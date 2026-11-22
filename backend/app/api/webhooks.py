"""Fast-200 idempotent LINE Messaging API webhook router with RLS tenant resolution."""

import json
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import InboundEvent
from app.channels.line import parse_line_events, verify_line_signature
from app.core.logging import get_logger
from app.core.queue import JobEnqueuer
from app.core.tenant_context import resolve_channel_tenant, tenant_scoped_session
from app.models.messaging import Channel
from app.models.operations import WebhookEvent
from app.services.debounce import DEBOUNCE_WINDOW_SECONDS, BurstDebouncer

logger = get_logger("app.api.webhooks")
LINE_INBOUND_JOB_NAME = "process_line_event_job"


async def _dedupe_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    channel_id: UUID,
    events: list[InboundEvent],
) -> tuple[list[InboundEvent], int]:
    """Insert webhook_events rows atomically; return only never-seen-before events."""
    accepted: list[InboundEvent] = []
    duplicates = 0
    for event in events:
        stmt = (
            pg_insert(WebhookEvent)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                channel_id=channel_id,
                external_event_id=event.event_id,
            )
            .on_conflict_do_nothing(
                index_elements=["channel_id", "external_event_id"],
            )
            .returning(WebhookEvent.id)
        )
        inserted_id = (await session.execute(stmt)).scalar_one_or_none()
        if inserted_id is None:
            duplicates += 1
        else:
            accepted.append(event)
    return accepted, duplicates


def create_webhooks_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    enqueuer: JobEnqueuer,
    debouncer: BurstDebouncer,
) -> APIRouter:
    """Build webhook endpoints for external messaging platforms."""
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])

    @router.post("/line/{channel_id}")
    async def line_webhook(
        channel_id: UUID,
        request: Request,
        x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
    ) -> dict[str, object]:
        # Step 1: Resolve owning tenant via SECURITY DEFINER before setting app.tenant_id
        async with session_factory() as lookup_session, lookup_session.begin():
            tenant_id = await resolve_channel_tenant(lookup_session, channel_id)
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active LINE channel not found",
            )

        raw_body = await request.body()

        # Step 2: Inside RLS-scoped transaction, verify HMAC-SHA256 signature & dedupe events
        async with tenant_scoped_session(session_factory, tenant_id) as session:
            channel = (
                await session.execute(
                    select(Channel).where(
                        Channel.id == channel_id,
                        Channel.tenant_id == tenant_id,
                        Channel.type == "line",
                        Channel.active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if channel is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Active LINE channel not found",
                )

            if not verify_line_signature(raw_body, x_line_signature or "", channel.webhook_secret):
                logger.warning(
                    "line_webhook_invalid_signature",
                    tenant_id=str(tenant_id),
                    channel_id=str(channel_id),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid X-Line-Signature",
                )

            try:
                payload_obj = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid JSON payload",
                ) from exc

            if not isinstance(payload_obj, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Webhook payload must be a JSON object",
                )

            events = parse_line_events(payload_obj)
            accepted, duplicates = await _dedupe_events(
                session,
                tenant_id=tenant_id,
                channel_id=channel_id,
                events=events,
            )

        # Step 3: Enqueue ARQ background jobs (2.5s debounce for text bursts) & return 200 fast
        for event in accepted:
            defer_by: timedelta | None = None
            if event.message_type == "text":
                await debouncer.mark_latest(
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    external_user_id=event.external_user_id,
                    event_id=event.event_id,
                )
                defer_by = timedelta(seconds=DEBOUNCE_WINDOW_SECONDS)

            await enqueuer.enqueue(
                LINE_INBOUND_JOB_NAME,
                str(tenant_id),
                str(channel_id),
                asdict(event),
                defer_by=defer_by,
            )

        logger.info(
            "line_webhook_received",
            tenant_id=str(tenant_id),
            channel_id=str(channel_id),
            accepted=len(accepted),
            duplicates=duplicates,
        )
        return {"status": "ok", "accepted": len(accepted), "duplicates": duplicates}

    return router
