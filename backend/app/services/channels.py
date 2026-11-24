"""Messaging channel creation (Fernet-encrypted), listing, deletion, and LINE probe."""

from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.core.plans import get_plan_config
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Channel
from app.models.tenant import Tenant
from app.schemas.channels import ChannelResponse, ChannelTestResponse, ChannelType

LINE_BOT_INFO_URL = "https://api.line.me/v2/bot/info"


class ChannelNotFoundError(LookupError):
    """Raised when a channel does not exist within the caller's tenant."""


class ChannelLimitExceededError(ValueError):
    """Raised when the tenant reaches their subscription plan's max_channels."""


class ChannelTester(Protocol):
    """Protocol for verifying outbound channel credentials."""

    async def test_line_token(self, access_token: str) -> ChannelTestResponse: ...


class HttpxChannelTester:
    """Live LINE Messaging API connection probe using GET /v2/bot/info."""

    async def test_line_token(self, access_token: str) -> ChannelTestResponse:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(LINE_BOT_INFO_URL, headers=headers)
            if resp.status_code == 200:
                payload = resp.json()
                return ChannelTestResponse(
                    ok=True,
                    bot_name=str(payload.get("displayName", "")) or None,
                    basic_id=str(payload.get("basicId", "")) or None,
                )
            return ChannelTestResponse(
                ok=False,
                error=f"LINE API returned HTTP {resp.status_code}",
            )
        except Exception as exc:
            return ChannelTestResponse(ok=False, error=str(exc))


def _webhook_url(settings: Settings, channel: Channel) -> str:
    base = settings.public_api_base_url.rstrip("/")
    return f"{base}/webhooks/{channel.type}/{channel.id}"


def _to_response(settings: Settings, channel: Channel) -> ChannelResponse:
    ch_type: ChannelType = channel.type  # type: ignore[assignment]
    return ChannelResponse(
        id=channel.id,
        type=ch_type,
        name=channel.name,
        active=channel.active,
        webhook_url=_webhook_url(settings, channel),
        created_at=channel.created_at,
    )


async def create_line_channel(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    tenant_id: UUID,
    name: str,
    channel_access_token: str,
    webhook_secret: str,
) -> ChannelResponse:
    """Encrypt credentials with Fernet, enforce plan channel limit, and save channel."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Channel name must not be blank")
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY is not configured on the server")

    encrypted = encrypt_credentials(
        {"channel_access_token": channel_access_token.strip()},
        fernet_key=settings.fernet_key,
    )

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one()
        plan = get_plan_config(tenant.plan)
        existing_count = int(
            (
                await session.execute(
                    select(func.count(Channel.id)).where(
                        Channel.tenant_id == tenant_id,
                        Channel.active.is_(True),
                    )
                )
            ).scalar_one()
        )
        if existing_count >= plan.max_channels:
            raise ChannelLimitExceededError(
                f"Channel limit reached ({plan.max_channels} for plan '{plan.name}')"
            )

        channel = Channel(
            id=uuid4(),
            tenant_id=tenant_id,
            type="line",
            name=cleaned_name,
            credentials_encrypted=encrypted,
            webhook_secret=webhook_secret.strip(),
            active=True,
        )
        session.add(channel)
        await session.flush()
        return _to_response(settings, channel)


async def list_channels(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    tenant_id: UUID,
) -> list[ChannelResponse]:
    """List all tenant channels newest-first without exposing encrypted secrets."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        rows = (
            await session.execute(
                select(Channel)
                .where(Channel.tenant_id == tenant_id)
                .order_by(Channel.created_at.desc())
            )
        ).scalars().all()
    return [_to_response(settings, row) for row in rows]


async def delete_channel(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    channel_id: UUID,
) -> None:
    """Remove a channel owned by the tenant under FORCE RLS."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        channel = (
            await session.execute(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if channel is None:
            raise ChannelNotFoundError(f"Channel {channel_id} not found")
        await session.delete(channel)


async def test_channel_connection(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tester: ChannelTester,
    *,
    tenant_id: UUID,
    channel_id: UUID,
) -> ChannelTestResponse:
    """Decrypt a tenant LINE channel token and probe the LINE Bot Info API."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        channel = (
            await session.execute(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if channel is None:
            raise ChannelNotFoundError(f"Channel {channel_id} not found")
        creds = decrypt_credentials(channel.credentials_encrypted, fernet_key=settings.fernet_key)

    token = creds.get("channel_access_token", "").strip()
    if not token:
        return ChannelTestResponse(ok=False, error="Missing channel_access_token")
    return await tester.test_line_token(token)
