"""Pydantic v2 schemas for conversation inbox, agent replies, and mode control."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ConversationMode = Literal["bot", "human"]
MessageRole = Literal["customer", "bot", "agent"]


class AgentMessageRequest(BaseModel):
    """Outbound text reply sent by a human agent from the dashboard."""

    content: str = Field(min_length=1, max_length=5000)


class AgentMessageResponse(BaseModel):
    """Persisted agent reply metadata returned after channel delivery."""

    id: UUID
    conversation_id: UUID
    role: Literal["agent"] = "agent"
    content: str
    mode: ConversationMode
    last_agent_reply_at: datetime
    created_at: datetime


class ConversationModeUpdateRequest(BaseModel):
    """Explicit bot/human mode toggle payload."""

    mode: ConversationMode


class ConversationModeResponse(BaseModel):
    """Current conversation mode state after a toggle or return-to-bot call."""

    id: UUID
    mode: ConversationMode
    last_message_at: datetime
    last_agent_reply_at: datetime | None


class ConversationSummaryResponse(BaseModel):
    """Inbox list row summarizing a single customer chat thread."""

    id: UUID
    channel_id: UUID
    channel_name: str
    channel_type: str
    external_user_id: str
    customer_name: str | None
    mode: ConversationMode
    last_message_preview: str | None
    last_message_at: datetime
    last_agent_reply_at: datetime | None


class ConversationListResponse(BaseModel):
    """Collection wrapper for tenant inbox conversations."""

    items: list[ConversationSummaryResponse]


class MessageItemResponse(BaseModel):
    """Single message inside a conversation thread."""

    id: UUID
    role: MessageRole
    content: str
    sources: list[dict[str, object]]
    created_at: datetime


class ConversationMessagesResponse(BaseModel):
    """Thread metadata plus ordered message stream."""

    conversation_id: UUID
    customer_name: str | None
    external_user_id: str
    mode: ConversationMode
    items: list[MessageItemResponse]
