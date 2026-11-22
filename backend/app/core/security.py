"""JWT authentication (Supabase JWKS + dev/test HS256) and RBAC helpers."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.tenant_context import resolve_user_tenant, tenant_scoped_session
from app.models.tenant import User

UserRole = Literal["owner", "admin", "agent"]
VALID_ROLES: frozenset[str] = frozenset({"owner", "admin", "agent"})
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Verified dashboard caller identity and tenant RBAC metadata."""

    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole
    is_super_admin: bool


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def create_dev_access_token(
    settings: Settings,
    *,
    user_id: UUID,
    email: str = "",
    expires_minutes: int = 60,
) -> str:
    """Issue a signed HS256 JWT strictly for development and automated tests."""
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Dev JWT tokens are forbidden outside development/test")
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.dev_jwt_secret, algorithm="HS256")


def decode_bearer_token(token: str, settings: Settings) -> dict[str, object]:
    """Decode and validate a Supabase JWKS or dev/test HS256 JWT."""
    if settings.supabase_jwks_url:
        signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},
        )
        return dict(decoded)

    if settings.app_env in {"development", "test"}:
        decoded = jwt.decode(
            token,
            settings.dev_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return dict(decoded)

    raise InvalidTokenError("SUPABASE_JWKS_URL must be configured in staging/production")


async def resolve_auth_context(
    token: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AuthContext:
    """Validate Bearer JWT and resolve the user's tenant and role under FORCE RLS."""
    try:
        claims = decode_bearer_token(token, settings)
        sub_raw = claims.get("sub")
        if not isinstance(sub_raw, str):
            raise InvalidTokenError("Missing sub claim")
        user_id = UUID(sub_raw)
    except (InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        ) from exc

    async with session_factory() as lookup_session, lookup_session.begin():
        resolved = await resolve_user_tenant(lookup_session, user_id)

    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is not registered",
        )
    tenant_id, _ = resolved

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        user = (
            await session.execute(
                select(User).where(User.id == user_id, User.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if user is None or user.role not in VALID_ROLES:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated user record not found",
            )
        role_val: UserRole = user.role  # type: ignore[assignment]
        return AuthContext(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=role_val,
            is_super_admin=user.is_super_admin,
        )


def require_roles(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    allowed_roles: tuple[UserRole, ...],
) -> Callable[[HTTPAuthorizationCredentials | None], Coroutine[object, object, AuthContext]]:
    """Build a FastAPI dependency enforcing JWT auth and allowed tenant roles."""

    async def _dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    ) -> AuthContext:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer authorization token",
            )
        auth = await resolve_auth_context(
            credentials.credentials,
            session_factory=session_factory,
            settings=settings,
        )
        if auth.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions",
            )
        return auth

    return _dependency
