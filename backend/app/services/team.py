"""Team member invitation, listing, role update, and removal service (owner-only)."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import UserRole
from app.core.tenant_context import resolve_user_by_email, tenant_scoped_session
from app.models.tenant import User
from app.schemas.team import TeamMemberResponse


class TeamMemberNotFoundError(LookupError):
    """Raised when a target team member does not exist in the caller's tenant."""


class TeamConflictError(ValueError):
    """Raised on duplicate email invite or invalid last-owner removal/demotion."""


def _normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
        raise ValueError("Invalid email address format")
    return cleaned


def _to_response(user: User) -> TeamMemberResponse:
    role_val: UserRole = user.role  # type: ignore[assignment]
    return TeamMemberResponse(
        id=user.id,
        email=user.email,
        role=role_val,
        created_at=user.created_at,
    )


async def list_team_members(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> list[TeamMemberResponse]:
    """List all users belonging to a tenant ordered by creation date."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        rows = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.asc())
            )
        ).scalars().all()
    return [_to_response(u) for u in rows]


async def invite_team_member(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    email: str,
    role: UserRole,
) -> TeamMemberResponse:
    """Create a new user membership in the caller's tenant under FORCE RLS."""
    cleaned_email = _normalize_email(email)
    async with session_factory() as lookup_session, lookup_session.begin():
        existing = await resolve_user_by_email(lookup_session, cleaned_email)
    if existing is not None:
        raise TeamConflictError("Email is already registered in a workspace")

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        member = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=cleaned_email,
            role=role,
            is_super_admin=False,
        )
        session.add(member)
        await session.flush()
        return _to_response(member)


async def update_member_role(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    member_id: UUID,
    new_role: UserRole,
) -> TeamMemberResponse:
    """Update a tenant member's role while protecting against removing the last owner."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        member = (
            await session.execute(
                select(User).where(User.id == member_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if member is None:
            raise TeamMemberNotFoundError(f"Team member {member_id} not found")

        if member.role == "owner" and new_role != "owner":
            owner_count = int(
                (
                    await session.execute(
                        select(func.count(User.id)).where(
                            User.tenant_id == tenant_id,
                            User.role == "owner",
                        )
                    )
                ).scalar_one()
            )
            if owner_count <= 1:
                raise TeamConflictError("Cannot demote the last owner of the shop")

        member.role = new_role
        await session.flush()
        return _to_response(member)


async def remove_team_member(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    member_id: UUID,
) -> None:
    """Delete a team member while preventing self-removal or deleting the last owner."""
    if actor_user_id == member_id:
        raise TeamConflictError("Cannot remove your own account from the team")

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        member = (
            await session.execute(
                select(User).where(User.id == member_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if member is None:
            raise TeamMemberNotFoundError(f"Team member {member_id} not found")

        if member.role == "owner":
            owner_count = int(
                (
                    await session.execute(
                        select(func.count(User.id)).where(
                            User.tenant_id == tenant_id,
                            User.role == "owner",
                        )
                    )
                ).scalar_one()
            )
            if owner_count <= 1:
                raise TeamConflictError("Cannot remove the last owner of the shop")

        await session.delete(member)
