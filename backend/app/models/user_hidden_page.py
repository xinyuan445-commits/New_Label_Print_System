"""Per-user menu visibility. Hidden entries do not revoke access."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserHiddenPage(Base):
    __tablename__ = "user_hidden_pages"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    page: Mapped[str] = mapped_column(String(32), primary_key=True)
