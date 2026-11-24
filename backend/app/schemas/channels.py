"""Pydantic v2 schemas for LINE OA channel management and connection testing."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ChannelType = Literal["line", "facebook", "instagram", "web"]


class CreateLineChannelRequest(BaseModel):
    """Payload to connect a new LINE Messaging API channel."""

    name: str = Field(min_length=1, max_length=255)
    channel_access_token: str = Field(min_length=10, max_length=2000)
    webhook_secret: str = Field(min_length=6, max_length=255)


class ChannelResponse(BaseModel):
    """Sanitized channel record returned to the dashboard (secrets never exposed)."""

    id: UUID
    type: ChannelType
    name: str
    active: bool
    webhook_url: str
    created_at: datetime


class ChannelListResponse(BaseModel):
    """Collection wrapper for tenant messaging channels."""

    items: list[ChannelResponse]


class ChannelTestResponse(BaseModel):
    """Result of probing the LINE Bot Info API with decrypted channel credentials."""

    ok: bool
    bot_name: str | None = None
    basic_id: str | None = None
    error: str | None = None
