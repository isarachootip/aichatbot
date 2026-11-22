"""Authenticated agent inbox endpoints for human replies and bot/human handoff control."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.factory import ChannelAdapterFactory
from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.conversations import (
    AgentMessageRequest,
    AgentMessageResponse,
    ConversationModeResponse,
    ConversationModeUpdateRequest,
)
from app.services.conversations import (
    ChannelUnavailableError,
    ConversationNotFoundError,
    send_agent_message,
    set_conversation_mode,
)

INBOX_ROLES: tuple[UserRole, ...] = ("owner", "admin", "agent")


def create_conversations_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    adapter_factory: ChannelAdapterFactory,
    settings: Settings,
) -> APIRouter:
    """Build tenant-isolated router for agent replies and return-to-bot controls."""
    router = APIRouter(prefix="/conversations", tags=["conversations"])
    inbox_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=INBOX_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(inbox_auth)]

    @router.post(
        "/{conversation_id}/messages",
        response_model=AgentMessageResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def post_agent_message(
        conversation_id: UUID,
        body: AgentMessageRequest,
        auth: AuthDep,
    ) -> AgentMessageResponse:
        try:
            result = await send_agent_message(
                session_factory,
                adapter_factory,
                tenant_id=auth.tenant_id,
                conversation_id=conversation_id,
                content=body.content,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            ) from exc
        except ChannelUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Messaging channel is inactive or unavailable",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        return AgentMessageResponse(
            id=result.id,
            conversation_id=result.conversation_id,
            content=result.content,
            mode=result.mode,
            last_agent_reply_at=result.last_agent_reply_at,
            created_at=result.created_at,
        )

    @router.post(
        "/{conversation_id}/return-to-bot",
        response_model=ConversationModeResponse,
    )
    async def return_conversation_to_bot(
        conversation_id: UUID,
        auth: AuthDep,
    ) -> ConversationModeResponse:
        try:
            result = await set_conversation_mode(
                session_factory,
                tenant_id=auth.tenant_id,
                conversation_id=conversation_id,
                mode="bot",
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            ) from exc

        return ConversationModeResponse(
            id=result.id,
            mode=result.mode,
            last_message_at=result.last_message_at,
            last_agent_reply_at=result.last_agent_reply_at,
        )

    @router.patch(
        "/{conversation_id}/mode",
        response_model=ConversationModeResponse,
    )
    async def update_conversation_mode(
        conversation_id: UUID,
        body: ConversationModeUpdateRequest,
        auth: AuthDep,
    ) -> ConversationModeResponse:
        try:
            result = await set_conversation_mode(
                session_factory,
                tenant_id=auth.tenant_id,
                conversation_id=conversation_id,
                mode=body.mode,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            ) from exc

        return ConversationModeResponse(
            id=result.id,
            mode=result.mode,
            last_message_at=result.last_message_at,
            last_agent_reply_at=result.last_agent_reply_at,
        )

    return router
