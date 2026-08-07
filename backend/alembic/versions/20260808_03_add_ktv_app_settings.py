"""add ktv app settings

Revision ID: 20260808_03
Revises: 20260808_02
Create Date: 2026-08-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260808_03"
down_revision = "20260808_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "telegram_ktv_bot_token",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "telegram_ktv_password",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "manager_telegram_chat_id",
            sa.String(length=100),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "manager_telegram_chat_id")
    op.drop_column("app_settings", "telegram_ktv_password")
    op.drop_column("app_settings", "telegram_ktv_bot_token")
