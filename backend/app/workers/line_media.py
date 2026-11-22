"""Non-text LINE media handlers (images/slips with handoff, stickers without handoff)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent
from app.channels.factory import ChannelAdapterFactory
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Conversation, Message
from app.services.handoff import execute_handoff

IMAGE_HANDOFF_REPLY = (
    "ได้รับรูปภาพเรียบร้อยแล้วค่ะ ขออนุญาตให้แอดมินตรวจสอบและตอบกลับสักครู่นะคะ"
)
STICKER_FALLBACK_REPLY = (
    "ขอบคุณสำหรับสติกเกอร์ค่ะ หากมีคำถามเกี่ยวกับสินค้าหรือบริการ พิมพ์สอบถามได้เลยนะคะ"
)
UNSUPPORTED_MEDIA_REPLY = (
    "ขออภัยค่ะ ระบบยังไม่รองรับข้อความประเภทนี้ รบกวนพิมพ์ข้อความสอบถามได้เลยนะคะ"
)


@dataclass(frozen=True)
class LineHandleOutcome:
    """Structured result emitted by handle_line_event for logging and testing."""

    action: str
    conversation_id: UUID | None = None
    delivery_method: str | None = None
    handoff: bool = False


async def handle_non_text_event(
    session_factory: async_sessionmaker[AsyncSession],
    adapter: ChannelAdapter,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    event: InboundEvent,
    deliver_fn: object,
    adapter_factory: ChannelAdapterFactory | None = None,
) -> LineHandleOutcome:
    """Reply politely to images (with handoff) and stickers/other media (without handoff)."""
    if event.message_type == "image":
        await execute_handoff(
            session_factory,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            question="[รูปภาพ / สลิปโอนเงิน]",
            reason="image",
            save_bot_message=True,
            bot_message_override=IMAGE_HANDOFF_REPLY,
            adapter_factory=adapter_factory,
            fallback_adapter=adapter,
        )
        delivery: str = await deliver_fn(adapter, event=event, text=IMAGE_HANDOFF_REPLY)  # type: ignore[operator]
        return LineHandleOutcome(
            action="image_handoff",
            conversation_id=conversation_id,
            delivery_method=delivery,
            handoff=True,
        )

    reply_text = (
        STICKER_FALLBACK_REPLY if event.message_type == "sticker" else UNSUPPORTED_MEDIA_REPLY
    )
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role="bot",
                content=reply_text,
            )
        )
        conv.last_message_at = datetime.now(UTC)

    delivery = await deliver_fn(adapter, event=event, text=reply_text)  # type: ignore[operator]
    return LineHandleOutcome(
        action=f"{event.message_type}_fallback",
        conversation_id=conversation_id,
        delivery_method=delivery,
        handoff=False,
    )
