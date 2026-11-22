"""Grounded Thai RAG answer generation with structured handoff and source citations."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Message
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import Embedder
from app.rag.llm import LLMClient
from app.rag.prompts import (
    append_customer_citations,
    build_system_prompt,
    build_user_message,
    extract_citations,
    format_history,
)
from app.rag.retrieval import hybrid_search
from app.rag.types import (
    AnswerResult,
    BotPromptConfig,
    ConversationTurn,
    RetrievedChunk,
    StructuredLLMResponse,
    TokenUsage,
)

HISTORY_LIMIT = 10


async def _load_bot_config(session: AsyncSession, tenant_id: UUID) -> BotPromptConfig:
    setting = (
        await session.execute(select(BotSetting).where(BotSetting.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if setting is not None:
        return BotPromptConfig.from_orm(setting)

    tenant_name = (
        await session.execute(select(Tenant.name).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return BotPromptConfig.from_orm(None, fallback_shop_name=tenant_name or "ร้านค้า")


async def _load_recent_history(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = HISTORY_LIMIT,
) -> list[ConversationTurn]:
    stmt = (
        select(Message.role, Message.content)
        .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).all())
    rows.reverse()
    turns: list[ConversationTurn] = []
    for role, content in rows:
        if role == "customer":
            turns.append(ConversationTurn(role="customer", content=content))
        elif role == "bot":
            turns.append(ConversationTurn(role="bot", content=content))
        elif role == "agent":
            turns.append(ConversationTurn(role="agent", content=content))
    return turns


def _build_messages_payload(
    history: Sequence[ConversationTurn],
    question: str,
    chunks: Sequence[RetrievedChunk],
) -> list[dict[str, str]]:
    messages = format_history(history, limit=HISTORY_LIMIT)
    user_content = build_user_message(question, chunks)
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{user_content}"
    else:
        messages.append({"role": "user", "content": user_content})
    return messages


async def _call_with_optional_escalation(
    llm_client: LLMClient,
    settings: Settings,
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> StructuredLLMResponse:
    primary = await llm_client.generate_grounded_reply(
        system_prompt=system_prompt,
        messages=messages,
        model=settings.llm_default_model,
    )
    can_escalate = (
        settings.llm_escalation_enabled
        and primary.handoff
        and primary.handoff_reason != "prompt_injection_detected"
        and bool(settings.llm_escalation_model)
        and settings.llm_escalation_model != settings.llm_default_model
    )
    if not can_escalate:
        return primary

    escalated = await llm_client.generate_grounded_reply(
        system_prompt=system_prompt,
        messages=messages,
        model=settings.llm_escalation_model,
    )
    return StructuredLLMResponse(
        answer_text=escalated.answer_text,
        handoff=escalated.handoff,
        handoff_reason=escalated.handoff_reason,
        cited_chunk_indices=escalated.cited_chunk_indices,
        input_tokens=primary.input_tokens + escalated.input_tokens,
        output_tokens=primary.output_tokens + escalated.output_tokens,
        model=escalated.model,
    )


async def answer(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    llm_client: LLMClient,
    settings: Settings,
    *,
    tenant_id: UUID,
    question: str,
    conversation_id: UUID | None = None,
) -> AnswerResult:
    """Answer a customer question grounded strictly in the tenant's knowledge base."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        bot_config = await _load_bot_config(session, tenant_id)
        history = (
            await _load_recent_history(
                session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                limit=HISTORY_LIMIT,
            )
            if conversation_id is not None
            else []
        )
        chunks = await hybrid_search(session, embedder, tenant_id=tenant_id, query=question)

    if not chunks:
        return AnswerResult(
            text=bot_config.fallback_message,
            sources=[],
            handoff=True,
            handoff_reason="no_relevant_chunks",
            tokens=TokenUsage(input_tokens=0, output_tokens=0, model=settings.llm_default_model),
        )

    llm_resp = await _call_with_optional_escalation(
        llm_client,
        settings,
        system_prompt=build_system_prompt(bot_config),
        messages=_build_messages_payload(history, question, chunks),
    )
    tokens = TokenUsage(
        input_tokens=llm_resp.input_tokens,
        output_tokens=llm_resp.output_tokens,
        model=llm_resp.model,
    )

    if llm_resp.handoff or not llm_resp.answer_text:
        return AnswerResult(
            text=bot_config.fallback_message,
            sources=[],
            handoff=True,
            handoff_reason=llm_resp.handoff_reason or "unanswerable",
            tokens=tokens,
        )

    citations = extract_citations(chunks, llm_resp.cited_chunk_indices)
    final_text = (
        append_customer_citations(llm_resp.answer_text, citations)
        if bot_config.show_citations_to_customer
        else llm_resp.answer_text
    )
    return AnswerResult(
        text=final_text,
        sources=citations,
        handoff=False,
        handoff_reason=None,
        tokens=tokens,
    )
