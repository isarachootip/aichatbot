"""Tenant analytics aggregation service (messages/day, auto-resolved %, handoffs)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.plans import get_plan_config
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Conversation, Message, UnansweredQuestion
from app.models.tenant import Tenant, UsageMonthly
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    DailyMessageCount,
    TopUnansweredQuestion,
)
from app.services.quota import current_usage_month


async def get_analytics_summary(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    days: int = 14,
    now: datetime | None = None,
) -> AnalyticsSummaryResponse:
    """Compute tenant message trends, auto-resolved rate, handoff rate, and top gaps."""
    ts = now or datetime.now(UTC)
    window_days = max(1, min(days, 90))
    start_date = (ts - timedelta(days=window_days - 1)).date()
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    month = current_usage_month(ts)

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one()
        plan = get_plan_config(tenant.plan)

        total_conversations = int(
            (
                await session.execute(
                    select(func.count(Conversation.id)).where(Conversation.tenant_id == tenant_id)
                )
            ).scalar_one()
        )

        # Daily message counts grouped by UTC date and role
        day_col = cast(func.timezone("UTC", Message.created_at), Date)
        daily_rows = (
            await session.execute(
                select(day_col, Message.role, func.count(Message.id))
                .where(Message.tenant_id == tenant_id, Message.created_at >= start_dt)
                .group_by(day_col, Message.role)
            )
        ).all()

        total_handoffs = int(
            (
                await session.execute(
                    select(func.count(UnansweredQuestion.id)).where(
                        UnansweredQuestion.tenant_id == tenant_id,
                        UnansweredQuestion.created_at >= start_dt,
                    )
                )
            ).scalar_one()
        )

        top_unanswered_rows = (
            await session.execute(
                select(UnansweredQuestion.question, func.count(UnansweredQuestion.id).label("cnt"))
                .where(UnansweredQuestion.tenant_id == tenant_id)
                .group_by(UnansweredQuestion.question)
                .order_by(func.count(UnansweredQuestion.id).desc())
                .limit(10)
            )
        ).all()

        usage = (
            await session.execute(
                select(UsageMonthly).where(
                    UsageMonthly.tenant_id == tenant_id,
                    UsageMonthly.month == month,
                )
            )
        ).scalar_one_or_none()

    buckets: dict[str, dict[str, int]] = {}
    for offset in range(window_days):
        d_str = (start_date + timedelta(days=offset)).isoformat()
        buckets[d_str] = {"customer": 0, "bot": 0, "agent": 0}

    total_customer = 0
    total_bot = 0
    for row_date, role, count in daily_rows:
        d_key = row_date.isoformat()
        cnt = int(count)
        if d_key in buckets and role in buckets[d_key]:
            buckets[d_key][role] = cnt
        if role == "customer":
            total_customer += cnt
        elif role == "bot":
            total_bot += cnt

    if total_bot > 0:
        handoff_rate = round(min(1.0, total_handoffs / total_bot) * 100.0, 1)
        auto_resolved_rate = round(max(0.0, 100.0 - handoff_rate), 1)
    else:
        handoff_rate = 0.0
        auto_resolved_rate = 0.0

    return AnalyticsSummaryResponse(
        days=window_days,
        total_conversations=total_conversations,
        total_customer_messages=total_customer,
        total_bot_messages=total_bot,
        total_handoffs=total_handoffs,
        auto_resolved_rate=auto_resolved_rate,
        handoff_rate=handoff_rate,
        used_messages_this_month=usage.message_count if usage is not None else 0,
        limit_messages_this_month=plan.monthly_messages,
        messages_per_day=[
            DailyMessageCount(
                date=d_str,
                customer_messages=counts["customer"],
                bot_messages=counts["bot"],
                agent_messages=counts["agent"],
            )
            for d_str, counts in buckets.items()
        ],
        top_unanswered_questions=[
            TopUnansweredQuestion(question=str(q), count=int(cnt))
            for q, cnt in top_unanswered_rows
        ],
    )
