"""Reusable dual-tenant seed factories for isolation and integration tests."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BotSetting, Channel, Chunk, Conversation, Document, Message, Tenant


@dataclass(frozen=True)
class SeededTenants:
    """Identifiers produced by seed_two_tenants."""

    tenant_a_id: UUID
    tenant_b_id: UUID
    doc_a_id: UUID
    doc_b_id: UUID
    channel_a_id: UUID
    inactive_channel_b_id: UUID


async def seed_two_tenants(
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> SeededTenants:
    """Insert two isolated shops with documents, chunks, channels, and messages."""
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    doc_a_id = uuid4()
    doc_b_id = uuid4()
    channel_a_id = uuid4()
    inactive_channel_b_id = uuid4()
    conv_a_id = uuid4()
    conv_b_id = uuid4()

    async with admin_session_factory() as session, session.begin():
        session.add_all(
            [
                Tenant(id=tenant_a_id, name="Shop Alpha"),
                Tenant(id=tenant_b_id, name="Shop Beta"),
            ]
        )
        await session.flush()

        session.add_all(
            [
                BotSetting(tenant_id=tenant_a_id, shop_name="Shop Alpha"),
                BotSetting(tenant_id=tenant_b_id, shop_name="Shop Beta"),
                Document(
                    id=doc_a_id,
                    tenant_id=tenant_a_id,
                    filename="alpha_policy.pdf",
                    mime="application/pdf",
                    storage_key="a/alpha_policy.pdf",
                    status="ready",
                ),
                Document(
                    id=doc_b_id,
                    tenant_id=tenant_b_id,
                    filename="beta_secret.pdf",
                    mime="application/pdf",
                    storage_key="b/beta_secret.pdf",
                    status="ready",
                ),
                Channel(
                    id=channel_a_id,
                    tenant_id=tenant_a_id,
                    type="line",
                    name="Alpha LINE OA",
                    credentials_encrypted="enc_a",
                    webhook_secret="sec_a",
                    active=True,
                ),
                Channel(
                    id=inactive_channel_b_id,
                    tenant_id=tenant_b_id,
                    type="line",
                    name="Beta LINE OA",
                    credentials_encrypted="enc_b",
                    webhook_secret="sec_b",
                    active=False,
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                Chunk(
                    tenant_id=tenant_a_id,
                    document_id=doc_a_id,
                    content="นโยบายคืนสินค้าภายใน 7 วันของร้าน Alpha",
                    page=1,
                    chunk_index=0,
                    tokens=18,
                ),
                Chunk(
                    tenant_id=tenant_b_id,
                    document_id=doc_b_id,
                    content="ส่วนลดลับเฉพาะร้าน Beta 50%",
                    page=1,
                    chunk_index=0,
                    tokens=14,
                ),
                Conversation(
                    id=conv_a_id,
                    tenant_id=tenant_a_id,
                    channel_id=channel_a_id,
                    external_user_id="U_alpha_1",
                ),
                Conversation(
                    id=conv_b_id,
                    tenant_id=tenant_b_id,
                    channel_id=inactive_channel_b_id,
                    external_user_id="U_beta_1",
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                Message(
                    tenant_id=tenant_a_id,
                    conversation_id=conv_a_id,
                    role="customer",
                    content="สอบถามค่าจัดส่งครับ",
                ),
                Message(
                    tenant_id=tenant_b_id,
                    conversation_id=conv_b_id,
                    role="customer",
                    content="ความลับลูกค้า Beta",
                ),
            ]
        )

    return SeededTenants(
        tenant_a_id=tenant_a_id,
        tenant_b_id=tenant_b_id,
        doc_a_id=doc_a_id,
        doc_b_id=doc_b_id,
        channel_a_id=channel_a_id,
        inactive_channel_b_id=inactive_channel_b_id,
    )
