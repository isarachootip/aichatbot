"""Shared channel adapter resolution factory under PostgreSQL FORCE RLS."""

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter
from app.channels.line import LineChannelAdapter
from app.core.crypto import decrypt_credentials
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Channel


class ChannelAdapterFactory(Protocol):
    """Protocol resolving an outbound ChannelAdapter for a tenant channel."""

    async def get_adapter(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> ChannelAdapter | None: ...


class DatabaseChannelAdapterFactory:
    """Loads active channel credentials from PostgreSQL under RLS and decrypts them."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        fernet_key: str,
    ) -> None:
        self._session_factory = session_factory
        self._fernet_key = fernet_key

    async def get_adapter(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> ChannelAdapter | None:
        return await resolve_channel_adapter(
            self._session_factory,
            tenant_id=tenant_id,
            channel_id=channel_id,
            fernet_key=self._fernet_key,
        )


async def resolve_channel_adapter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    channel_id: UUID,
    fernet_key: str,
) -> ChannelAdapter | None:
    """Load an active channel under RLS and return its ChannelAdapter instance."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        channel = (
            await session.execute(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                    Channel.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if channel is None:
            return None
        channel_type = channel.type
        creds = decrypt_credentials(channel.credentials_encrypted, fernet_key=fernet_key)

    if channel_type == "line":
        token = creds.get("channel_access_token", "").strip()
        if not token:
            raise ValueError(f"Channel {channel_id} credentials missing channel_access_token")
        return LineChannelAdapter(channel_access_token=token)

    raise ValueError(f"Unsupported channel type for outbound delivery: {channel_type}")
