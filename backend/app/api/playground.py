"""Authenticated RAG Playground endpoint (excluded from monthly billing quota)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.rag.embeddings import Embedder, create_embedder
from app.rag.generate import answer
from app.rag.llm import LLMClient, create_llm_client
from app.schemas.playground import (
    PlaygroundAskRequest,
    PlaygroundAskResponse,
    PlaygroundSourceResponse,
)

ADMIN_ROLES: tuple[UserRole, ...] = ("owner", "admin")


def create_playground_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    embedder: Embedder | None = None,
    llm_client: LLMClient | None = None,
) -> APIRouter:
    """Build tenant-isolated Playground simulator endpoint with lazy RAG clients."""
    router = APIRouter(prefix="/playground", tags=["playground"])
    admin_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ADMIN_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(admin_auth)]

    resolved_embedder: Embedder | None = embedder
    resolved_llm: LLMClient | None = llm_client

    def _get_clients() -> tuple[Embedder, LLMClient]:
        nonlocal resolved_embedder, resolved_llm
        if resolved_embedder is None:
            resolved_embedder = create_embedder(settings)
        if resolved_llm is None:
            resolved_llm = create_llm_client(settings)
        return resolved_embedder, resolved_llm

    get_clients: Callable[[], tuple[Embedder, LLMClient]] = _get_clients

    @router.post("/ask", response_model=PlaygroundAskResponse)
    async def playground_ask(
        body: PlaygroundAskRequest,
        auth: AuthDep,
    ) -> PlaygroundAskResponse:
        question = body.question.strip()
        if not question:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Question must not be blank",
            )

        emb, llm = get_clients()
        # Intentionally does NOT increment usage_monthly (Playground is free for shop testing).
        result = await answer(
            session_factory,
            emb,
            llm,
            settings,
            tenant_id=auth.tenant_id,
            question=question,
            conversation_id=None,
        )
        return PlaygroundAskResponse(
            answer=result.text,
            sources=[
                PlaygroundSourceResponse(
                    document_id=src.document_id,
                    filename=src.filename,
                    page=src.page,
                )
                for src in result.sources
            ],
            handoff=result.handoff,
            handoff_reason=result.handoff_reason,
            model=result.tokens.model,
            input_tokens=result.tokens.input_tokens,
            output_tokens=result.tokens.output_tokens,
        )

    return router
