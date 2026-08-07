"""add technician_profile and submitted_by

Revision ID: 20260808_02
Revises: 20260808_01
Create Date: 2026-08-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260808_02"
down_revision = "20260808_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create technician_profiles table
    op.create_table(
        "technician_profiles",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("ktv_name", sa.String(length=200), nullable=False),
        sa.Column("ktv_phone", sa.String(length=50), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )

    # Add submitted_by to meter_readings
    op.add_column(
        "meter_readings", sa.Column("submitted_by", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    # Drop submitted_by from meter_readings
    op.drop_column("meter_readings", "submitted_by")

    # Drop technician_profiles table
    op.drop_table("technician_profiles")
