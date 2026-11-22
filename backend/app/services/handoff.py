"""Human handoff trigger evaluation and unified execution pipeline."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter
from app.channels.factory import ChannelAdapterFactory
from app.core.logging import get_logger
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Conversation, Message, UnansweredQuestion
from app.models.tenant import BotSetting
from app.services.notifications import (
    create_in_app_notification,
    dispatch_handoff_line_alert,
    handoff_reason_label,
)
from app.services.sentiment import detect_strong_frustration

logger = get_logger("app.services.handoff")

HandoffReason = Literal["rag_low_confidence", "keyword", "frustration", "image"]
PreLLMReason = Literal["keyword", "frustration"]

DEFAULT_FALLBACK_MESSAGE = (
    "ขออภัยค่ะ ข้อมูลส่วนนี้ขออนุญาตให้แอดมินตรวจสอบและติดต่อกลับนะคะ"
)


@dataclass(frozen=True)
class PreLLMHandoffMatch:
    """Trigger detected before invoking the LLM (saves cost and latency)."""

    reason: PreLLMReason
    matched_term: str


@dataclass(frozen=True)
class HandoffExecutionResult:
    """Structured outcome of executing a human handoff."""

    conversation_id: UUID
    reason: HandoffReason
    fallback_message: str
    line_alert_sent: bool


def evaluate_pre_llm_handoff(
    text: str,
    handoff_keywords: Sequence[str],
) -> PreLLMHandoffMatch | None:
    """Check tenant handoff keywords and Thai frustration sentiment before LLM calls."""
    normalized = text.strip().lower()
    if not normalized:
        return None

    for raw_keyword in handoff_keywords:
        keyword = raw_keyword.strip()
        if keyword and keyword.lower() in normalized:
            return PreLLMHandoffMatch(reason="keyword", matched_term=keyword)

    sentiment = detect_strong_frustration(text)
    if sentiment.is_frustrated:
        return PreLLMHandoffMatch(
            reason="frustration",
            matched_term=sentiment.matched_phrase or "frustration",
        )
    return None


async def execute_handoff(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    question: str,
    reason: HandoffReason,
    matched_term: str | None = None,
    save_bot_message: bool = True,
    bot_message_override: str | None = None,
    adapter_factory: ChannelAdapterFactory | None = None,
    fallback_adapter: ChannelAdapter | None = None,
    now: datetime | None = None,
) -> HandoffExecutionResult:
    """Switch conversation to human mode, log unanswered question, and notify tenant."""
    ts = now or datetime.now(UTC)

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        bot_settings = (
            await session.execute(
                select(BotSetting).where(BotSetting.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

        fallback_text = (
            bot_message_override
            if bot_message_override is not None
            else (
                bot_settings.fallback_message
                if bot_settings is not None
                else DEFAULT_FALLBACK_MESSAGE
            )
        )
        notify_target_id = bot_settings.handoff_notify_target_id if bot_settings else None
        notify_channel_id = bot_settings.handoff_notify_channel_id if bot_settings else None

        conv.mode = "human"
        conv.last_message_at = ts

        session.add(
            UnansweredQuestion(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                question=question,
            )
        )
        if save_bot_message:
            session.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role="bot",
                    content=fallback_text,
                )
            )

        reason_label = handoff_reason_label(reason)
        customer_label = conv.customer_name or conv.external_user_id
        metadata: dict[str, object] = {
            "conversation_id": str(conversation_id),
            "reason": reason,
            "customer_name": conv.customer_name,
            "external_user_id": conv.external_user_id,
            "question": question,
        }
        if matched_term:
            metadata["matched_term"] = matched_term

        create_in_app_notification(
            session,
            tenant_id=tenant_id,
            notif_type="handoff",
            title=f"ส่งต่อแอดมิน: {reason_label}",
            body=f"ลูกค้า {customer_label}: {question[:200]}",
            metadata=metadata,
        )

        conv_channel_id = conv.channel_id
        conv_customer_name = conv.customer_name
        conv_external_user_id = conv.external_user_id

    line_alert_sent = await dispatch_handoff_line_alert(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        notify_target_id=notify_target_id,
        notify_channel_id=notify_channel_id,
        fallback_channel_id=conv_channel_id,
        reason=reason,
        customer_name=conv_customer_name,
        external_user_id=conv_external_user_id,
        question=question,
        adapter_factory=adapter_factory,
        fallback_adapter=fallback_adapter,
    )

    logger.info(
        "handoff_executed",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        reason=reason,
        line_alert_sent=line_alert_sent,
    )
    return HandoffExecutionResult(
        conversation_id=conversation_id,
        reason=reason,
        fallback_message=fallback_text,
        line_alert_sent=line_alert_sent,
    )
