"""Authenticated knowledge-base document endpoints (upload, list, delete, re-upload)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.queue import JobEnqueuer
from app.core.security import AuthContext, UserRole, require_roles
from app.core.storage import ObjectStorage
from app.schemas.documents import DocumentListResponse, DocumentResponse
from app.services.documents import (
    DocumentLimitExceededError,
    DocumentNotFoundError,
    InvalidDocumentError,
    delete_document,
    list_documents,
    reupload_document,
    upload_document,
)

ADMIN_ROLES: tuple[UserRole, ...] = ("owner", "admin")


def create_documents_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    enqueuer: JobEnqueuer,
    settings: Settings,
) -> APIRouter:
    """Build tenant-isolated router for managing knowledge-base documents."""
    router = APIRouter(prefix="/documents", tags=["documents"])
    admin_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ADMIN_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(admin_auth)]

    @router.get("", response_model=DocumentListResponse)
    async def get_documents(auth: AuthDep) -> DocumentListResponse:
        items = await list_documents(session_factory, tenant_id=auth.tenant_id)
        return DocumentListResponse(items=items)

    @router.post(
        "",
        response_model=DocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_document(
        auth: AuthDep,
        file: Annotated[UploadFile, File(...)],
    ) -> DocumentResponse:
        data = await file.read()
        try:
            return await upload_document(
                session_factory,
                storage,
                enqueuer,
                tenant_id=auth.tenant_id,
                filename=file.filename or "upload.txt",
                mime=file.content_type or "application/octet-stream",
                data=data,
            )
        except DocumentLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except InvalidDocumentError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @router.post("/{document_id}/reupload", response_model=DocumentResponse)
    async def replace_document(
        document_id: UUID,
        auth: AuthDep,
        file: Annotated[UploadFile, File(...)],
    ) -> DocumentResponse:
        data = await file.read()
        try:
            return await reupload_document(
                session_factory,
                storage,
                enqueuer,
                tenant_id=auth.tenant_id,
                document_id=document_id,
                filename=file.filename or "upload.txt",
                mime=file.content_type or "application/octet-stream",
                data=data,
            )
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidDocumentError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_document(document_id: UUID, auth: AuthDep) -> Response:
        try:
            await delete_document(
                session_factory,
                storage,
                tenant_id=auth.tenant_id,
                document_id=document_id,
            )
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
