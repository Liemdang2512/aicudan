import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

from app.db.init_db import _ensure_invoice_unique_constraint


def _legacy_invoice_database():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table(
        "invoices",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("room_id", Integer, nullable=False),
        Column("invoice_month", String(7), nullable=False),
    )
    metadata.create_all(engine)
    return engine


def test_legacy_database_gets_invoice_unique_index():
    engine = _legacy_invoice_database()

    with engine.begin() as connection:
        _ensure_invoice_unique_constraint(connection)

    unique_indexes = [
        index for index in inspect(engine).get_indexes("invoices") if index.get("unique")
    ]
    assert any(
        set(index["column_names"]) == {"room_id", "invoice_month"}
        for index in unique_indexes
    )


def test_legacy_database_with_duplicates_fails_closed():
    engine = _legacy_invoice_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO invoices (id, room_id, invoice_month) "
                "VALUES (1, 10, '2026-08'), (2, 10, '2026-08')"
            )
        )

        with pytest.raises(RuntimeError, match="dữ liệu trùng"):
            _ensure_invoice_unique_constraint(connection)
