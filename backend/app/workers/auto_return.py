"""ARQ periodic cron job returning inactive human-mode conversations back to the bot."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.tenant_context import list_active_tenant_ids, tenant_scoped_session
from app.models.messaging import Conversation
from app.models.tenant import Tenant

logger = get_logger("app.workers.auto_return")


@dataclass(frozen=True)
class AutoReturnSummary:
    """Counts emitted by a single auto-return sweep across tenants."""

    tenants_checked: int
    conversations_returned: int


async def auto_return_inactive_conversations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> AutoReturnSummary:
    """Return human-mode conversations to bot mode after N hours of agent inactivity.

    Inactivity is measured from ``COALESCE(last_agent_reply_at, last_message_at)``
    against each tenant's ``tenants.auto_return_hours`` setting under FORCE RLS.
    Tenants with ``auto_return_hours <= 0`` are skipped (auto-return disabled).
    """
    ts = now or datetime.now(UTC)

    async with session_factory() as lookup_session, lookup_session.begin():
        tenant_ids = await list_active_tenant_ids(lookup_session)

    returned_total = 0
    for tenant_id in tenant_ids:
        async with tenant_scoped_session(session_factory, tenant_id) as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            ).scalar_one_or_none()
            if tenant is None or tenant.auto_return_hours <= 0:
                continue

            cutoff = ts - timedelta(hours=tenant.auto_return_hours)
            last_activity = func.coalesce(
                Conversation.last_agent_reply_at,
                Conversation.last_message_at,
            )
            stmt = select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.mode == "human",
                last_activity <= cutoff,
            )
            stale_conversations = (await session.execute(stmt)).scalars().all()
            for conv in stale_conversations:
                conv.mode = "bot"

            if stale_conversations:
                returned_total += len(stale_conversations)
                logger.info(
                    "conversations_auto_returned_to_bot",
                    tenant_id=str(tenant_id),
                    count=len(stale_conversations),
                    auto_return_hours=tenant.auto_return_hours,
                )

    return AutoReturnSummary(
        tenants_checked=len(tenant_ids),
        conversations_returned=returned_total,
    )


async def auto_return_inactive_conversations_job(
    ctx: dict[str, object],
) -> dict[str, int]:
    """ARQ cron entrypoint running periodic human-to-bot auto-return sweeps."""
    session_factory = ctx.get("session_factory")
    if session_factory is None:
        raise RuntimeError("ARQ worker context missing session_factory")

    summary = await auto_return_inactive_conversations(session_factory)  # type: ignore[arg-type]
    return {
        "tenants_checked": summary.tenants_checked,
        "conversations_returned": summary.conversations_returned,
    }
