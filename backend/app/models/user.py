"""User model + Role enum."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user_disabled_page import UserDisabledPage
    from app.models.user_hidden_page import UserHiddenPage

PAGE_FEATURES = ("bills", "templates", "printers", "library", "history")
VISIBLE_PAGES = (
    "dashboard",
    "bills",
    "templates",
    "printers",
    "library",
    "history",
    "help",
    "users",
)


class Role(enum.StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base, UserMixin):  # type: ignore[misc]  # UserMixin is loosely typed in flask-login
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [r.value for r in e]),
        nullable=False,
        default=Role.EDITOR,
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="pl")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_pages: Mapped[list[UserDisabledPage]] = relationship(
        "UserDisabledPage", cascade="all, delete-orphan", lazy="selectin"
    )
    hidden_pages: Mapped[list[UserHiddenPage]] = relationship(
        "UserHiddenPage", cascade="all, delete-orphan", lazy="selectin"
    )

    # Flask-Login expects `is_active` (provided), `is_authenticated`, `is_anonymous`,
    # and `get_id()` — UserMixin provides those, but is_active here overrides.

    def get_id(self) -> str:
        return str(self.id)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def permissions(self) -> dict[str, bool]:
        disabled = {entry.page for entry in self.disabled_pages} if not self.is_admin else set()
        return {page: page not in disabled for page in PAGE_FEATURES}

    @property
    def visibility(self) -> dict[str, bool]:
        hidden = {entry.page for entry in self.hidden_pages}
        return {page: page not in hidden for page in VISIBLE_PAGES}

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
