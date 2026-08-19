#!/bin/sh
# entrypoint.sh — check DB state, run migration if needed, start server
set -e

echo "[startup] Checking database state..."

# Check if alembic_version table exists (indicates DB already initialized)
HAS_ALEMBIC=$(python3 -c "
import asyncio, os, sys

async def check():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        engine = create_async_engine(os.environ.get('DATABASE_URL', ''))
        async with engine.connect() as conn:
            result = await conn.execute(text(
                \"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'alembic_version'\"
            ))
            count = result.scalar()
            return count > 0
    except Exception as e:
        print(f'DB check error: {e}', file=sys.stderr)
        return False

result = asyncio.run(check())
print('yes' if result else 'no')
" 2>/dev/null || echo "no")

if [ "$HAS_ALEMBIC" = "yes" ]; then
    echo "[startup] Existing DB — running alembic upgrade head..."
    alembic upgrade head
else
    echo "[startup] Fresh DB — skipping alembic (app startup will init schema + stamp)"
fi

echo "[startup] Starting application server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
