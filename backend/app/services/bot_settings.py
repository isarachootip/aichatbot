"""Service for reading and updating per-tenant bot settings and auto_return_hours."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenant_context import tenant_scoped_session
from app.models.messaging import Channel
from app.models.tenant import BotSetting, Tenant
from app.schemas.bot_settings import BotSettingsResponse, UpdateBotSettingsRequest


def _to_response(setting: BotSetting, auto_return_hours: int) -> BotSettingsResponse:
    return BotSettingsResponse(
        shop_name=setting.shop_name,
        tone=setting.tone,
        greeting=setting.greeting,
        handoff_keywords=list(setting.handoff_keywords or []),
        extra_instructions=setting.extra_instructions,
        fallback_message=setting.fallback_message,
        show_citations_to_customer=setting.show_citations_to_customer,
        handoff_notify_channel_id=setting.handoff_notify_channel_id,
        handoff_notify_target_id=setting.handoff_notify_target_id,
        auto_return_hours=auto_return_hours,
    )


async def get_bot_settings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> BotSettingsResponse:
    """Return the tenant's bot settings (auto-creating defaults if missing)."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one()
        setting = (
            await session.execute(select(BotSetting).where(BotSetting.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if setting is None:
            setting = BotSetting(tenant_id=tenant_id, shop_name=tenant.name)
            session.add(setting)
            await session.flush()
        return _to_response(setting, tenant.auto_return_hours)


async def update_bot_settings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    payload: UpdateBotSettingsRequest,
) -> BotSettingsResponse:
    """Update bot persona, handoff keywords, notify target, and auto-return hours."""
    cleaned_keywords = [kw.strip() for kw in payload.handoff_keywords if kw.strip()]
    target_id = (payload.handoff_notify_target_id or "").strip() or None

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one()

        if payload.handoff_notify_channel_id is not None:
            notify_ch = (
                await session.execute(
                    select(Channel).where(
                        Channel.id == payload.handoff_notify_channel_id,
                        Channel.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if notify_ch is None:
                raise ValueError("Selected notify channel does not belong to this tenant")

        setting = (
            await session.execute(select(BotSetting).where(BotSetting.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if setting is None:
            setting = BotSetting(tenant_id=tenant_id, shop_name=payload.shop_name.strip())
            session.add(setting)

        setting.shop_name = payload.shop_name.strip()
        setting.tone = payload.tone.strip()
        setting.greeting = payload.greeting.strip()
        setting.handoff_keywords = cleaned_keywords
        setting.extra_instructions = payload.extra_instructions.strip()
        setting.fallback_message = payload.fallback_message.strip()
        setting.show_citations_to_customer = payload.show_citations_to_customer
        setting.handoff_notify_channel_id = payload.handoff_notify_channel_id
        setting.handoff_notify_target_id = target_id

        tenant.name = setting.shop_name
        tenant.auto_return_hours = payload.auto_return_hours
        await session.flush()
        return _to_response(setting, tenant.auto_return_hours)
