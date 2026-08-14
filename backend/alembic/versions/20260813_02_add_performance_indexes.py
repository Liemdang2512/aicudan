"""Add performance indexes for frequently filtered columns.

Revision ID: 20260813_02
Revises: 20260813_01
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_02"
down_revision: str | None = "20260813_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # if_not_exists=True: idempotent — safe to run even if index already exists
    # meter_readings — most queried table
    op.create_index("ix_meter_readings_room_id", "meter_readings", ["room_id"], if_not_exists=True)
    op.create_index("ix_meter_readings_status", "meter_readings", ["status"], if_not_exists=True)
    op.create_index("ix_meter_readings_reading_date", "meter_readings", ["reading_date"], if_not_exists=True)
    op.create_index(
        "ix_meter_readings_room_date_status",
        "meter_readings",
        ["room_id", "reading_date", "status"],
        if_not_exists=True,
    )

    # rooms
    op.create_index("ix_rooms_building_id", "rooms", ["building_id"], if_not_exists=True)
    op.create_index("ix_rooms_is_active", "rooms", ["is_active"], if_not_exists=True)

    # invoices
    op.create_index("ix_invoices_room_id", "invoices", ["room_id"], if_not_exists=True)
    op.create_index("ix_invoices_invoice_month", "invoices", ["invoice_month"], if_not_exists=True)

    # buildings
    op.create_index("ix_buildings_owner_id", "buildings", ["owner_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_buildings_owner_id", "buildings")
    op.drop_index("ix_invoices_invoice_month", "invoices")
    op.drop_index("ix_invoices_room_id", "invoices")
    op.drop_index("ix_rooms_is_active", "rooms")
    op.drop_index("ix_rooms_building_id", "rooms")
    op.drop_index("ix_meter_readings_room_date_status", "meter_readings")
    op.drop_index("ix_meter_readings_reading_date", "meter_readings")
    op.drop_index("ix_meter_readings_status", "meter_readings")
    op.drop_index("ix_meter_readings_room_id", "meter_readings")
