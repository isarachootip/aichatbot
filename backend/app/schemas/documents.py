"""Pydantic v2 schemas for knowledge-base document management."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentResponse(BaseModel):
    """Metadata and ingestion status of one tenant knowledge document."""

    id: UUID
    filename: str
    mime: str
    status: DocumentStatus
    error: str | None
    chunk_count: int
    uploaded_at: datetime


class DocumentListResponse(BaseModel):
    """Collection wrapper for tenant documents."""

    items: list[DocumentResponse]
