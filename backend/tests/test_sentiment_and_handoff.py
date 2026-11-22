"""Tests for Phase 4 handoff triggers (RAG, keywords, frustration), alerts, and bot silence."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent, UserProfile
from app.core.config import Settings
from app.core.crypto import encrypt_credentials, generate_fernet_key
from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Document
from app.models.messaging import Channel, Conversation, Message, UnansweredQuestion
from app.models.operations import Notification
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import MockEmbedder
from app.rag.types import StructuredLLMResponse
from app.services.debounce import InMemoryBurstDebouncer
from app.services.handoff import evaluate_pre_llm_handoff
from app.services.sentiment import detect_strong_frustration
from app.workers.ingest import ingest_document
from app.workers.line_inbound import handle_line_event


class _RecordingAdapter:
    def __init__(self, *, fail_push: bool = False) -> None:
        self.fail_push = fail_push
        self.replies: list[tuple[str, str]] = []
        self.pushes: list[tuple[str, str]] = []

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        del body, signature, secret
        return True

    def parse_events(self, payload: dict[str, object]) -> list[InboundEvent]:
        del payload
        return []

    async def send_reply(self, reply_token: str, text: str) -> None:
        self.replies.append((reply_token, text))

    async def send_push(self, external_user_id: str, text: str) -> None:
        if self.fail_push:
            raise RuntimeError("Simulated LINE notify API outage")
        self.pushes.append((external_user_id, text))

    async def get_profile(self, external_user_id: str) -> UserProfile:
        return UserProfile(external_user_id=external_user_id, display_name="คุณนภา")

    async def show_loading(self, external_user_id: str, seconds: int = 20) -> None:
        del external_user_id, seconds


class _MapAdapterFactory:
    def __init__(self, adapters: dict[UUID, ChannelAdapter]) -> None:
        self._adapters = adapters

    async def get_adapter(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> ChannelAdapter | None:
        del tenant_id
        return self._adapters.get(channel_id)


class _HandoffStubLLM:
    def __init__(self, *, handoff: bool, reason: str | None = None) -> None:
        self.handoff = handoff
        self.reason = reason
        self.calls: int = 0

    async def generate_grounded_reply(
        self,
        *,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        model: str,
        max_tokens: int = 600,
    ) -> StructuredLLMResponse:
        del system_prompt, messages, max_tokens
        self.calls += 1
        return StructuredLLMResponse(
            answer_text="ขออภัยค่ะ ข้อมูลส่วนนี้ขออนุญาตให้แอดมินตรวจสอบและติดต่อกลับนะคะ",
            handoff=self.handoff,
            handoff_reason=self.reason,
            cited_chunk_indices=[],
            input_tokens=120,
            output_tokens=30,
            model=model,
        )


def test_pre_llm_keyword_and_frustration_detection_rules() -> None:
    """Verify Thai keyword matching, strong frustration triggers, and zero false positives."""
    kw_match = evaluate_pre_llm_handoff("ขอคุยกับ แอดมิน หน่อยค่ะ", ["แอดมิน", "คุยกับคน"])
    assert kw_match is not None
    assert kw_match.reason == "keyword"
    assert kw_match.matched_term == "แอดมิน"

    high_frust = detect_strong_frustration("ร้านนี้โกงมาก จะแจ้ง สคบ แน่นอน")
    assert high_frust.is_frustrated is True

    med_combo = detect_strong_frustration("บริการแย่ รอนานมาก")
    assert med_combo.is_frustrated is True

    punct_combo = detect_strong_frustration("ไม่พอใจ!!!")
    assert punct_combo.is_frustrated is True

    for polite_msg in (
        "ค่าส่งกี่บาทคะ",
        "ขอเปลี่ยนไซส์เสื้อได้ไหมคะ",
        "รอนานไหมคะกว่าของจะถึง",
        "สั่งสินค้ายังไงครับ",
    ):
        assert detect_strong_frustration(polite_msg).is_frustrated is False
        assert evaluate_pre_llm_handoff(polite_msg, ["แอดมิน", "คุยกับคน"]) is None


async def _seed_tenant_with_notify_group(
    admin_factory: async_sessionmaker[AsyncSession],
    app_factory: async_sessionmaker[AsyncSession],
    *,
    fernet_key: str,
    fallback_message: str = "เดี๋ยวแอดมินรีบเข้ามาดูแลให้นะคะ",
) -> tuple[UUID, UUID, UUID]:
    tenant_id, main_channel_id, notify_channel_id, doc_id = uuid4(), uuid4(), uuid4(), uuid4()
    enc = encrypt_credentials({"channel_access_token": "tok-1"}, fernet_key=fernet_key)
    async with admin_factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                name="ร้านไทยแฮนด์ออฟ",
                plan="trial",
                status="trial",
                trial_ends_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.flush()
        session.add(
            Channel(
                id=main_channel_id,
                tenant_id=tenant_id,
                type="line",
                name="Main LINE OA",
                credentials_encrypted=enc,
                webhook_secret="sec-main",
                active=True,
            )
        )
        session.add(
            Channel(
                id=notify_channel_id,
                tenant_id=tenant_id,
                type="line",
                name="Admin Alert Bot",
                credentials_encrypted=enc,
                webhook_secret="sec-notify",
                active=True,
            )
        )
        await session.flush()
        session.add(
            BotSetting(
                tenant_id=tenant_id,
                shop_name="ร้านไทยแฮนด์ออฟ",
                handoff_keywords=["แอดมิน", "คุยกับคน", "ติดต่อเจ้าหน้าที่"],
                fallback_message=fallback_message,
                handoff_notify_channel_id=notify_channel_id,
                handoff_notify_target_id="C_admin_group_001",
            )
        )
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename="faq.txt",
                mime="text/plain",
                storage_key="handoff/faq.txt",
                status="pending",
            )
        )

    storage = InMemoryStorage()
    await storage.upload_bytes("handoff/faq.txt", "ค่าจัดส่ง 40 บาท".encode(), "text/plain")
    res = await ingest_document(
        app_factory, storage, MockEmbedder(), tenant_id=tenant_id, document_id=doc_id
    )
    assert res.status == "ready"
    return tenant_id, main_channel_id, notify_channel_id


@pytest.mark.usefixtures("clean_database")
async def test_rag_handoff_switches_to_human_logs_unanswered_and_pushes_line_group(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, main_ch, notify_ch = await _seed_tenant_with_notify_group(
        admin_session_factory, app_session_factory, fernet_key=fernet_key
    )
    customer_adapter = _RecordingAdapter()
    notify_adapter = _RecordingAdapter()
    llm = _HandoffStubLLM(handoff=True, reason="out_of_scope")

    out = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        InMemoryBurstDebouncer(),
        Settings(fernet_key=fernet_key),
        tenant_id=tenant_id,
        channel_id=main_ch,
        event=InboundEvent("evt-rag", "U_rag", "text", "มีผ่อน 0% ไหมคะ", "rt-rag", 1000),
        adapter=customer_adapter,
        notify_adapter_factory=_MapAdapterFactory({notify_ch: notify_adapter}),
    )

    assert out.action == "handoff_rag"
    assert out.handoff is True
    assert llm.calls == 1
    assert len(customer_adapter.replies) == 1
    assert len(notify_adapter.pushes) == 1
    assert notify_adapter.pushes[0][0] == "C_admin_group_001"
    assert "มีผ่อน 0% ไหมคะ" in notify_adapter.pushes[0][1]

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.mode == "human"
        uq = (await session.execute(select(UnansweredQuestion))).scalar_one()
        assert uq.question == "มีผ่อน 0% ไหมคะ"
        notif = (await session.execute(select(Notification))).scalar_one()
        assert notif.type == "handoff"
        assert notif.payload["reason"] == "rag_low_confidence"


@pytest.mark.usefixtures("clean_database")
async def test_keyword_handoff_skips_llm_notifies_and_bot_stays_silent_afterward(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, main_ch, notify_ch = await _seed_tenant_with_notify_group(
        admin_session_factory, app_session_factory, fernet_key=fernet_key
    )
    customer_adapter = _RecordingAdapter()
    notify_adapter = _RecordingAdapter()
    llm = _HandoffStubLLM(handoff=False)
    debouncer = InMemoryBurstDebouncer()
    settings = Settings(fernet_key=fernet_key)

    out1 = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=main_ch,
        event=InboundEvent("evt-kw1", "U_kw", "text", "ขอคุยกับคนได้ไหมคะ", "rt-kw1", 1000),
        adapter=customer_adapter,
        notify_adapter_factory=_MapAdapterFactory({notify_ch: notify_adapter}),
    )
    assert out1.action == "handoff_keyword"
    assert out1.handoff is True
    assert llm.calls == 0
    assert customer_adapter.replies == [("rt-kw1", "เดี๋ยวแอดมินรีบเข้ามาดูแลให้นะคะ")]
    assert len(notify_adapter.pushes) == 1

    # Follow-up message while in human mode -> bot stays completely silent, customer msg saved
    out2 = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        debouncer,
        settings,
        tenant_id=tenant_id,
        channel_id=main_ch,
        event=InboundEvent("evt-kw2", "U_kw", "text", "รออยู่นะคะ", "rt-kw2", 2000),
        adapter=customer_adapter,
        notify_adapter_factory=_MapAdapterFactory({notify_ch: notify_adapter}),
    )
    assert out2.action == "silent_human_mode"
    assert llm.calls == 0
    assert len(customer_adapter.replies) == 1
    assert len(notify_adapter.pushes) == 1

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        msgs = (await session.execute(select(Message).order_by(Message.created_at))).scalars().all()
        assert [m.role for m in msgs] == ["customer", "bot", "customer"]
        assert msgs[2].content == "รออยู่นะคะ"


@pytest.mark.usefixtures("clean_database")
async def test_frustration_handoff_and_resilience_when_line_notify_push_fails(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    fernet_key = generate_fernet_key()
    tenant_id, main_ch, notify_ch = await _seed_tenant_with_notify_group(
        admin_session_factory, app_session_factory, fernet_key=fernet_key
    )
    customer_adapter = _RecordingAdapter()
    failing_notify_adapter = _RecordingAdapter(fail_push=True)
    llm = _HandoffStubLLM(handoff=False)

    out = await handle_line_event(
        app_session_factory,
        MockEmbedder(),
        llm,
        InMemoryBurstDebouncer(),
        Settings(fernet_key=fernet_key),
        tenant_id=tenant_id,
        channel_id=main_ch,
        event=InboundEvent(
            "evt-ang", "U_ang", "text", "บริการแย่มาก คืนเงินเดี๋ยวนี้", "rt-ang", 1000
        ),
        adapter=customer_adapter,
        notify_adapter_factory=_MapAdapterFactory({notify_ch: failing_notify_adapter}),
    )

    assert out.action == "handoff_frustration"
    assert out.handoff is True
    assert llm.calls == 0
    assert customer_adapter.replies == [("rt-ang", "เดี๋ยวแอดมินรีบเข้ามาดูแลให้นะคะ")]

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.mode == "human"
        uq = (await session.execute(select(UnansweredQuestion))).scalar_one()
        assert "คืนเงินเดี๋ยวนี้" in uq.question
        notif = (await session.execute(select(Notification))).scalar_one()
        assert notif.payload["reason"] == "frustration"
