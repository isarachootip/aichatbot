"""Phase 5 API tests: signup, dev-login, /me, documents, channels, and cross-tenant denial."""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import generate_fernet_key
from app.core.queue import InMemoryJobEnqueuer
from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.main import create_app
from app.models.knowledge import Chunk
from app.rag.embeddings import MockEmbedder
from app.schemas.channels import ChannelTestResponse
from app.workers.ingest import ingest_document


class _FakeChannelTester:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.seen_tokens: list[str] = []

    async def test_line_token(self, access_token: str) -> ChannelTestResponse:
        self.seen_tokens.append(access_token)
        if self.ok:
            return ChannelTestResponse(ok=True, bot_name="SiamShop Bot", basic_id="@siamshop")
        return ChannelTestResponse(ok=False, error="Invalid token")


@pytest.mark.usefixtures("clean_database")
async def test_signup_dev_login_me_and_documents_lifecycle_with_rls(
    test_settings: Settings,
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cfg = test_settings.model_copy(
        update={
            "fernet_key": generate_fernet_key(),
            "public_api_base_url": "https://api.example.com",
        }
    )
    storage = InMemoryStorage()
    enqueuer = InMemoryJobEnqueuer()
    app = create_app(cfg, storage=storage, enqueuer=enqueuer)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        # 1. Signup Shop A & Shop B (7-day free trial)
        r_a = await client.post(
            "/signup", json={"shop_name": "ร้านสยาม", "email": "owner-a@siam.th"}
        )
        assert r_a.status_code == 201
        data_a = r_a.json()
        token_a = data_a["access_token"]
        tenant_a = UUID(data_a["tenant_id"])
        assert token_a
        assert data_a["role"] == "owner"

        # Duplicate email rejected
        r_dup = await client.post(
            "/signup", json={"shop_name": "ซ้ำ", "email": "owner-a@siam.th"}
        )
        assert r_dup.status_code == 409

        # Dev login works for registered email
        r_login = await client.post("/auth/dev-login", json={"email": "owner-a@siam.th"})
        assert r_login.status_code == 200
        assert r_login.json()["tenant_id"] == str(tenant_a)

        r_b = await client.post(
            "/signup", json={"shop_name": "ร้านบี", "email": "owner-b@shop.th"}
        )
        assert r_b.status_code == 201
        token_b = r_b.json()["access_token"]

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 2. /me returns trial countdown & limits
        r_me = await client.get("/me", headers=headers_a)
        assert r_me.status_code == 200
        me = r_me.json()
        assert me["shop_name"] == "ร้านสยาม"
        assert me["trial_days_remaining"] == 7
        assert me["limit_messages"] == 200

        # 3. Upload document (unsupported extension rejected, .txt accepted & enqueued)
        r_bad = await client.post(
            "/documents",
            files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
            headers=headers_a,
        )
        assert r_bad.status_code == 422

        r_up = await client.post(
            "/documents",
            files={"file": ("policy.txt", "ส่งฟรีเมื่อซื้อครบ 500 บาท".encode(), "text/plain")},
            headers=headers_a,
        )
        assert r_up.status_code == 201
        doc_id = UUID(r_up.json()["id"])
        assert r_up.json()["status"] == "pending"
        assert len(enqueuer.jobs) == 1
        assert enqueuer.jobs[0].function_name == "ingest_document_job"

        # Run ingestion worker directly and confirm list shows ready + chunk_count >= 1
        ingest_res = await ingest_document(
            app_session_factory, storage, MockEmbedder(), tenant_id=tenant_a, document_id=doc_id
        )
        assert ingest_res.status == "ready"

        r_list_a = await client.get("/documents", headers=headers_a)
        assert r_list_a.status_code == 200
        assert r_list_a.json()["items"][0]["status"] == "ready"
        assert r_list_a.json()["items"][0]["chunk_count"] >= 1

        # Tenant B cannot see, reupload, or delete Tenant A's document
        r_list_b = await client.get("/documents", headers=headers_b)
        assert r_list_b.json()["items"] == []
        assert (await client.delete(f"/documents/{doc_id}", headers=headers_b)).status_code == 404

        # Re-upload resets status to pending and enqueues again
        r_re = await client.post(
            f"/documents/{doc_id}/reupload",
            files={"file": ("policy_v2.txt", "ค่าส่ง 30 บาททั่วไทย".encode(), "text/plain")},
            headers=headers_a,
        )
        assert r_re.status_code == 200
        assert r_re.json()["status"] == "pending"
        assert len(enqueuer.jobs) == 2

        # Delete removes document & cascades chunks
        r_del = await client.delete(f"/documents/{doc_id}", headers=headers_a)
        assert r_del.status_code == 204
        async with tenant_scoped_session(app_session_factory, tenant_a) as session:
            chunks_left = (await session.execute(select(Chunk))).scalars().all()
            assert chunks_left == []


@pytest.mark.usefixtures("clean_database")
async def test_channels_create_webhook_url_test_limit_and_cross_tenant_denial(
    test_settings: Settings,
) -> None:
    cfg = test_settings.model_copy(
        update={
            "fernet_key": generate_fernet_key(),
            "public_api_base_url": "https://api.thai-shop.th",
        }
    )
    tester = _FakeChannelTester(ok=True)
    app = create_app(cfg, channel_tester=tester)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        t_a = (
            await client.post("/signup", json={"shop_name": "Shop A", "email": "ch-a@shop.th"})
        ).json()["access_token"]
        t_b = (
            await client.post("/signup", json={"shop_name": "Shop B", "email": "ch-b@shop.th"})
        ).json()["access_token"]
        h_a = {"Authorization": f"Bearer {t_a}"}
        h_b = {"Authorization": f"Bearer {t_b}"}

        r_ch = await client.post(
            "/channels",
            json={
                "name": "LINE Official Main",
                "channel_access_token": "line-live-access-token-12345",
                "webhook_secret": "line-secret-999",
            },
            headers=h_a,
        )
        assert r_ch.status_code == 201
        ch_data = r_ch.json()
        ch_id = ch_data["id"]
        assert ch_data["webhook_url"] == f"https://api.thai-shop.th/webhooks/line/{ch_id}"
        assert "line-live-access-token-12345" not in str(ch_data)

        # Trial plan max_channels = 1 -> second channel returns 403
        r_ch2 = await client.post(
            "/channels",
            json={
                "name": "LINE Second",
                "channel_access_token": "line-token-second-99999",
                "webhook_secret": "secret-2",
            },
            headers=h_a,
        )
        assert r_ch2.status_code == 403

        # Connection test decrypts token and calls tester
        r_test = await client.post(f"/channels/{ch_id}/test", headers=h_a)
        assert r_test.status_code == 200
        assert r_test.json()["ok"] is True
        assert r_test.json()["bot_name"] == "SiamShop Bot"
        assert tester.seen_tokens == ["line-live-access-token-12345"]

        # Tenant B cannot test or delete Tenant A's channel
        assert (await client.post(f"/channels/{ch_id}/test", headers=h_b)).status_code == 404
        assert (await client.delete(f"/channels/{ch_id}", headers=h_b)).status_code == 404
