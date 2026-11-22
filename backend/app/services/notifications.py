"""Tenant notification helpers (in-app dashboard notifications + LINE group push)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import ChannelAdapter
from app.channels.factory import ChannelAdapterFactory
from app.core.logging import get_logger
from app.models.operations import Notification

logger = get_logger("app.services.notifications")

_REASON_LABELS: dict[str, str] = {
    "rag_low_confidence": "บอทไม่พบข้อมูลที่แน่ชัด",
    "keyword": "ลูกค้าขอติดต่อแอดมิน",
    "frustration": "ตรวจพบความไม่พอใจของลูกค้า",
    "image": "ลูกค้าส่งรูปภาพ/สลิป",
}


def handoff_reason_label(reason: str) -> str:
    """Return a concise Thai display label for a handoff trigger reason."""
    return _REASON_LABELS.get(reason, "ส่งต่อแอดมิน")


def format_handoff_alert(
    *,
    reason: str,
    customer_name: str | None,
    external_user_id: str,
    question: str,
    conversation_id: UUID,
) -> str:
    """Build a short Thai LINE push alert for the shop's admin notify group."""
    display_customer = customer_name or external_user_id
    snippet = question.strip().replace("\n", " ")
    if len(snippet) > 180:
        snippet = f"{snippet[:177]}..."
    label = handoff_reason_label(reason)
    return (
        f"[แจ้งเตือนส่งต่อแอดมิน]\n"
        f"สาเหตุ: {label}\n"
        f"ลูกค้า: {display_customer}\n"
        f"ข้อความ: {snippet}\n"
        f"แชท: {conversation_id}"
    )


def create_in_app_notification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    notif_type: str,
    title: str,
    body: str,
    metadata: dict[str, object] | None = None,
) -> Notification:
    """Stage an in-app Notification row inside the caller's tenant-scoped transaction."""
    notification = Notification(
        tenant_id=tenant_id,
        type=notif_type,
        title=title,
        body=body,
        payload=metadata or {},
    )
    session.add(notification)
    return notification


async def dispatch_handoff_line_alert(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    notify_target_id: str | None,
    notify_channel_id: UUID | None,
    fallback_channel_id: UUID,
    reason: str,
    customer_name: str | None,
    external_user_id: str,
    question: str,
    adapter_factory: ChannelAdapterFactory | None,
    fallback_adapter: ChannelAdapter | None = None,
) -> bool:
    """Push a Thai handoff alert to the tenant's configured LINE group/admin target.

    Failures are logged and swallowed so an external LINE outage never blocks
    the customer's fallback reply or database state transitions.
    """
    target_id = (notify_target_id or "").strip()
    if not target_id:
        return False

    target_channel_id = notify_channel_id or fallback_channel_id
    adapter: ChannelAdapter | None = None

    try:
        if target_channel_id == fallback_channel_id and fallback_adapter is not None:
            adapter = fallback_adapter
        elif adapter_factory is not None:
            adapter = await adapter_factory.get_adapter(
                tenant_id=tenant_id,
                channel_id=target_channel_id,
            )

        if adapter is None:
            logger.warning(
                "handoff_notify_channel_unavailable",
                tenant_id=str(tenant_id),
                channel_id=str(target_channel_id),
            )
            return False

        alert_text = format_handoff_alert(
            reason=reason,
            customer_name=customer_name,
            external_user_id=external_user_id,
            question=question,
            conversation_id=conversation_id,
        )
        await adapter.send_push(target_id, alert_text)
        logger.info(
            "handoff_line_alert_sent",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            target_id=target_id,
            reason=reason,
        )
        return True
    except Exception as exc:
        logger.warning(
            "handoff_line_alert_failed",
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            target_id=target_id,
            error=str(exc),
        )
        return False
