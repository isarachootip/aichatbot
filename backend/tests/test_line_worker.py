"""End-to-end mocked LINE API worker tests (RAG reply, fallback, debounce, media, quota)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import InboundEvent, ReplyTokenExpiredError, UserProfile
from app.core.config import Settings
from app.core.crypto import encrypt_credentials, generate_fernet_key
from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Document
from app.models.messaging import Channel, Conversation, Message
from app.models.operations import Notification
from app.models.tenant import BotSetting, Tenant, UsageMonthly
from app.rag.embeddings import MockEmbedder
from app.rag.types import StructuredLLMResponse
from app.services.debounce import InMemoryBurstDebouncer
from app.services.quota import current_usage_month
from app.workers.ingest import ingest_document
from app.workers.line_inbound import handle_line_event


class _FakeLineAdapter:
    """Mocked LINE ChannelAdapter recording replies, pushes, profiles, and loading calls."""

    def __init__(self, *, expire_reply_token: bool = False) -> None:
        self.expire_reply_token = expire_reply_token
        self.replies: list[tuple[str, str]] = []
        self.pushes: list[tuple[str, str]] = []
        self.loading_calls: list[str] = []

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        del body, signature, secret
        return True

    def parse_events(self, payload: dict[str, object]) -> list[InboundEvent]:
        del payload
        return []

    async def send_reply(self, reply_token: str, text: str) -> None:
        if self.expire_reply_token:
            raise ReplyTokenExpiredError("expired token")
        self.replies.append((reply_token, text))

    async def send_push(self, external_user_id: str, text: str) -> None:
        self.pushes.append((external_user_id, text))

    async def get_profile(self, external_user_id: str) -> UserProfile:
        return UserProfile(external_user_id=external_user_id, display_name="คุณสมชาย")

    async def show_loading(self, external_user_id: str, seconds: int = 20) -> None:
        del seconds
        self.loading_calls.append(external_user_id)


class _StubLLM:
    def __init__(self, answer_text: str = "ค่าจัดส่ง 40 บาท ส่งฟรีครบ 500 บาทค่ะ") -> None:
        self.answer_text = answer_text
        self.seen_questions: list[str] = []

    async def generate_grounded_reply(
        self,
        *,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        model: str,
        max_tokens: int = 600,
    ) -> StructuredLLMResponse:
        del system_prompt, max_tokens
        self.seen_questions.append(messages[-1]["content"])
        return StructuredLLMResponse(
            answer_text=self.answer_text,
            handoff=False,
            handoff_reason=None,
            cited_chunk_indices=[1],
            input_tokens=180,
            output_tokens=45,
            model=model,
        )


async def _seed_shop_with_kb(
    admin_factory: async_sessionmaker[AsyncSession],
    app_factory: async_sessionmaker[AsyncSession],
    *,
    fernet_key: str,
    tenant_status: str = "trial",
    trial_ends_at: datetime | None = None,
    used_messages: int = 0,
) -> tuple[UUID, UUID, UUID]:
    tenant_id, channel_id, doc_id = uuid4(), uuid4(), uuid4()
    enc = encrypt_credentials({"channel_access_token": "tok-1"}, fernet_key=fernet_key)
    async with admin_factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                name="ร้านสยาม LINE",
                plan="trial",
                status=tenant_status,
                trial_ends_at=trial_ends_at or (datetime.now(UTC) + timedelta(days=7)),
            )
        )
        await session.flush()
        session.add(BotSetting(tenant_id=tenant_id, shop_name="ร้านสยาม LINE"))
        session.add(
            Channel(
                id=channel_id,
                tenant_id=tenant_id,
                type="line",
                name="LINE OA",
                credentials_encrypted=enc,
                webhook_secret="sec-1",
                active=True,
            )
        )
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename="faq.txt",
                mime="text/plain",
                storage_key="line/faq.txt",
                status="pending",
            )
        )
        if used_messages > 0:
            session.add(
                UsageMonthly(
                    tenant_id=tenant_id,
                    month=current_usage_month(),
                    message_count=used_messages,
                    input_tokens=1000,
                    output_tokens=200,
                )
            )

    storage = InMemoryStorage()
    await storage.upload_bytes(
        "line/faq.txt",
        "ค่าจัดส่ง 40 บาท ส่งฟรีเมื่อซื้อครบ 500 บาท".encode(),
        "text/plain",
    )
    res = await ingest_document(
        app_factory,
        storage,
        MockEmbedder(),
        tenant_id=tenant_id,
        document_id=doc_id,
    )
    assert res.status == "ready"
    return tenant_id, channel_id, doc_id


@pytest.mark.usefixtures("clean_database")
async def test_line_worker_e2e_reply_push_fallback_and_usage_logging(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, channel_id, doc_id = await _seed_shop_with_kb(
        admin_session_factory,
        app_session_factory,
        fernet_key=fernet_key,
    )
    settings = Settings(fernet_key=fernet_key, llm_default_model="gemini-3.5-flash-lite")
    adapter = _FakeLineAdapter(expire_reply_token=True)
    llm = _StubLLM()
    debouncer = InMemoryBurstDebouncer()
    event = InboundEvent("evt-1", "U_buyer", "text", "ค่าส่งกี่บาทคะ", "rt-exp", 1700000001000)

    outcome = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=event,
        adapter=adapter,
    )

    assert outcome.action == "replied"
    assert outcome.delivery_method == "push"
    assert adapter.loading_calls == ["U_buyer"]
    assert len(adapter.pushes) == 1
    assert "40 บาท" in adapter.pushes[0][1]

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.customer_name == "คุณสมชาย"
        msgs = (await session.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [m.role for m in msgs] == ["customer", "bot"]
        assert msgs[1].sources[0]["document_id"] == str(doc_id)
        assert msgs[1].input_tokens == 180
        assert msgs[1].output_tokens == 45

        usage = (await session.execute(select(UsageMonthly))).scalar_one()
        assert usage.message_count == 1
        assert usage.input_tokens == 180
        assert usage.output_tokens == 45


@pytest.mark.usefixtures("clean_database")
async def test_line_worker_debounce_coalesces_rapid_text_burst(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, channel_id, _ = await _seed_shop_with_kb(
        admin_session_factory,
        app_session_factory,
        fernet_key=fernet_key,
    )
    settings = Settings(fernet_key=fernet_key)
    debouncer = InMemoryBurstDebouncer()
    adapter = _FakeLineAdapter()
    llm = _StubLLM()

    evt1 = InboundEvent("evt-b1", "U_fast", "text", "สวัสดีค่ะ", "rt-1", 1000)
    evt2 = InboundEvent("evt-b2", "U_fast", "text", "ค่าส่งกี่บาทคะ", "rt-2", 2000)
    await debouncer.mark_latest(
        tenant_id=tenant_id,
        channel_id=channel_id,
        external_user_id="U_fast",
        event_id="evt-b2",
    )

    out1 = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=evt1,
        adapter=adapter,
    )
    out2 = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=evt2,
        adapter=adapter,
    )

    assert out1.action == "debounced_skip"
    assert out2.action == "replied"
    assert len(adapter.replies) == 1
    assert len(llm.seen_questions) == 1
    assert "สวัสดีค่ะ" in llm.seen_questions[0]
    assert "ค่าส่งกี่บาทคะ" in llm.seen_questions[0]


@pytest.mark.usefixtures("clean_database")
async def test_line_worker_image_handoff_and_sticker_fallback(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, channel_id, _ = await _seed_shop_with_kb(
        admin_session_factory,
        app_session_factory,
        fernet_key=fernet_key,
    )
    settings = Settings(fernet_key=fernet_key)
    adapter = _FakeLineAdapter()
    llm = _StubLLM()
    debouncer = InMemoryBurstDebouncer()

    # Sticker -> polite fallback without handoff
    stk_out = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=InboundEvent("evt-stk", "U_media", "sticker", None, "rt-stk", 1000),
        adapter=adapter,
    )
    assert stk_out.action == "sticker_fallback"
    assert stk_out.handoff is False
    assert len(llm.seen_questions) == 0

    # Image/slip -> polite reply + immediate switch to human mode + notification
    img_out = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=InboundEvent("evt-img", "U_media", "image", None, "rt-img", 2000),
        adapter=adapter,
    )
    assert img_out.action == "image_handoff"
    assert img_out.handoff is True
    assert len(adapter.replies) == 2

    # Subsequent text while in human mode -> bot stays completely silent
    silent_out = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=channel_id,
        event=InboundEvent("evt-after", "U_media", "text", "โอนแล้วค่ะ", "rt-after", 3000),
        adapter=adapter,
    )
    assert silent_out.action == "silent_human_mode"
    assert len(adapter.replies) == 2
    assert len(llm.seen_questions) == 0


@pytest.mark.usefixtures("clean_database")
async def test_line_worker_quota_exceeded_and_trial_expired_stay_silent_and_notify(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    # 1. Quota 100% (trial limit = 200)
    tid_q, cid_q, _ = await _seed_shop_with_kb(
        admin_session_factory,
        app_session_factory,
        fernet_key=fernet_key,
        used_messages=200,
    )
    adapter_q = _FakeLineAdapter()
    llm_q = _StubLLM()
    out_q = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm_q,
        InMemoryBurstDebouncer(),
        Settings(fernet_key=fernet_key),
        tenant_id=tid_q,
        channel_id=cid_q,
        event=InboundEvent("evt-q", "U_q", "text", "ค่าส่งกี่บาท", "rt-q", 1000),
        adapter=adapter_q,
    )
    assert out_q.action == "silent_quota_exceeded"
    assert adapter_q.replies == []
    assert adapter_q.pushes == []
    assert llm_q.seen_questions == []

    async with tenant_scoped_session(app_session_factory, tid_q) as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.mode == "human"
        notif = (await session.execute(select(Notification))).scalar_one()
        assert notif.type == "quota_exceeded"

    # 2. Trial expired
    tid_t, cid_t, _ = await _seed_shop_with_kb(
        admin_session_factory,
        app_session_factory,
        fernet_key=fernet_key,
        trial_ends_at=datetime.now(UTC) - timedelta(hours=1),
    )
    adapter_t = _FakeLineAdapter()
    out_t = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        _StubLLM(),
        InMemoryBurstDebouncer(),
        Settings(fernet_key=fernet_key),
        tenant_id=tid_t,
        channel_id=cid_t,
        event=InboundEvent("evt-t", "U_t", "text", "สอบถามค่ะ", "rt-t", 1000),
        adapter=adapter_t,
    )
    assert out_t.action == "silent_trial_expired"
    assert adapter_t.replies == []
    assert adapter_t.pushes == []
