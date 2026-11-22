"""Domain service for agent outbound replies and conversation mode transitions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.factory import ChannelAdapterFactory
from app.core.logging import get_logger
from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Conversation, Message

logger = get_logger("app.services.conversations")

ConversationMode = Literal["bot", "human"]


class ConversationNotFoundError(LookupError):
    """Raised when a conversation does not exist within the caller's tenant."""


class ChannelUnavailableError(RuntimeError):
    """Raised when the conversation's messaging channel is inactive or missing."""


@dataclass(frozen=True)
class AgentMessageResult:
    """Result returned after an agent message is delivered and persisted."""

    id: UUID
    conversation_id: UUID
    content: str
    mode: ConversationMode
    last_agent_reply_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ConversationModeResult:
    """Result returned after updating a conversation's bot/human mode."""

    id: UUID
    mode: ConversationMode
    last_message_at: datetime
    last_agent_reply_at: datetime | None


async def send_agent_message(
    session_factory: async_sessionmaker[AsyncSession],
    adapter_factory: ChannelAdapterFactory,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    content: str,
    now: datetime | None = None,
) -> AgentMessageResult:
    """Send a human agent reply through the channel adapter and persist it under RLS."""
    cleaned = content.strip()
    if not cleaned:
        raise ValueError("Agent message content must not be blank")

    # 1. Resolve conversation metadata under FORCE RLS before calling external channel API
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        channel_id = conv.channel_id
        external_user_id = conv.external_user_id

    # 2. Deliver outbound push without holding a DB transaction open
    adapter = await adapter_factory.get_adapter(tenant_id=tenant_id, channel_id=channel_id)
    if adapter is None:
        raise ChannelUnavailableError(f"Active channel {channel_id} not available")
    await adapter.send_push(external_user_id, cleaned)

    # 3. Persist agent message and mark active human reply timestamp
    ts = now or datetime.now(UTC)
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv_row = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        conv_row.mode = "human"
        conv_row.last_agent_reply_at = ts
        conv_row.last_message_at = ts

        msg = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role="agent",
            content=cleaned,
        )
        session.add(msg)
        await session.flush()
        msg_id = msg.id
        created_at = msg.created_at or ts

    logger.info(
        "agent_message_sent",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        message_id=str(msg_id),
    )
    return AgentMessageResult(
        id=msg_id,
        conversation_id=conversation_id,
        content=cleaned,
        mode="human",
        last_agent_reply_at=ts,
        created_at=created_at,
    )


async def set_conversation_mode(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    mode: ConversationMode,
) -> ConversationModeResult:
    """Switch a tenant conversation between 'bot' and 'human' mode under FORCE RLS."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        conv.mode = mode
        last_message_at = conv.last_message_at
        last_agent_reply_at = conv.last_agent_reply_at

    logger.info(
        "conversation_mode_updated",
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        mode=mode,
    )
    return ConversationModeResult(
        id=conversation_id,
        mode=mode,
        last_message_at=last_message_at,
        last_agent_reply_at=last_agent_reply_at,
    )
