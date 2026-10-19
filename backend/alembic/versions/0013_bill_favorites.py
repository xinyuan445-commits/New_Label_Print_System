"""Per-user U8 bill shortcuts.

Revision ID: 0013_bill_favorites
Revises: 0012_generated_files
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_bill_favorites"
down_revision: str | None = "0012_generated_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bill_favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bill_type", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "bill_type"),
    )
    op.create_index("ix_bill_favorites_user_id", "bill_favorites", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_bill_favorites_user_id", table_name="bill_favorites")
    op.drop_table("bill_favorites")
