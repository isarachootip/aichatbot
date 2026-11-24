"""Phase 5 API tests: playground, bot settings, inbox read, analytics, team, and RBAC."""

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import encrypt_credentials, generate_fernet_key
from app.core.queue import InMemoryJobEnqueuer
from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.main import create_app
from app.models.messaging import Channel, Conversation, Message, UnansweredQuestion
from app.models.operations import Notification
from app.models.tenant import UsageMonthly
from app.rag.embeddings import MockEmbedder
from app.rag.types import StructuredLLMResponse
from app.workers.ingest import ingest_document


class _PlaygroundStubLLM:
    async def generate_grounded_reply(
        self,
        *,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        model: str,
        max_tokens: int = 600,
    ) -> StructuredLLMResponse:
        del system_prompt, messages, max_tokens
        return StructuredLLMResponse(
            answer_text="ส่งฟรีเมื่อซื้อครบ 500 บาทค่ะ",
            handoff=False,
            handoff_reason=None,
            cited_chunk_indices=[1],
            input_tokens=95,
            output_tokens=22,
            model=model,
        )


@pytest.mark.usefixtures("clean_database")
async def test_playground_not_billed_bot_settings_inbox_and_analytics(
    test_settings: Settings,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    cfg = test_settings.model_copy(update={"fernet_key": fernet_key})
    storage = InMemoryStorage()
    enqueuer = InMemoryJobEnqueuer()
    app = create_app(
        cfg,
        storage=storage,
        enqueuer=enqueuer,
        embedder=MockEmbedder(),
        llm_client=_PlaygroundStubLLM(),
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        signup = (
            await client.post("/signup", json={"shop_name": "ร้านมณี", "email": "manee@shop.th"})
        ).json()
        tenant_id = UUID(signup["tenant_id"])
        headers = {"Authorization": f"Bearer {signup['access_token']}"}

        # 1. Update bot settings + auto_return_hours
        r_set = await client.put(
            "/settings/bot",
            json={
                "shop_name": "ร้านมณี พลัส",
                "tone": "สุภาพ (ครับ)",
                "greeting": "สวัสดีครับ ยินดีต้อนรับ",
                "handoff_keywords": ["แอดมิน", "ด่วนมาก"],
                "extra_instructions": "ตอบสั้นกระชับ",
                "fallback_message": "ขอส่งต่อให้แอดมินนะครับ",
                "show_citations_to_customer": True,
                "handoff_notify_target_id": "C_group_manee",
                "auto_return_hours": 12,
            },
            headers=headers,
        )
        assert r_set.status_code == 200
        assert r_set.json()["auto_return_hours"] == 12
        assert r_set.json()["handoff_notify_target_id"] == "C_group_manee"

        # 2. Upload + ingest doc -> test Playground ask (must NOT increment usage_monthly)
        up = await client.post(
            "/documents",
            files={"file": ("faq.txt", "ส่งฟรีเมื่อซื้อครบ 500 บาท".encode(), "text/plain")},
            headers=headers,
        )
        doc_id = UUID(up.json()["id"])
        await ingest_document(
            app_session_factory, storage, MockEmbedder(), tenant_id=tenant_id, document_id=doc_id
        )

        r_play = await client.post(
            "/playground/ask",
            json={"question": "ซื้อครบกี่บาทส่งฟรี"},
            headers=headers,
        )
        assert r_play.status_code == 200
        play = r_play.json()
        assert "500 บาท" in play["answer"]
        assert play["handoff"] is False
        assert len(play["sources"]) == 1
        assert play["sources"][0]["filename"] == "faq.txt"

        async with tenant_scoped_session(app_session_factory, tenant_id) as session:
            usage_rows = (await session.execute(select(UsageMonthly))).scalars().all()
            assert usage_rows == []

        # 3. Seed conversation, messages, unanswered question & notif -> check inbox + analytics
        ch_id, conv_id, notif_id = uuid4(), uuid4(), uuid4()
        enc = encrypt_credentials({"channel_access_token": "tok"}, fernet_key=fernet_key)
        async with admin_session_factory() as session, session.begin():
            session.add(
                Channel(
                    id=ch_id, tenant_id=tenant_id, type="line", name="LINE",
                    credentials_encrypted=enc, webhook_secret="s", active=True,
                )
            )
            await session.flush()
            session.add(
                Conversation(
                    id=conv_id, tenant_id=tenant_id, channel_id=ch_id,
                    external_user_id="U_cust_1", customer_name="คุณแป้ง", mode="human",
                )
            )
            await session.flush()
            session.add(
                Message(
                    tenant_id=tenant_id, conversation_id=conv_id,
                    role="customer", content="ผ่อนได้ไหม",
                )
            )
            session.add(
                Message(
                    tenant_id=tenant_id, conversation_id=conv_id,
                    role="bot", content="ขอส่งต่อแอดมิน",
                )
            )
            session.add(
                Message(
                    tenant_id=tenant_id, conversation_id=conv_id,
                    role="bot", content="ค่าส่ง 40 บาท",
                )
            )
            session.add(
                UnansweredQuestion(
                    tenant_id=tenant_id, conversation_id=conv_id, question="ผ่อนได้ไหม"
                )
            )
            session.add(
                Notification(
                    id=notif_id, tenant_id=tenant_id, type="handoff",
                    title="ส่งต่อแอดมิน", body="ผ่อนได้ไหม", payload={},
                )
            )

        r_convs = await client.get("/conversations?mode=human", headers=headers)
        assert r_convs.status_code == 200
        assert len(r_convs.json()["items"]) == 1
        assert r_convs.json()["items"][0]["customer_name"] == "คุณแป้ง"

        r_msgs = await client.get(f"/conversations/{conv_id}/messages", headers=headers)
        assert r_msgs.status_code == 200
        assert len(r_msgs.json()["items"]) == 3

        r_notifs = await client.get("/notifications", headers=headers)
        assert len(r_notifs.json()["items"]) == 1
        r_read = await client.post(f"/notifications/{notif_id}/read", headers=headers)
        assert r_read.json()["read_at"] is not None

        r_ana = await client.get("/analytics/summary?days=7", headers=headers)
        assert r_ana.status_code == 200
        ana = r_ana.json()
        assert ana["total_conversations"] == 1
        assert ana["total_bot_messages"] == 2
        assert ana["total_handoffs"] == 1
        assert ana["handoff_rate"] == 50.0
        assert ana["auto_resolved_rate"] == 50.0
        assert ana["top_unanswered_questions"][0]["question"] == "ผ่อนได้ไหม"


@pytest.mark.usefixtures("clean_database")
async def test_team_management_and_strict_rbac_matrix(
    test_settings: Settings,
) -> None:
    cfg = test_settings.model_copy(update={"fernet_key": generate_fernet_key()})
    app = create_app(cfg, storage=InMemoryStorage(), enqueuer=InMemoryJobEnqueuer())

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        owner_data = (
            await client.post("/signup", json={"shop_name": "RBAC Shop", "email": "own@rbac.th"})
        ).json()
        owner_id = owner_data["user_id"]
        h_owner = {"Authorization": f"Bearer {owner_data['access_token']}"}

        # Owner invites admin and agent
        r_inv_adm = await client.post(
            "/team/invite", json={"email": "adm@rbac.th", "role": "admin"}, headers=h_owner
        )
        assert r_inv_adm.status_code == 201
        adm_id = r_inv_adm.json()["id"]

        r_inv_ag = await client.post(
            "/team/invite", json={"email": "ag@rbac.th", "role": "agent"}, headers=h_owner
        )
        assert r_inv_ag.status_code == 201
        ag_id = r_inv_ag.json()["id"]

        # Login as admin and agent via dev-login
        t_adm = (await client.post("/auth/dev-login", json={"email": "adm@rbac.th"})).json()[
            "access_token"
        ]
        t_ag = (await client.post("/auth/dev-login", json={"email": "ag@rbac.th"})).json()[
            "access_token"
        ]
        h_adm = {"Authorization": f"Bearer {t_adm}"}
        h_ag = {"Authorization": f"Bearer {t_ag}"}

        # Agent: allowed on /me & /conversations, blocked (403) on /documents, /analytics, /team
        assert (await client.get("/me", headers=h_ag)).status_code == 200
        assert (await client.get("/conversations", headers=h_ag)).status_code == 200
        assert (await client.get("/documents", headers=h_ag)).status_code == 403
        assert (await client.get("/analytics/summary", headers=h_ag)).status_code == 403
        assert (await client.get("/team/users", headers=h_ag)).status_code == 403

        # Admin: allowed on /documents & /analytics, blocked (403) on /team
        assert (await client.get("/documents", headers=h_adm)).status_code == 200
        assert (await client.get("/analytics/summary", headers=h_adm)).status_code == 200
        assert (await client.get("/team/users", headers=h_adm)).status_code == 403

        # Owner: cannot demote or delete last owner (409), can update & remove agent
        r_demote_self = await client.patch(
            f"/team/users/{owner_id}/role", json={"role": "admin"}, headers=h_owner
        )
        assert r_demote_self.status_code == 409

        r_promote = await client.patch(
            f"/team/users/{ag_id}/role", json={"role": "admin"}, headers=h_owner
        )
        assert r_promote.status_code == 200
        assert r_promote.json()["role"] == "admin"

        assert (await client.delete(f"/team/users/{adm_id}", headers=h_owner)).status_code == 204
