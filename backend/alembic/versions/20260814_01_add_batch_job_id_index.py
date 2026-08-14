"""Add index on meter_readings.batch_job_id for faster batch status lookups.

Revision ID: 20260814_01
Revises: 20260813_02
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_01"
down_revision: str | None = "20260813_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # if_not_exists=True: idempotent — safe to run even if index already exists
    op.create_index(
        "ix_meter_readings_batch_job_id",
        "meter_readings",
        ["batch_job_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_meter_readings_batch_job_id", "meter_readings")
