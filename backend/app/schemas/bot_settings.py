"""Pydantic v2 schemas for tenant bot persona, handoff, and auto-return settings."""

from uuid import UUID

from pydantic import BaseModel, Field


class BotSettingsResponse(BaseModel):
    """Current per-tenant bot configuration plus auto-return timeout."""

    shop_name: str
    tone: str
    greeting: str
    handoff_keywords: list[str]
    extra_instructions: str
    fallback_message: str
    show_citations_to_customer: bool
    handoff_notify_channel_id: UUID | None
    handoff_notify_target_id: str | None
    auto_return_hours: int


class UpdateBotSettingsRequest(BaseModel):
    """Validated update payload for bot persona, handoff alerts, and auto-return hours."""

    shop_name: str = Field(min_length=1, max_length=255)
    tone: str = Field(min_length=1, max_length=64)
    greeting: str = Field(min_length=1, max_length=2000)
    handoff_keywords: list[str] = Field(default_factory=list, max_length=50)
    extra_instructions: str = Field(default="", max_length=4000)
    fallback_message: str = Field(min_length=1, max_length=2000)
    show_citations_to_customer: bool = False
    handoff_notify_channel_id: UUID | None = None
    handoff_notify_target_id: str | None = Field(default=None, max_length=255)
    auto_return_hours: int = Field(default=24, ge=0, le=720)
