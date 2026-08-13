#!/bin/sh
# entrypoint.sh — chạy migration trước, rồi mới start server
set -e

DB_PATH="/app/data/app.db"

echo "[startup] Checking database state..."

if [ -f "$DB_PATH" ]; then
    # DB tồn tại — kiểm tra có alembic_version chưa
    HAS_ALEMBIC=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
result = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'\").fetchone()
conn.close()
print('yes' if result else 'no')
" 2>/dev/null || echo "unknown")

    if [ "$HAS_ALEMBIC" = "no" ]; then
        echo "[startup] Legacy DB (no alembic_version) detected. Stamping to 20260808_03..."
        alembic stamp 20260808_03
    fi

    echo "[startup] Running database migrations..."
    alembic upgrade head
else
    echo "[startup] Fresh install — skipping alembic (schema will be created on first run)"
fi

echo "[startup] Starting application server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
