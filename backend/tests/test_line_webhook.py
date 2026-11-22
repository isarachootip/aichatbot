"""Integration tests for POST /webhooks/line/{channel_id} (signature, dedupe, RLS)."""

import base64
import hashlib
import hmac
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import encrypt_credentials, generate_fernet_key
from app.core.queue import InMemoryJobEnqueuer
from app.main import create_app
from app.models.messaging import Channel
from app.models.tenant import BotSetting, Tenant
from app.services.debounce import DEBOUNCE_WINDOW_SECONDS, InMemoryBurstDebouncer


def _sign(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


async def _seed_line_channel(
    admin_session_factory: async_sessionmaker[AsyncSession],
    *,
    fernet_key: str,
    webhook_secret: str = "line-secret-123",
    active: bool = True,
) -> tuple[UUID, UUID]:
    tenant_id, channel_id = uuid4(), uuid4()
    encrypted = encrypt_credentials(
        {"channel_access_token": "line-token-abc"},
        fernet_key=fernet_key,
    )
    async with admin_session_factory() as session, session.begin():
        session.add(Tenant(id=tenant_id, name="Shop LINE Webhook"))
        await session.flush()
        session.add(BotSetting(tenant_id=tenant_id, shop_name="Shop LINE Webhook"))
        session.add(
            Channel(
                id=channel_id,
                tenant_id=tenant_id,
                type="line",
                name="Primary LINE OA",
                credentials_encrypted=encrypted,
                webhook_secret=webhook_secret,
                active=active,
            )
        )
    return tenant_id, channel_id


@pytest.mark.usefixtures("clean_database")
async def test_line_webhook_valid_signature_dedupe_and_debounce_enqueue(
    test_settings: Settings,
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    secret = "wh-secret-ok"
    tenant_id, channel_id = await _seed_line_channel(
        admin_session_factory,
        fernet_key=fernet_key,
        webhook_secret=secret,
    )
    enqueuer = InMemoryJobEnqueuer()
    debouncer = InMemoryBurstDebouncer()
    app = create_app(
        test_settings.model_copy(update={"fernet_key": fernet_key}),
        enqueuer=enqueuer,
        debouncer=debouncer,
    )

    body = json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "webhookEventId": "evt-001",
                    "replyToken": "rt-001",
                    "timestamp": 1700000001000,
                    "source": {"type": "user", "userId": "U_cust_1"},
                    "message": {"id": "m-1", "type": "text", "text": "ค่าส่งกี่บาทคะ"},
                },
                {
                    "type": "message",
                    "webhookEventId": "evt-002",
                    "replyToken": "rt-002",
                    "timestamp": 1700000002000,
                    "source": {"type": "user", "userId": "U_cust_2"},
                    "message": {"id": "m-2", "type": "image"},
                },
            ]
        }
    ).encode("utf-8")
    sig = _sign(body, secret)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp1 = await client.post(
            f"/webhooks/line/{channel_id}",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp1.status_code == 200
        assert resp1.json() == {"status": "ok", "accepted": 2, "duplicates": 0}
        assert len(enqueuer.jobs) == 2

        # Text event is deferred by 2.5s for burst debounce; image event runs immediately
        assert enqueuer.jobs[0].function_name == "process_line_event_job"
        assert enqueuer.jobs[0].defer_by is not None
        assert enqueuer.jobs[0].defer_by.total_seconds() == DEBOUNCE_WINDOW_SECONDS
        assert enqueuer.jobs[1].defer_by is None
        assert await debouncer.is_latest(
            tenant_id=tenant_id,
            channel_id=channel_id,
            external_user_id="U_cust_1",
            event_id="evt-001",
        )

        # Replaying the exact same webhook must be idempotently deduped
        resp2 = await client.post(
            f"/webhooks/line/{channel_id}",
            content=body,
            headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp2.status_code == 200
        assert resp2.json() == {"status": "ok", "accepted": 0, "duplicates": 2}
        assert len(enqueuer.jobs) == 2


@pytest.mark.usefixtures("clean_database")
async def test_line_webhook_rejects_invalid_signature_and_inactive_channel(
    test_settings: Settings,
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    _, active_channel_id = await _seed_line_channel(
        admin_session_factory,
        fernet_key=fernet_key,
        webhook_secret="real-secret",
        active=True,
    )
    _, inactive_channel_id = await _seed_line_channel(
        admin_session_factory,
        fernet_key=fernet_key,
        webhook_secret="inactive-secret",
        active=False,
    )
    enqueuer = InMemoryJobEnqueuer()
    app = create_app(
        test_settings.model_copy(update={"fernet_key": fernet_key}),
        enqueuer=enqueuer,
        debouncer=InMemoryBurstDebouncer(),
    )
    body = b'{"events":[]}'

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        bad_sig = await client.post(
            f"/webhooks/line/{active_channel_id}",
            content=body,
            headers={"X-Line-Signature": "wrong-sig"},
        )
        assert bad_sig.status_code == 401

        inactive_resp = await client.post(
            f"/webhooks/line/{inactive_channel_id}",
            content=body,
            headers={"X-Line-Signature": _sign(body, "inactive-secret")},
        )
        assert inactive_resp.status_code == 404

        missing_resp = await client.post(
            f"/webhooks/line/{uuid4()}",
            content=body,
            headers={"X-Line-Signature": "anything"},
        )
        assert missing_resp.status_code == 404
        assert len(enqueuer.jobs) == 0
