"""Add app_settings table for persistent application configuration.

Revision ID: 20260808_01
Revises: 20260804_01
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_01"
down_revision: str | None = "20260804_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gemini_api_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("telegram_bot_token", sa.String(500), nullable=False, server_default=""),
        sa.Column("payment_management_unit", sa.String(200), nullable=False, server_default=""),
        sa.Column("payment_bank_account", sa.String(100), nullable=False, server_default=""),
        sa.Column("payment_bank_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("payment_account_holder", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
