"""Multi-tenancy: add owner_id to app_settings, bot_sessions, technician_profiles.

Revision ID: 20260818_02
Revises: 20260818_01
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20260818_02"
down_revision = "20260818_01"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # --- app_settings: add owner_id ---
    if not _column_exists(conn, "app_settings", "owner_id"):
        op.add_column(
            "app_settings",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )

    # --- bot_sessions: add owner_id ---
    if not _column_exists(conn, "bot_sessions", "owner_id"):
        op.add_column(
            "bot_sessions",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )

    # --- technician_profiles: add owner_id ---
    if not _column_exists(conn, "technician_profiles", "owner_id"):
        op.add_column(
            "technician_profiles",
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )

    # --- data migration: assign existing rows to first non-admin owner ---
    result = conn.execute(
        sa.text(
            "SELECT id FROM users WHERE role != 'admin' ORDER BY id LIMIT 1"
        )
    )
    row = result.fetchone()
    if row is None:
        # fallback: use first user of any role
        result = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1"))
        row = result.fetchone()

    if row is not None:
        owner_id = row[0]
        conn.execute(
            sa.text("UPDATE app_settings SET owner_id = :oid WHERE owner_id IS NULL"),
            {"oid": owner_id},
        )
        conn.execute(
            sa.text("UPDATE technician_profiles SET owner_id = :oid WHERE owner_id IS NULL"),
            {"oid": owner_id},
        )
        conn.execute(
            sa.text(
                "UPDATE bot_sessions SET owner_id = :oid "
                "WHERE bot_type = 'ktv' AND owner_id IS NULL"
            ),
            {"oid": owner_id},
        )

    # --- make owner_id NOT NULL after data fill ---
    # app_settings: only if there are rows (skip for empty fresh DB)
    count = conn.execute(sa.text("SELECT COUNT(*) FROM app_settings WHERE owner_id IS NULL")).scalar()
    if count == 0:
        op.alter_column("app_settings", "owner_id", nullable=False)

    count = conn.execute(sa.text("SELECT COUNT(*) FROM technician_profiles WHERE owner_id IS NULL")).scalar()
    if count == 0:
        op.alter_column("technician_profiles", "owner_id", nullable=False)

    # --- unique constraint on app_settings.owner_id ---
    result = conn.execute(
        sa.text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name = 'app_settings' AND constraint_name = 'uq_app_settings_owner_id'"
        )
    )
    if not result.fetchone():
        op.create_unique_constraint("uq_app_settings_owner_id", "app_settings", ["owner_id"])


def downgrade() -> None:
    op.drop_constraint("uq_app_settings_owner_id", "app_settings", type_="unique")
    op.drop_column("app_settings", "owner_id")
    op.drop_column("bot_sessions", "owner_id")
    op.drop_column("technician_profiles", "owner_id")
