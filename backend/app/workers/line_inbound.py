"""ARQ worker pipeline processing inbound LINE Messaging API events."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent
from app.channels.factory import ChannelAdapterFactory, DatabaseChannelAdapterFactory
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.tenant_context import tenant_scoped_session
from app.rag.embeddings import Embedder
from app.rag.generate import answer
from app.rag.llm import LLMClient
from app.services.debounce import BurstDebouncer, collect_unreplied_customer_text
from app.services.handoff import evaluate_pre_llm_handoff, execute_handoff
from app.services.quota import check_tenant_eligibility, handle_ineligible_tenant
from app.workers.line_helpers import (
    load_handoff_keywords,
    parse_event_dict,
    populate_customer_name,
    resolve_line_adapter,
    save_bot_reply_and_usage,
    send_line_with_fallback,
    upsert_conversation_and_save_customer_msg,
)
from app.workers.line_media import LineHandleOutcome, handle_non_text_event

logger = get_logger("app.workers.line_inbound")


async def handle_line_event(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    llm_client: LLMClient,
    debouncer: BurstDebouncer,
    settings: Settings,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    event: InboundEvent,
    adapter: ChannelAdapter | None = None,
    notify_adapter_factory: ChannelAdapterFactory | None = None,
) -> LineHandleOutcome:
    """Process one inbound LINE event end-to-end under PostgreSQL FORCE RLS."""
    resolved_adapter = adapter or await resolve_line_adapter(
        session_factory,
        tenant_id=tenant_id,
        channel_id=channel_id,
        fernet_key=settings.fernet_key,
    )
    if resolved_adapter is None:
        return LineHandleOutcome(action="channel_missing")

    alert_factory: ChannelAdapterFactory = notify_adapter_factory or DatabaseChannelAdapterFactory(
        session_factory, fernet_key=settings.fernet_key
    )

    # 1. Always upsert conversation and persist customer message first
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv, needs_profile = await upsert_conversation_and_save_customer_msg(
            session, tenant_id=tenant_id, channel_id=channel_id, event=event
        )
        conv_id, conv_mode = conv.id, conv.mode

    if needs_profile:
        await populate_customer_name(
            session_factory, resolved_adapter,
            tenant_id=tenant_id, conversation_id=conv_id, external_user_id=event.external_user_id,
        )

    # 2. Stay silent in human mode or if superseded by a newer message in the 2.5s burst
    if conv_mode == "human":
        return LineHandleOutcome(action="silent_human_mode", conversation_id=conv_id)

    if event.message_type == "text" and not await debouncer.is_latest(
        tenant_id=tenant_id, channel_id=channel_id,
        external_user_id=event.external_user_id, event_id=event.event_id,
    ):
        return LineHandleOutcome(action="debounced_skip", conversation_id=conv_id)

    # 3. Enforce tenant trial/subscription status and monthly quota BEFORE calling LLM
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        eligibility = await check_tenant_eligibility(session, tenant_id=tenant_id)
        if not eligibility.allowed:
            await handle_ineligible_tenant(
                session, tenant_id=tenant_id, conversation_id=conv_id, eligibility=eligibility
            )
            return LineHandleOutcome(
                action=f"silent_{eligibility.reason}", conversation_id=conv_id, handoff=True,
            )

        is_text = event.message_type == "text"
        combined_question = (
            await collect_unreplied_customer_text(
                session, tenant_id=tenant_id,
                conversation_id=conv_id, fallback_text=event.text or "",
            )
            if is_text
            else ""
        )
        handoff_keywords = (
            await load_handoff_keywords(session, tenant_id=tenant_id) if is_text else []
        )

    # 4. Handle images (handoff) and stickers/unsupported media (polite fallback)
    if event.message_type != "text":
        return await handle_non_text_event(
            session_factory, resolved_adapter,
            tenant_id=tenant_id, conversation_id=conv_id, event=event,
            deliver_fn=send_line_with_fallback, adapter_factory=alert_factory,
        )

    # 5. Pre-LLM handoff triggers (keyword match or Thai strong frustration)
    pre_handoff = evaluate_pre_llm_handoff(combined_question, handoff_keywords)
    if pre_handoff is not None:
        handoff_res = await execute_handoff(
            session_factory, tenant_id=tenant_id, conversation_id=conv_id,
            question=combined_question, reason=pre_handoff.reason,
            matched_term=pre_handoff.matched_term, save_bot_message=True,
            adapter_factory=alert_factory, fallback_adapter=resolved_adapter,
        )
        delivery = await send_line_with_fallback(
            resolved_adapter, event=event, text=handoff_res.fallback_message
        )
        return LineHandleOutcome(
            action=f"handoff_{pre_handoff.reason}",
            conversation_id=conv_id, delivery_method=delivery, handoff=True,
        )

    # 6. Text flow: loading -> RAG -> save message + usage -> handoff if flagged -> reply
    await resolved_adapter.show_loading(event.external_user_id, seconds=20)
    rag_result = await answer(
        session_factory, embedder, llm_client, settings,
        tenant_id=tenant_id, conversation_id=conv_id, question=combined_question,
    )
    await save_bot_reply_and_usage(
        session_factory, tenant_id=tenant_id, conversation_id=conv_id, rag_result=rag_result,
    )
    if rag_result.handoff:
        await execute_handoff(
            session_factory, tenant_id=tenant_id, conversation_id=conv_id,
            question=combined_question, reason="rag_low_confidence",
            matched_term=rag_result.handoff_reason, save_bot_message=False,
            adapter_factory=alert_factory, fallback_adapter=resolved_adapter,
        )
    delivery = await send_line_with_fallback(resolved_adapter, event=event, text=rag_result.text)
    logger.info(
        "line_event_processed",
        tenant_id=str(tenant_id), conversation_id=str(conv_id),
        delivery=delivery, handoff=rag_result.handoff,
    )
    return LineHandleOutcome(
        action="handoff_rag" if rag_result.handoff else "replied",
        conversation_id=conv_id, delivery_method=delivery, handoff=rag_result.handoff,
    )


async def process_line_event_job(
    ctx: dict[str, object],
    tenant_id_str: str,
    channel_id_str: str,
    raw_event: dict[str, object],
) -> dict[str, object]:
    """ARQ task entrypoint for processing inbound LINE webhook events."""
    settings, session_factory = ctx["settings"], ctx["session_factory"]
    embedder, llm_client, debouncer = ctx["embedder"], ctx["llm_client"], ctx["debouncer"]
    if (
        not isinstance(settings, Settings)
        or not isinstance(embedder, Embedder)
        or not isinstance(llm_client, LLMClient)
        or not isinstance(debouncer, BurstDebouncer)
    ):
        raise RuntimeError("ARQ worker context missing RAG/LINE dependencies")

    outcome = await handle_line_event(
        session_factory,  # type: ignore[arg-type]
        embedder, llm_client, debouncer, settings,
        tenant_id=UUID(tenant_id_str), channel_id=UUID(channel_id_str),
        event=parse_event_dict(raw_event),
    )
    conv_str = str(outcome.conversation_id) if outcome.conversation_id else None
    return {
        "action": outcome.action, "conversation_id": conv_str,
        "delivery_method": outcome.delivery_method, "handoff": outcome.handoff,
    }
