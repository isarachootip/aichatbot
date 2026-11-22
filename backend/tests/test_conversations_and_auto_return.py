"""Tests for agent reply API, return-to-bot endpoint, cross-tenant RBAC, and auto-return cron."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent, UserProfile
from app.core.config import Settings
from app.core.crypto import encrypt_credentials, generate_fernet_key
from app.core.security import create_dev_access_token
from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.main import create_app
from app.models.knowledge import Document
from app.models.messaging import Channel, Conversation, Message
from app.models.tenant import BotSetting, Tenant, User
from app.rag.embeddings import MockEmbedder
from app.rag.types import StructuredLLMResponse
from app.services.debounce import InMemoryBurstDebouncer
from app.workers.auto_return import auto_return_inactive_conversations
from app.workers.ingest import ingest_document
from app.workers.line_inbound import handle_line_event


class _FakeOutboundAdapter:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, str]] = []
        self.replies: list[tuple[str, str]] = []

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        del body, signature, secret
        return True

    def parse_events(self, payload: dict[str, object]) -> list[InboundEvent]:
        del payload
        return []

    async def send_reply(self, reply_token: str, text: str) -> None:
        self.replies.append((reply_token, text))

    async def send_push(self, external_user_id: str, text: str) -> None:
        self.pushes.append((external_user_id, text))

    async def get_profile(self, external_user_id: str) -> UserProfile:
        return UserProfile(external_user_id=external_user_id, display_name="คุณบีม")

    async def show_loading(self, external_user_id: str, seconds: int = 20) -> None:
        del external_user_id, seconds


class _FixedAdapterFactory:
    def __init__(self, adapter: ChannelAdapter) -> None:
        self._adapter = adapter

    async def get_adapter(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> ChannelAdapter | None:
        del tenant_id, channel_id
        return self._adapter


class _ReplyStubLLM:
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
            answer_text="ค่าส่ง 40 บาทค่ะ",
            handoff=False,
            handoff_reason=None,
            cited_chunk_indices=[1],
            input_tokens=100,
            output_tokens=20,
            model=model,
        )


async def _seed_tenant_user_and_conv(
    admin_factory: async_sessionmaker[AsyncSession],
    *,
    fernet_key: str,
    email: str,
    role: str = "agent",
    mode: str = "human",
    auto_return_hours: int = 24,
) -> tuple[UUID, UUID, UUID, UUID]:
    tenant_id, user_id, channel_id, conv_id = uuid4(), uuid4(), uuid4(), uuid4()
    enc = encrypt_credentials({"channel_access_token": "tok-x"}, fernet_key=fernet_key)
    async with admin_factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                name=f"Shop-{email}",
                plan="trial",
                status="trial",
                auto_return_hours=auto_return_hours,
                trial_ends_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.flush()
        session.add(BotSetting(tenant_id=tenant_id, shop_name=f"Shop-{email}"))
        session.add(User(id=user_id, tenant_id=tenant_id, email=email, role=role))
        session.add(
            Channel(
                id=channel_id,
                tenant_id=tenant_id,
                type="line",
                name="LINE OA",
                credentials_encrypted=enc,
                webhook_secret="sec",
                active=True,
            )
        )
        await session.flush()
        session.add(
            Conversation(
                id=conv_id,
                tenant_id=tenant_id,
                channel_id=channel_id,
                external_user_id=f"U_{tenant_id.hex[:8]}",
                mode=mode,
            )
        )
    return tenant_id, user_id, channel_id, conv_id


@pytest.mark.usefixtures("clean_database")
async def test_agent_reply_api_cross_tenant_denial_and_return_to_bot_flow(
    test_settings: Settings,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    cfg = test_settings.model_copy(update={"fernet_key": fernet_key})
    t_a, u_a, ch_a, conv_a = await _seed_tenant_user_and_conv(
        admin_session_factory, fernet_key=fernet_key, email="agent-a@shop.th", role="agent"
    )
    _, u_b, _, _ = await _seed_tenant_user_and_conv(
        admin_session_factory, fernet_key=fernet_key, email="agent-b@shop.th", role="owner"
    )

    token_a = create_dev_access_token(cfg, user_id=u_a, email="agent-a@shop.th")
    token_b = create_dev_access_token(cfg, user_id=u_b, email="agent-b@shop.th")
    fake_adapter = _FakeOutboundAdapter()
    app = create_app(cfg, adapter_factory=_FixedAdapterFactory(fake_adapter))

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        # 1. Missing auth -> 401
        r_unauth = await client.post(
            f"/conversations/{conv_a}/messages", json={"content": "สวัสดีครับ"}
        )
        assert r_unauth.status_code == 401

        # 2. Cross-tenant access -> 404 and zero outbound push
        r_cross = await client.post(
            f"/conversations/{conv_a}/messages",
            json={"content": "แอบตอบข้ามร้าน"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_cross.status_code == 404
        assert fake_adapter.pushes == []

        # 3. Valid agent reply -> 201, LINE push delivered, agent message persisted
        r_ok = await client.post(
            f"/conversations/{conv_a}/messages",
            json={"content": "แอดมินตรวจสอบยอดโอนให้แล้วนะคะ"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_ok.status_code == 201
        body = r_ok.json()
        assert body["role"] == "agent"
        assert body["mode"] == "human"
        assert body["last_agent_reply_at"] is not None
        assert len(fake_adapter.pushes) == 1
        assert fake_adapter.pushes[0][1] == "แอดมินตรวจสอบยอดโอนให้แล้วนะคะ"

        # 4. Return conversation to bot mode (cross-tenant -> 404, same tenant -> 200)
        r_cross_ret = await client.post(
            f"/conversations/{conv_a}/return-to-bot",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_cross_ret.status_code == 404

        r_ret = await client.post(
            f"/conversations/{conv_a}/return-to-bot",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_ret.status_code == 200
        assert r_ret.json()["mode"] == "bot"

    # 5. After return-to-bot, inbound customer text receives an AI reply again
    doc_id = uuid4()
    async with admin_session_factory() as session, session.begin():
        session.add(
            Document(
                id=doc_id, tenant_id=t_a, filename="ship.txt",
                mime="text/plain", storage_key="conv/ship.txt", status="pending",
            )
        )
    storage = InMemoryStorage()
    await storage.upload_bytes("conv/ship.txt", "ค่าส่ง 40 บาท".encode(), "text/plain")
    await ingest_document(
        app_session_factory, storage, MockEmbedder(), tenant_id=t_a, document_id=doc_id
    )

    async with tenant_scoped_session(app_session_factory, t_a) as session:
        conv_row = (
            await session.execute(select(Conversation).where(Conversation.id == conv_a))
        ).scalar_one()
        ext_uid = conv_row.external_user_id

    outcome = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        _ReplyStubLLM(),
        InMemoryBurstDebouncer(),
        cfg,
        tenant_id=t_a,
        channel_id=ch_a,
        event=InboundEvent("evt-back", ext_uid, "text", "ค่าส่งกี่บาทคะ", "rt-back", 3000),
        adapter=fake_adapter,
    )
    assert outcome.action == "replied"
    assert fake_adapter.replies == [("rt-back", "ค่าส่ง 40 บาทค่ะ")]

    async with tenant_scoped_session(app_session_factory, t_a) as session:
        msgs = (await session.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [m.role for m in msgs] == ["agent", "customer", "bot"]


@pytest.mark.usefixtures("clean_database")
async def test_auto_return_cron_respects_per_tenant_hours_and_agent_inactivity(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

    # Tenant A: 2h timeout; Tenant B: 24h timeout; Tenant C: 0 (disabled)
    t_a, _, ch_a, conv_a_stale_agent = await _seed_tenant_user_and_conv(
        admin_session_factory,
        fernet_key=fernet_key, email="a@shop.th", auto_return_hours=2,
    )
    t_b, _, _, conv_b_recent = await _seed_tenant_user_and_conv(
        admin_session_factory,
        fernet_key=fernet_key, email="b@shop.th", auto_return_hours=24,
    )
    t_c, _, _, conv_c_disabled = await _seed_tenant_user_and_conv(
        admin_session_factory,
        fernet_key=fernet_key, email="c@shop.th", auto_return_hours=0,
    )

    conv_a_active_agent = uuid4()
    conv_a_stale_no_agent = uuid4()
    async with admin_session_factory() as session, session.begin():
        c1 = (
            await session.execute(select(Conversation).where(Conversation.id == conv_a_stale_agent))
        ).scalar_one()
        c1.last_message_at = now - timedelta(hours=4)
        c1.last_agent_reply_at = now - timedelta(hours=3)

        session.add(
            Conversation(
                id=conv_a_active_agent,
                tenant_id=t_a,
                channel_id=ch_a,
                external_user_id="U_active_agent",
                mode="human",
                last_message_at=now - timedelta(hours=5),
                last_agent_reply_at=now - timedelta(minutes=30),
            )
        )
        session.add(
            Conversation(
                id=conv_a_stale_no_agent,
                tenant_id=t_a,
                channel_id=ch_a,
                external_user_id="U_stale_no_agent",
                mode="human",
                last_message_at=now - timedelta(hours=3),
                last_agent_reply_at=None,
            )
        )

        cb = (
            await session.execute(select(Conversation).where(Conversation.id == conv_b_recent))
        ).scalar_one()
        cb.last_agent_reply_at = now - timedelta(hours=3)

        cc = (
            await session.execute(select(Conversation).where(Conversation.id == conv_c_disabled))
        ).scalar_one()
        cc.last_message_at = now - timedelta(days=5)

    summary = await auto_return_inactive_conversations(app_session_factory, now=now)
    assert summary.tenants_checked == 3
    assert summary.conversations_returned == 2

    async with tenant_scoped_session(app_session_factory, t_a) as session:
        modes_a = {
            c.id: c.mode for c in (await session.execute(select(Conversation))).scalars().all()
        }
        assert modes_a[conv_a_stale_agent] == "bot"
        assert modes_a[conv_a_stale_no_agent] == "bot"
        assert modes_a[conv_a_active_agent] == "human"

    async with tenant_scoped_session(app_session_factory, t_b) as session:
        cb_after = (await session.execute(select(Conversation))).scalar_one()
        assert cb_after.mode == "human"

    async with tenant_scoped_session(app_session_factory, t_c) as session:
        cc_after = (await session.execute(select(Conversation))).scalar_one()
        assert cc_after.mode == "human"
