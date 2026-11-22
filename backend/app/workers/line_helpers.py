"""Helper utilities for LINE inbound processing (delivery fallback, conversation upsert)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent, ReplyTokenExpiredError
from app.channels.factory import resolve_channel_adapter
from app.core.logging import get_logger
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Conversation, Message
from app.models.tenant import BotSetting
from app.rag.types import AnswerResult
from app.services.quota import increment_monthly_usage

logger = get_logger("app.workers.line_inbound")


def customer_message_content(event: InboundEvent) -> str:
    """Convert an inbound LINE event into stored message content."""
    if event.message_type == "text":
        return (event.text or "").strip()
    if event.message_type == "image":
        return "[รูปภาพ / สลิปโอนเงิน]"
    if event.message_type == "sticker":
        return "[สติกเกอร์]"
    return "[ข้อความสื่อที่ยังไม่รองรับ]"


def parse_event_dict(raw: dict[str, object]) -> InboundEvent:
    """Reconstruct a typed InboundEvent from serialized ARQ job payload."""
    raw_type = str(raw.get("message_type", "unsupported"))
    msg_type = (
        raw_type if raw_type in {"text", "image", "sticker", "unsupported"} else "unsupported"
    )
    text_raw = raw.get("text")
    rt_raw = raw.get("reply_token")
    ts_raw = raw.get("timestamp_ms", 0)
    return InboundEvent(
        event_id=str(raw["event_id"]),
        external_user_id=str(raw["external_user_id"]),
        message_type=msg_type,  # type: ignore[arg-type]
        text=str(text_raw) if isinstance(text_raw, str) else None,
        reply_token=str(rt_raw) if isinstance(rt_raw, str) else None,
        timestamp_ms=int(ts_raw) if isinstance(ts_raw, (int, float)) else 0,
    )


async def resolve_line_adapter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    channel_id: UUID,
    fernet_key: str,
) -> ChannelAdapter | None:
    """Load an active LINE channel under RLS and decrypt its access token."""
    return await resolve_channel_adapter(
        session_factory,
        tenant_id=tenant_id,
        channel_id=channel_id,
        fernet_key=fernet_key,
    )


async def load_handoff_keywords(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[str]:
    """Fetch the tenant's configured handoff trigger keywords."""
    row = (
        await session.execute(select(BotSetting).where(BotSetting.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None or not row.handoff_keywords:
        return ["แอดมิน", "คุยกับคน", "ติดต่อเจ้าหน้าที่"]
    return list(row.handoff_keywords)


async def upsert_conversation_and_save_customer_msg(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    event: InboundEvent,
    now: datetime | None = None,
) -> tuple[Conversation, bool]:
    """Upsert conversation row, save customer message, and report if profile fetch is needed."""
    ts = now or datetime.now(UTC)
    stmt = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.channel_id == channel_id,
        Conversation.external_user_id == event.external_user_id,
    )
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if conv is None:
        conv = Conversation(
            tenant_id=tenant_id,
            channel_id=channel_id,
            external_user_id=event.external_user_id,
            mode="bot",
            last_message_at=ts,
        )
        session.add(conv)
        await session.flush()
    else:
        conv.last_message_at = ts

    session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            role="customer",
            content=customer_message_content(event),
        )
    )
    return conv, conv.customer_name is None


async def save_bot_reply_and_usage(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    rag_result: AnswerResult,
) -> None:
    """Persist bot reply message and increment monthly LLM token/message rollup."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role="bot",
                content=rag_result.text,
                sources=[src.to_json_dict() for src in rag_result.sources],
                model=rag_result.tokens.model,
                input_tokens=rag_result.tokens.input_tokens,
                output_tokens=rag_result.tokens.output_tokens,
            )
        )
        conv_ref = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        ).scalar_one()
        conv_ref.last_message_at = datetime.now(UTC)
        await increment_monthly_usage(
            session,
            tenant_id=tenant_id,
            input_tokens=rag_result.tokens.input_tokens,
            output_tokens=rag_result.tokens.output_tokens,
        )


async def populate_customer_name(
    session_factory: async_sessionmaker[AsyncSession],
    adapter: ChannelAdapter,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    external_user_id: str,
) -> None:
    """Lazily fetch and persist customer display name from LINE Profile API."""
    profile = await adapter.get_profile(external_user_id)
    if not profile.display_name:
        return
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        ).scalar_one()
        conv.customer_name = profile.display_name


async def send_line_with_fallback(
    adapter: ChannelAdapter,
    *,
    event: InboundEvent,
    text: str,
) -> str:
    """Deliver outbound LINE text via Reply API, falling back to Push API on token expiry."""
    if event.reply_token:
        try:
            await adapter.send_reply(event.reply_token, text)
            return "reply"
        except ReplyTokenExpiredError:
            logger.info(
                "line_reply_token_expired_fallback_push",
                event_id=event.event_id,
                user_id=event.external_user_id,
            )
    await adapter.send_push(event.external_user_id, text)
    return "push"
