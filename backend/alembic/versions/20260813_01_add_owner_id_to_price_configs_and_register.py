"""Add owner_id to price_configs for multi-tenant isolation.

Revision ID: 20260813_01
Revises: 20260808_03_add_ktv_app_settings
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_01"
down_revision: str | None = "20260808_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add owner_id to price_configs (nullable for backward compat with existing rows)
    # SQLite does not support ADD CONSTRAINT via ALTER — FK enforced at application level
    # Idempotent: skip if column already exists (e.g. partial previous run)
    conn = op.get_bind()
    cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(price_configs)")).fetchall()]
    if "owner_id" not in cols:
        op.add_column("price_configs", sa.Column("owner_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_configs", "owner_id")
