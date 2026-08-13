#!/bin/sh
# entrypoint.sh — chạy migration trước, rồi mới start server
set -e

echo "[startup] Running database migrations..."
alembic upgrade head

echo "[startup] Starting application server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
