"""Tenant self-serve signup, dev login, and authenticated profile summary service."""

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.plans import get_plan_config
from app.core.security import AuthContext, UserRole, create_dev_access_token
from app.core.tenant_context import resolve_user_by_email, tenant_scoped_session
from app.models.operations import Notification
from app.models.tenant import BotSetting, Subscription, Tenant, UsageMonthly, User
from app.schemas.auth import AuthTokenResponse, MeResponse
from app.services.quota import current_usage_month

TRIAL_DURATION_DAYS = 7


class EmailAlreadyRegisteredError(ValueError):
    """Raised when signup attempts to register an already existing email."""


class UserNotFoundError(LookupError):
    """Raised when dev login cannot locate a registered user by email."""


def _normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
        raise ValueError("Invalid email address format")
    return cleaned


def _compute_trial_days_remaining(trial_ends_at: datetime | None, *, now: datetime) -> int:
    if trial_ends_at is None:
        return 0
    end = trial_ends_at if trial_ends_at.tzinfo is not None else trial_ends_at.replace(tzinfo=UTC)
    seconds_left = (end - now).total_seconds()
    return 0 if seconds_left <= 0 else math.ceil(seconds_left / 86_400)


def _issue_dev_token(settings: Settings, *, user_id: UUID, email: str) -> str | None:
    if settings.app_env in {"development", "test"} and not settings.supabase_jwks_url:
        return create_dev_access_token(settings, user_id=user_id, email=email)
    return None


async def signup_shop(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    shop_name: str,
    email: str,
    user_id: UUID | None = None,
    now: datetime | None = None,
) -> AuthTokenResponse:
    """Create a 7-day trial tenant, default bot settings, subscription, and owner user."""
    cleaned_shop = shop_name.strip()
    if not cleaned_shop:
        raise ValueError("Shop name must not be blank")
    cleaned_email = _normalize_email(email)

    async with session_factory() as lookup_session, lookup_session.begin():
        if await resolve_user_by_email(lookup_session, cleaned_email) is not None:
            raise EmailAlreadyRegisteredError("Email is already registered")

    ts = now or datetime.now(UTC)
    trial_ends = ts + timedelta(days=TRIAL_DURATION_DAYS)
    tenant_id = uuid4()
    owner_id = user_id or uuid4()

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        session.add(
            Tenant(
                id=tenant_id, name=cleaned_shop, plan="trial",
                status="trial", trial_ends_at=trial_ends,
            )
        )
        await session.flush()
        session.add(
            User(
                id=owner_id, tenant_id=tenant_id, email=cleaned_email,
                role="owner", is_super_admin=False,
            )
        )
        session.add(BotSetting(tenant_id=tenant_id, shop_name=cleaned_shop))
        session.add(
            Subscription(
                tenant_id=tenant_id, plan="trial", status="trialing",
                current_period_end=trial_ends,
            )
        )

    return AuthTokenResponse(
        access_token=_issue_dev_token(settings, user_id=owner_id, email=cleaned_email),
        user_id=owner_id,
        tenant_id=tenant_id,
        email=cleaned_email,
        role="owner",
        shop_name=cleaned_shop,
        trial_ends_at=trial_ends,
    )


async def dev_login_by_email(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    email: str,
) -> AuthTokenResponse:
    """Authenticate a local dev/test user by email and return a signed Dev JWT."""
    if settings.app_env not in {"development", "test"} or settings.supabase_jwks_url:
        raise PermissionError("Dev login is disabled when Supabase Auth or production is active")

    cleaned_email = _normalize_email(email)
    async with session_factory() as lookup_session, lookup_session.begin():
        resolved = await resolve_user_by_email(lookup_session, cleaned_email)
    if resolved is None:
        raise UserNotFoundError("User not found")

    user_id, tenant_id, role_str = resolved
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one()
        shop_name, trial_ends = tenant.name, tenant.trial_ends_at

    role_val: UserRole = role_str  # type: ignore[assignment]
    return AuthTokenResponse(
        access_token=create_dev_access_token(settings, user_id=user_id, email=cleaned_email),
        user_id=user_id,
        tenant_id=tenant_id,
        email=cleaned_email,
        role=role_val,
        shop_name=shop_name,
        trial_ends_at=trial_ends,
    )


async def get_me_summary(
    session_factory: async_sessionmaker[AsyncSession],
    auth: AuthContext,
    *,
    now: datetime | None = None,
) -> MeResponse:
    """Load the caller's tenant profile, trial countdown, quota usage, and unread alerts."""
    ts = now or datetime.now(UTC)
    month = current_usage_month(ts)

    async with tenant_scoped_session(session_factory, auth.tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == auth.tenant_id))
        ).scalar_one()
        usage = (
            await session.execute(
                select(UsageMonthly).where(
                    UsageMonthly.tenant_id == auth.tenant_id, UsageMonthly.month == month
                )
            )
        ).scalar_one_or_none()
        unread_count = int(
            (
                await session.execute(
                    select(func.count(Notification.id)).where(
                        Notification.tenant_id == auth.tenant_id, Notification.read_at.is_(None)
                    )
                )
            ).scalar_one()
        )

    plan = get_plan_config(tenant.plan)
    return MeResponse(
        user_id=auth.user_id, tenant_id=auth.tenant_id, email=auth.email,
        role=auth.role, is_super_admin=auth.is_super_admin, shop_name=tenant.name,
        plan=tenant.plan, status=tenant.status, trial_ends_at=tenant.trial_ends_at,
        trial_days_remaining=_compute_trial_days_remaining(tenant.trial_ends_at, now=ts),
        used_messages=usage.message_count if usage is not None else 0,
        limit_messages=plan.monthly_messages, max_channels=plan.max_channels,
        max_documents=plan.max_documents, unread_notifications=unread_count,
    )
