"""Remove Telegram credentials copied across tenant settings.

Revision ID: 20260820_01
Revises: 20260818_02
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "20260820_01"
down_revision = "20260818_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # A Telegram bot token identifies one bot and cannot safely belong to two
    # independent tenants. Preserve the oldest settings row and clear copies.
    conn.execute(
        sa.text(
            """
            UPDATE app_settings AS current_setting
            SET telegram_bot_token = ''
            WHERE current_setting.telegram_bot_token <> ''
              AND EXISTS (
                  SELECT 1
                  FROM app_settings AS earlier_setting
                  WHERE earlier_setting.id < current_setting.id
                    AND earlier_setting.telegram_bot_token = current_setting.telegram_bot_token
              )
            """
        )
    )

    # The KTV password and manager destination were copied together with the
    # duplicated KTV bot token, so reset the whole KTV configuration copy.
    conn.execute(
        sa.text(
            """
            UPDATE app_settings AS current_setting
            SET telegram_ktv_bot_token = '',
                telegram_ktv_password = '',
                manager_telegram_chat_id = ''
            WHERE current_setting.telegram_ktv_bot_token <> ''
              AND EXISTS (
                  SELECT 1
                  FROM app_settings AS earlier_setting
                  WHERE earlier_setting.id < current_setting.id
                    AND earlier_setting.telegram_ktv_bot_token = current_setting.telegram_ktv_bot_token
              )
            """
        )
    )


def downgrade() -> None:
    # Cleared credentials cannot be reconstructed safely.
    pass
