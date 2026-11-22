"""Health check response schema."""

from typing import Literal

from pydantic import BaseModel

DependencyStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    """Status payload returned by GET /health."""

    status: Literal["ok", "degraded"]
    database: DependencyStatus
    redis: DependencyStatus
    version: str
