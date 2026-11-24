"""Pydantic v2 schemas for the non-billed RAG Playground."""

from uuid import UUID

from pydantic import BaseModel, Field


class PlaygroundAskRequest(BaseModel):
    """Question submitted from the dashboard Playground simulator."""

    question: str = Field(min_length=1, max_length=2000)


class PlaygroundSourceResponse(BaseModel):
    """Citation reference returned alongside a Playground answer."""

    document_id: UUID
    filename: str
    page: int


class PlaygroundAskResponse(BaseModel):
    """Grounded RAG response from the Playground (not counted toward monthly quota)."""

    answer: str
    sources: list[PlaygroundSourceResponse]
    handoff: bool
    handoff_reason: str | None
    model: str
    input_tokens: int
    output_tokens: int
