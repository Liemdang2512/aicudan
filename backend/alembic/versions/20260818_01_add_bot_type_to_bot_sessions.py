"""Add bot_type column to bot_sessions for multi-bot support (manager vs KTV).

Revision ID: 20260818_01
Revises: 20260814_01
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa

revision = "20260818_01"
down_revision = "20260814_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bot_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("bot_type", sa.String(20), nullable=False, server_default="manager")
        )


def downgrade() -> None:
    with op.batch_alter_table("bot_sessions") as batch_op:
        batch_op.drop_column("bot_type")
