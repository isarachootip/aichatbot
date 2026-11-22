"""Tenant eligibility, trial/quota enforcement, monthly usage rollup, and notifications."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import get_plan_config
from app.models.messaging import Conversation
from app.models.operations import Notification
from app.models.tenant import Tenant, UsageMonthly

EligibilityReason = Literal["ok", "trial_expired", "tenant_inactive", "quota_exceeded"]


@dataclass(frozen=True)
class QuotaCheckResult:
    """Result of checking tenant subscription status and monthly message quota."""

    allowed: bool
    reason: EligibilityReason
    used_messages: int
    limit_messages: int


def current_usage_month(now: datetime | None = None) -> str:
    """Return the UTC billing month key formatted as YYYY-MM."""
    ts = now or datetime.now(UTC)
    return ts.astimezone(UTC).strftime("%Y-%m")


async def check_tenant_eligibility(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
) -> QuotaCheckResult:
    """Verify tenant trial/subscription status and monthly message quota before LLM call."""
    ts = now or datetime.now(UTC)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        return QuotaCheckResult(
            allowed=False,
            reason="tenant_inactive",
            used_messages=0,
            limit_messages=0,
        )

    plan = get_plan_config(tenant.plan)
    month = current_usage_month(ts)
    usage = (
        await session.execute(
            select(UsageMonthly).where(
                UsageMonthly.tenant_id == tenant_id,
                UsageMonthly.month == month,
            )
        )
    ).scalar_one_or_none()
    used = usage.message_count if usage is not None else 0

    if tenant.status == "trial_expired":
        return QuotaCheckResult(
            allowed=False,
            reason="trial_expired",
            used_messages=used,
            limit_messages=plan.monthly_messages,
        )
    if tenant.status == "trial" and tenant.trial_ends_at is not None:
        trial_end = (
            tenant.trial_ends_at
            if tenant.trial_ends_at.tzinfo is not None
            else tenant.trial_ends_at.replace(tzinfo=UTC)
        )
        if trial_end <= ts:
            return QuotaCheckResult(
                allowed=False,
                reason="trial_expired",
                used_messages=used,
                limit_messages=plan.monthly_messages,
            )
    if tenant.status not in {"trial", "active"}:
        return QuotaCheckResult(
            allowed=False,
            reason="tenant_inactive",
            used_messages=used,
            limit_messages=plan.monthly_messages,
        )

    if used >= plan.monthly_messages:
        return QuotaCheckResult(
            allowed=False,
            reason="quota_exceeded",
            used_messages=used,
            limit_messages=plan.monthly_messages,
        )

    return QuotaCheckResult(
        allowed=True,
        reason="ok",
        used_messages=used,
        limit_messages=plan.monthly_messages,
    )


async def increment_monthly_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    input_tokens: int,
    output_tokens: int,
    message_increment: int = 1,
    now: datetime | None = None,
) -> None:
    """Atomically upsert and increment monthly message and LLM token counters."""
    month = current_usage_month(now)
    stmt = (
        pg_insert(UsageMonthly)
        .values(
            tenant_id=tenant_id,
            month=month,
            message_count=message_increment,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "month"],
            set_={
                "message_count": UsageMonthly.message_count + message_increment,
                "input_tokens": UsageMonthly.input_tokens + input_tokens,
                "output_tokens": UsageMonthly.output_tokens + output_tokens,
            },
        )
    )
    await session.execute(stmt)


async def switch_to_human_and_notify(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    notif_type: str,
    title: str,
    body: str,
    metadata: dict[str, object] | None = None,
) -> None:
    """Switch conversation to human mode and create an in-app owner notification."""
    conversation.mode = "human"
    session.add(
        Notification(
            tenant_id=tenant_id,
            type=notif_type,
            title=title,
            body=body,
            payload=metadata or {},
        )
    )
