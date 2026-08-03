"""Enforce one invoice per room and invoice month.

Revision ID: 20260801_01
Revises: None
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT room_id, invoice_month, COUNT(*) AS duplicate_count
            FROM invoices
            GROUP BY room_id, invoice_month
            HAVING COUNT(*) > 1
            ORDER BY room_id, invoice_month
            LIMIT 20
            """
        )
    ).mappings().all()
    if duplicates:
        details = ", ".join(
            f"room_id={row['room_id']} month={row['invoice_month']} count={row['duplicate_count']}"
            for row in duplicates
        )
        raise RuntimeError(
            "Không thể tạo unique constraint vì có hóa đơn trùng. "
            f"Hãy đối soát và xử lý thủ công trước khi chạy lại migration: {details}"
        )

    with op.batch_alter_table("invoices") as batch_op:
        batch_op.create_unique_constraint(
            "uq_invoices_room_month",
            ["room_id", "invoice_month"],
        )


def downgrade() -> None:
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_constraint("uq_invoices_room_month", type_="unique")
