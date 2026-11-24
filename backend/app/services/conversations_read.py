"""Read-side domain service for listing inbox conversations and message history."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Channel, Conversation, Message
from app.schemas.conversations import (
    ConversationMessagesResponse,
    ConversationMode,
    ConversationSummaryResponse,
    MessageItemResponse,
    MessageRole,
)
from app.services.conversations import ConversationNotFoundError


async def list_conversations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    mode: ConversationMode | None = None,
    limit: int = 50,
) -> list[ConversationSummaryResponse]:
    """List tenant conversations ordered by most recent message with latest text preview."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        latest_msg_subq = (
            select(
                Message.conversation_id.label("conv_id"),
                Message.content.label("content"),
                func.row_number()
                .over(
                    partition_by=Message.conversation_id,
                    order_by=Message.created_at.desc(),
                )
                .label("rn"),
            )
            .where(Message.tenant_id == tenant_id)
            .subquery()
        )
        stmt = (
            select(
                Conversation,
                Channel.name,
                Channel.type,
                latest_msg_subq.c.content,
            )
            .join(Channel, Channel.id == Conversation.channel_id)
            .outerjoin(
                latest_msg_subq,
                (latest_msg_subq.c.conv_id == Conversation.id) & (latest_msg_subq.c.rn == 1),
            )
            .where(Conversation.tenant_id == tenant_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
        if mode is not None:
            stmt = stmt.where(Conversation.mode == mode)

        rows = (await session.execute(stmt)).all()

    items: list[ConversationSummaryResponse] = []
    for conv, ch_name, ch_type, preview in rows:
        mode_val: ConversationMode = conv.mode
        items.append(
            ConversationSummaryResponse(
                id=conv.id,
                channel_id=conv.channel_id,
                channel_name=str(ch_name),
                channel_type=str(ch_type),
                external_user_id=conv.external_user_id,
                customer_name=conv.customer_name,
                mode=mode_val,
                last_message_preview=str(preview)[:120] if isinstance(preview, str) else None,
                last_message_at=conv.last_message_at,
                last_agent_reply_at=conv.last_agent_reply_at,
            )
        )
    return items


async def get_conversation_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = 100,
) -> ConversationMessagesResponse:
    """Return ordered message history for a single tenant conversation under RLS."""
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

        msgs = (
            await session.execute(
                select(Message)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation_id,
                )
                .order_by(Message.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        mode_val: ConversationMode = conv.mode  # type: ignore[assignment]
        items: list[MessageItemResponse] = []
        for m in msgs:
            role_val: MessageRole = m.role  # type: ignore[assignment]
            items.append(
                MessageItemResponse(
                    id=m.id,
                    role=role_val,
                    content=m.content,
                    sources=list(m.sources or []),
                    created_at=m.created_at,
                )
            )

        return ConversationMessagesResponse(
            conversation_id=conv.id,
            customer_name=conv.customer_name,
            external_user_id=conv.external_user_id,
            mode=mode_val,
            items=items,
        )
