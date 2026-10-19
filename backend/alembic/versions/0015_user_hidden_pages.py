"""Per-user page visibility.

Revision ID: 0015_user_hidden_pages
Revises: 0014_user_disabled_pages
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_user_hidden_pages"
down_revision: str | None = "0014_user_disabled_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_hidden_pages",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("page", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "page"),
    )


def downgrade() -> None:
    op.drop_table("user_hidden_pages")
