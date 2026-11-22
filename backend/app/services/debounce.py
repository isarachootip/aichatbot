"""Redis 2.5s burst debounce coordinator for rapid LINE customer text messages."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.messaging import Message

DEBOUNCE_WINDOW_SECONDS = 2.5
DEBOUNCE_KEY_TTL_SECONDS = 60


def _debounce_key(tenant_id: UUID, channel_id: UUID, external_user_id: str) -> str:
    return f"line:debounce:{tenant_id}:{channel_id}:{external_user_id}"


@runtime_checkable
class BurstDebouncer(Protocol):
    """Per-conversation burst tracker for coalescing rapid customer messages."""

    async def mark_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> None:
        """Record `event_id` as the newest pending text message in the burst window."""
        ...

    async def is_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> bool:
        """Return True if `event_id` is still the latest event (or no marker exists)."""
        ...


class RedisBurstDebouncer:
    """Production Redis-backed burst debouncer."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def mark_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> None:
        key = _debounce_key(tenant_id, channel_id, external_user_id)
        await self._redis.set(key, event_id, ex=DEBOUNCE_KEY_TTL_SECONDS)

    async def is_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> bool:
        key = _debounce_key(tenant_id, channel_id, external_user_id)
        current = await self._redis.get(key)
        if current is None:
            return True
        decoded = current.decode("utf-8") if isinstance(current, bytes) else str(current)
        return decoded == event_id


class InMemoryBurstDebouncer:
    """In-memory burst debouncer for deterministic unit and integration tests."""

    def __init__(self) -> None:
        self._latest: dict[str, str] = {}

    async def mark_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> None:
        key = _debounce_key(tenant_id, channel_id, external_user_id)
        self._latest[key] = event_id

    async def is_latest(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        external_user_id: str,
        event_id: str,
    ) -> bool:
        key = _debounce_key(tenant_id, channel_id, external_user_id)
        current = self._latest.get(key)
        return current is None or current == event_id


async def collect_unreplied_customer_text(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    fallback_text: str,
    max_burst: int = 10,
) -> str:
    """Combine trailing consecutive customer text messages awaiting a bot reply."""
    stmt = (
        select(Message.role, Message.content)
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        )
        .order_by(Message.created_at.desc())
        .limit(max_burst)
    )
    rows = (await session.execute(stmt)).all()
    burst: list[str] = []
    for role, content in rows:
        if role != "customer":
            break
        cleaned = content.strip()
        if cleaned and not cleaned.startswith("["):
            burst.append(cleaned)
    burst.reverse()
    return "\n".join(burst) if burst else fallback_text.strip()
