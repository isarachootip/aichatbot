"""SQLAlchemy 2.x DeclarativeBase and shared naming conventions."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarative class shared by all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[UUID]:
    """Create a standard UUID primary key column."""
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)


def created_at_col() -> Mapped[datetime]:
    """Create a timezone-aware server-defaulted created_at column."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
