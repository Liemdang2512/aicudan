---
phase: quick-260818-jrq
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: true
files_modified:
  # Task 1 — PostgreSQL + Schema
  - backend/pyproject.toml
  - backend/docker-compose.yml  # actually project root
  - docker-compose.yml
  - backend/app/core/config.py
  - backend/app/db/session.py
  - backend/app/models/app_setting.py
  - backend/app/models/bot_session.py
  - backend/app/models/technician_profile.py
  - backend/alembic/versions/20260818_02_multi_tenancy_postgresql.py
  - backend/alembic/env.py
  - backend/entrypoint.sh
  - backend/Dockerfile
  # Task 2 — App settings per-tenant + init_db
  - backend/app/db/init_db.py
  - backend/app/api/v1/app_settings.py
  - backend/app/main.py
  # Task 3 — KTV webhook per-tenant
  - backend/app/api/v1/telegram_bot_ktv.py
  - backend/app/api/v1/router.py

estimate:
  tokens: 80000
  raw_tokens: 40000
  tasks: 3
  confidence: med

must_haves:
  truths:
    - "DATABASE_URL uses postgresql+asyncpg driver and connects to PostgreSQL container"
    - "app_settings has owner_id FK to users, unique constraint on owner_id"
    - "bot_sessions has owner_id column (nullable, for KTV sessions)"
    - "technician_profiles has owner_id column linking KTV to specific owner"
    - "KTV webhook endpoint accepts owner_id path param: /telegram/ktv/webhook/{owner_id}"
    - "Startup auto-registers KTV webhook per owner who has ktv_bot_token configured"
    - "Existing data migrated to first non-admin owner"
    - "All existing owner_id filtering in buildings/rooms/readings/invoices/price_configs continues working"
  artifacts:
    - backend/alembic/versions/20260818_02_multi_tenancy_postgresql.py
    - docker-compose.yml (with postgres service)
  key_links:
    - "AppSetting.owner_id -> User.id (each owner has own settings)"
    - "BotSession.owner_id -> User.id (KTV sessions scoped to owner)"
    - "TechnicianProfile.owner_id -> User.id (KTV belongs to owner)"
    - "KTV webhook {owner_id} -> loads that owner's AppSetting for bot token + password"
---

<objective>
Multi-tenancy migration: SQLite to PostgreSQL, per-owner app_settings, and per-tenant KTV Telegram webhook routing.

Purpose: Enable multiple landlords (owners) to use the same system with completely isolated data. Each owner has their own settings (API keys, bot tokens), and KTV bots route to the correct owner via webhook URL path parameter.

Output: Working PostgreSQL-backed multi-tenant system with per-owner settings, per-tenant KTV webhook, and data migration.
</objective>

<execution_context>
@/Users/tanliem/.claude/gsd-core/workflows/execute-plan.md
@/Users/tanliem/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@docker-compose.yml
@backend/app/core/config.py
@backend/app/db/session.py
@backend/app/models/app_setting.py
@backend/app/models/bot_session.py
@backend/app/models/technician_profile.py
@backend/app/models/user.py
@backend/app/models/building.py
@backend/app/db/init_db.py
@backend/app/main.py
@backend/app/api/v1/app_settings.py
@backend/app/api/v1/telegram_bot_ktv.py
@backend/app/api/v1/router.py
@backend/alembic/env.py
@backend/entrypoint.sh
@backend/Dockerfile
@backend/pyproject.toml
</context>

<tasks>

<task type="tracer">
  <name>Task 1: PostgreSQL migration + schema changes (models, migration, docker, config)</name>
  <files>
    docker-compose.yml,
    backend/pyproject.toml,
    backend/app/core/config.py,
    backend/app/db/session.py,
    backend/app/models/app_setting.py,
    backend/app/models/bot_session.py,
    backend/app/models/technician_profile.py,
    backend/alembic/versions/20260818_02_multi_tenancy_postgresql.py,
    backend/alembic/env.py,
    backend/entrypoint.sh,
    backend/Dockerfile
  </files>
  <action>
    1. ADD asyncpg dependency to pyproject.toml dependencies list (keep aiosqlite for backward compat).

    2. CHANGE config.py DATABASE_URL default from "sqlite+aiosqlite:///./data/app.db" to "postgresql+asyncpg://aicudan:aicudan@localhost:5432/aicudan". This is the dev default; production overrides via env.

    3. CHANGE docker-compose.yml:
       - Add postgres service before backend:
         image: postgres:16-alpine, container_name: aicudan-postgres, restart: unless-stopped,
         environment: POSTGRES_DB=aicudan, POSTGRES_USER=aicudan, POSTGRES_PASSWORD=aicudan,
         volumes: postgres_data:/var/lib/postgresql/data, networks: aicudan-net,
         healthcheck: pg_isready -U aicudan
       - Add backend depends_on: postgres (condition: service_healthy)
       - Add backend environment: DATABASE_URL=postgresql+asyncpg://aicudan:aicudan@postgres:5432/aicudan
       - Add postgres_data to volumes section
       - Remove backend_data volume (no more SQLite file)

    4. CHANGE Dockerfile: add libpq-dev in builder stage build deps, add libpq5 in runtime stage. These are required for asyncpg.

    5. CHANGE entrypoint.sh: Remove all SQLite-specific logic (DB_PATH check, sqlite3 python check, HAS_ALEMBIC detection). Replace with: wait for postgres to be ready (pg_isready loop or simple retry), then always run "alembic upgrade head", then exec uvicorn. The stamp-if-fresh logic in main.py handles new DBs.

    6. CHANGE app_setting.py model:
       - Remove "id" column (primary key default=1 pattern).
       - Add "id" as autoincrement Integer primary key.
       - Add "owner_id" column: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True).
       - Keep all other columns the same.

    7. CHANGE bot_session.py model:
       - Add "owner_id" column: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True).
       - This is nullable because manager bot sessions may not be owner-scoped.

    8. CHANGE technician_profile.py model:
       - Add "owner_id" column: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default=0).
       - Default=0 is temporary for migration; migration script will set real owner_id.

    9. CREATE alembic migration 20260818_02_multi_tenancy_postgresql.py:
       - This migration runs on PostgreSQL (the fresh DB after switch).
       - op.add_column("app_settings", sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
       - op.create_unique_constraint("uq_app_settings_owner_id", "app_settings", ["owner_id"])
       - op.add_column("bot_sessions", sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
       - op.add_column("technician_profiles", sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True))
       - Data migration: find first non-admin user (role != 'admin' or if none, use first user). UPDATE app_settings SET owner_id = that_user_id. UPDATE technician_profiles SET owner_id = that_user_id. UPDATE bot_sessions SET owner_id = that_user_id WHERE bot_type = 'ktv'.
       - After data migration: ALTER app_settings ALTER COLUMN owner_id SET NOT NULL. ALTER technician_profiles ALTER COLUMN owner_id SET NOT NULL.
       - Make migration idempotent: check if columns exist before adding.

    10. CHANGE alembic/env.py: add import for app_setting and technician_profile models to ensure they are registered with Base.metadata (app_setting import may already be handled via init_db but alembic env should be explicit).

    11. CHANGE db/session.py: The engine creation stays the same (it reads DATABASE_URL from settings). No changes needed unless connect_args for SQLite were set. Currently no connect_args, so no change needed.
  </action>
  <verify>
    <automated>cd backend && python -c "from app.core.config import settings; assert 'postgresql' in settings.DATABASE_URL or 'sqlite' in settings.DATABASE_URL; print('Config OK:', settings.DATABASE_URL[:40])"</automated>
    <automated>cd backend && python -c "from app.models.app_setting import AppSetting; assert hasattr(AppSetting, 'owner_id'); print('AppSetting.owner_id exists')"</automated>
    <automated>cd backend && python -c "from app.models.bot_session import BotSession; assert hasattr(BotSession, 'owner_id'); print('BotSession.owner_id exists')"</automated>
    <automated>cd backend && python -c "from app.models.technician_profile import TechnicianProfile; assert hasattr(TechnicianProfile, 'owner_id'); print('TechnicianProfile.owner_id exists')"</automated>
  </verify>
  <done>
    - DATABASE_URL default is postgresql+asyncpg
    - docker-compose.yml has postgres service, backend depends on it, DATABASE_URL env var set
    - Dockerfile has libpq dependencies
    - entrypoint.sh has no SQLite logic, always runs alembic upgrade head
    - AppSetting model has owner_id (unique, FK to users)
    - BotSession model has owner_id (nullable, FK to users)
    - TechnicianProfile model has owner_id (FK to users)
    - Alembic migration adds columns and migrates existing data
    - asyncpg in pyproject.toml
  </done>
</task>

<task type="auto">
  <name>Task 2: Per-owner app_settings in init_db, settings hydration, and API endpoints</name>
  <files>
    backend/app/db/init_db.py,
    backend/app/api/v1/app_settings.py,
    backend/app/main.py
  </files>
  <action>
    1. CHANGE init_db.py:
       - _ensure_app_settings: Instead of looking up AppSetting by id=1, look up by owner_id. Accept owner_id parameter. The function should find or create AppSetting for a specific owner.
       - seed_data: After creating admin user, also create an AppSetting for that admin with owner_id=admin.id seeded from env vars.
       - load_settings_from_db: This function currently loads global settings. Change it to accept owner_id and load settings for that specific owner. For backward compat during startup, load settings for the first owner found (or admin).
       - _hydrate_settings_from_db in main.py: Change to load settings from the first owner's AppSetting (not id=1). Query: select(AppSetting).join(User).order_by(User.id).limit(1). This is a transitional approach; eventually each request will load per-owner settings.

    2. CHANGE app_settings.py API:
       - _get_or_create_setting(db, owner_id): Change parameter from nothing to accepting owner_id. Query by AppSetting.owner_id == owner_id instead of AppSetting.id == 1. When creating, set owner_id=owner_id.
       - GET /settings: Pass current_user.id as owner_id to _get_or_create_setting.
       - PATCH /settings: Pass current_user.id as owner_id. When syncing to runtime settings, only update if current_user is the "active" owner (for now, always update since single-server).
       - POST /settings/setup-webhook: Load token from the current_user's AppSetting (not global). The webhook URL for manager bot stays /api/v1/telegram/webhook (not per-tenant for manager bot).
       - POST /settings/setup-ktv-webhook: Load token from current_user's AppSetting. The webhook URL should now be /api/v1/telegram/ktv/webhook/{current_user.id} (per-tenant).
       - POST /settings/validate: Use current_user's AppSetting.

    3. CHANGE main.py _hydrate_settings_from_db:
       - Query AppSetting joined with User, get first non-admin owner's settings (or first user if all admin).
       - Hydrate runtime settings from that owner's AppSetting row.
       - This is transitional; multi-tenant requests will load per-request.

    4. CHANGE main.py _auto_register_webhooks:
       - Instead of using global settings.TELEGRAM_KTV_BOT_TOKEN, iterate all AppSetting rows that have a non-empty telegram_ktv_bot_token.
       - For each, register webhook at /api/v1/telegram/ktv/webhook/{owner_id}.
       - For manager bot: still use global settings.TELEGRAM_BOT_TOKEN for the single manager webhook (or iterate owners with manager bot tokens if needed).
  </action>
  <verify>
    <automated>cd backend && python -c "
from app.db.init_db import _ensure_app_settings, seed_data
import inspect
sig = inspect.signature(_ensure_app_settings)
params = list(sig.parameters.keys())
print('_ensure_app_settings params:', params)
# Should not have hardcoded id=1 in the function
source = inspect.getsource(_ensure_app_settings)
assert 'id == 1' not in source or 'owner_id' in source, 'Should use owner_id not id=1'
print('init_db OK')
"</automated>
    <automated>cd backend && python -c "
from app.api.v1.app_settings import _get_or_create_setting
import inspect
sig = inspect.signature(_get_or_create_setting)
params = list(sig.parameters.keys())
assert 'owner_id' in params, f'Expected owner_id param, got {params}'
print('app_settings API OK: params =', params)
"</automated>
  </verify>
  <done>
    - _ensure_app_settings creates per-owner settings row, not global id=1
    - GET/PATCH /settings loads current_user's own AppSetting
    - setup-ktv-webhook generates per-tenant URL: /api/v1/telegram/ktv/webhook/{owner_id}
    - Startup hydrates settings from first owner and registers webhooks per-tenant
    - seed_data creates AppSetting for admin user with owner_id
  </done>
</task>

<task type="auto">
  <name>Task 3: Per-tenant KTV webhook routing with owner_id path param</name>
  <files>
    backend/app/api/v1/telegram_bot_ktv.py,
    backend/app/api/v1/router.py
  </files>
  <action>
    1. CHANGE telegram_bot_ktv.py webhook endpoint:
       - Change route from @router.post("/ktv/webhook") to @router.post("/ktv/webhook/{owner_id}").
       - Add owner_id: int path parameter.
       - In the endpoint function: load AppSetting for that owner_id from DB. If not found or no ktv bot token configured, return 404.
       - Pass owner_id into _ktv_dispatch so all downstream functions know which owner's context they operate in.

    2. CHANGE _ktv_dispatch signature to accept owner_id: int parameter.
       - At the start of _ktv_dispatch, load the owner's AppSetting to get telegram_ktv_bot_token and telegram_ktv_password for this owner.
       - Store owner context in a module-level or pass through function chain.

    3. CHANGE _ktv_token() and _ktv_api() to accept or use owner's token:
       - Approach: pass owner_id through the dispatch chain. In _ktv_dispatch, after loading AppSetting, store token in a contextvars.ContextVar or pass explicitly.
       - Recommended: Create a dataclass OwnerContext(owner_id, ktv_bot_token, ktv_password, manager_bot_token, manager_chat_id) and pass it through all handler functions.
       - _ktv_token() becomes owner_ctx.ktv_bot_token.
       - _ktv_api() uses the owner context token.
       - _manager_api() uses owner context manager_bot_token.

    4. CHANGE _cmd_ktv_auth to verify password against owner's telegram_ktv_password (from OwnerContext), not global settings.TELEGRAM_KTV_PASSWORD.

    5. CHANGE _cmd_ktv_baodien: When querying buildings, filter by Building.owner_id == owner_id (the owner whose webhook was called). This ensures KTV only sees buildings belonging to their assigned owner.

    6. CHANGE _get_ktv_session: Add owner_id parameter. When creating new BotSession, set owner_id. When querying, filter by owner_id to allow same chat_id to work with different owners.
       - Update BotSession primary key consideration: currently (chat_id, bot_type) is PK. For multi-tenant, a KTV might work for multiple owners. Add owner_id to the composite key or use a surrogate key. Recommended: keep (chat_id, bot_type) as PK but add owner_id column. If same KTV works for multiple owners, they need separate /ktv commands per owner bot. Since each owner has a separate Telegram bot, the chat_id is unique per bot anyway.
       - Actually, since each owner has a DIFFERENT Telegram bot, the same human KTV would have different chat_ids with different bots. So (chat_id, bot_type) PK still works. Just store owner_id for reference.

    7. CHANGE _save_profile: Add owner_id parameter. Set TechnicianProfile.owner_id when creating.

    8. CHANGE _notify_manager: Use owner context's manager_telegram_chat_id and manager bot token instead of global settings.

    9. CHANGE _handle_ktv_edit_room_input and photo processor: When querying rooms, add Building.owner_id == owner_id filter to room lookups (join Room -> Building where Building.owner_id == owner_id). This prevents cross-tenant room matching.

    10. No changes needed to router.py - the route prefix /telegram already covers it, and the path param {owner_id} is in the route decorator.
  </action>
  <verify>
    <automated>cd backend && python -c "
from app.api.v1.telegram_bot_ktv import router
routes = [r.path for r in router.routes]
print('KTV routes:', routes)
assert any('{owner_id}' in r for r in routes), f'Expected owner_id path param in routes: {routes}'
print('Per-tenant webhook route OK')
"</automated>
    <automated>cd backend && python -c "
import inspect
from app.api.v1.telegram_bot_ktv import _ktv_dispatch
sig = inspect.signature(_ktv_dispatch)
params = list(sig.parameters.keys())
assert 'owner_id' in params, f'Expected owner_id in _ktv_dispatch params: {params}'
print('_ktv_dispatch accepts owner_id OK')
"</automated>
  </verify>
  <done>
    - KTV webhook route is /api/v1/telegram/ktv/webhook/{owner_id}
    - Each webhook call loads owner's AppSetting for bot token and password
    - KTV auth verifies against owner-specific password
    - Building queries in KTV flow filter by owner_id
    - Room queries in KTV flow join through Building.owner_id
    - BotSession and TechnicianProfile store owner_id
    - Manager notifications use owner-specific chat_id and bot token
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| webhook URL -> backend | owner_id in URL is untrusted input; must validate owner exists and has KTV configured |
| tenant isolation | Each owner must only see/modify their own data |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation |
|-----------|----------|-----------|----------|-------------|------------|
| T-jrq-01 | Spoofing | /ktv/webhook/{owner_id} | medium | mitigate | Validate owner_id exists in DB, has active KTV token; return 404 for invalid |
| T-jrq-02 | Information Disclosure | Cross-tenant data | high | mitigate | All KTV queries (buildings, rooms) filter by owner_id from URL path, not user input |
| T-jrq-03 | Tampering | AppSetting PATCH | medium | mitigate | require_admin + current_user.id scopes writes to own settings only |
| T-jrq-04 | Elevation of Privilege | owner_id manipulation | medium | mitigate | webhook owner_id only determines which tenant context to load; KTV still must authenticate with that tenant's password |
</threat_model>

<verification>
1. Docker compose up with PostgreSQL connects successfully
2. Alembic migration runs clean on fresh PostgreSQL
3. AppSetting created per-owner, not global id=1
4. KTV webhook at /ktv/webhook/{owner_id} loads correct owner context
5. KTV auth uses owner-specific password
6. Building/room queries in KTV scoped to owner
7. Startup registers webhooks for all owners with KTV tokens
</verification>

<success_criteria>
- PostgreSQL is the database backend (asyncpg driver)
- Each owner has isolated app_settings
- KTV Telegram webhook routes per owner_id
- Existing owner_id filtering on buildings/rooms/readings/invoices/price_configs unaffected
- Data migration assigns existing records to first non-admin owner
- System starts up and registers per-tenant webhooks
</success_criteria>

<output>
Create `.planning/quick/260818-jrq-multi-tenancy-postgresql-migration/260818-jrq-SUMMARY.md` when done
</output>
