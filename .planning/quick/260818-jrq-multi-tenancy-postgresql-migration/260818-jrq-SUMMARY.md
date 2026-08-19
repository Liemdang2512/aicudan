---
phase: quick-260818-jrq
status: complete
---

# Multi-tenancy PostgreSQL Migration — Summary

## Objective
Migrate từ SQLite sang PostgreSQL, thêm per-owner app_settings, và per-tenant KTV Telegram webhook routing.

## Changes

### Task 1: PostgreSQL migration + schema
- `backend/pyproject.toml` — thêm `asyncpg>=0.29.0`
- `backend/app/core/config.py` — DATABASE_URL default đổi sang postgresql+asyncpg
- `docker-compose.yml` — thêm postgres service, depends_on, DATABASE_URL env, bỏ backend_data volume
- `backend/Dockerfile` — thêm libpq-dev (builder) và libpq5 (runtime)
- `backend/entrypoint.sh` — bỏ SQLite logic, luôn chạy `alembic upgrade head`
- `backend/app/models/app_setting.py` — thêm `owner_id` FK → users, unique constraint
- `backend/app/models/bot_session.py` — thêm `owner_id` nullable FK → users
- `backend/app/models/technician_profile.py` — thêm `owner_id` FK → users
- `backend/alembic/versions/20260818_02_multi_tenancy_postgresql.py` — migration: add owner_id columns, data migration, NOT NULL constraints
- `backend/alembic/env.py` — thêm app_setting và technician_profile imports

### Task 2: Per-owner app_settings
- `backend/app/db/init_db.py` — `_ensure_app_settings(db, owner_id)`, `load_settings_from_db(db, owner_id)`, `seed_data` flush trước khi commit để lấy admin.id
- `backend/app/api/v1/app_settings.py` — `_get_or_create_setting(db, owner_id)`, setup-ktv-webhook URL dùng `/ktv/webhook/{owner_id}`
- `backend/app/main.py` — `_hydrate_settings_from_db` load từ first non-admin owner, `_auto_register_webhooks` iterate all owners với KTV token

### Task 3: Per-tenant KTV webhook
- `backend/app/api/v1/telegram_bot_ktv.py` — full refactor:
  - `OwnerContext` dataclass (owner_id, ktv_bot_token, ktv_password, manager_bot_token, manager_chat_id)
  - Webhook endpoint `/ktv/webhook/{owner_id}` với owner validation
  - `_ktv_dispatch(update, owner_id)` load AppSetting → OwnerContext
  - All API calls pass `token` explicitly thay vì dùng `settings.*`
  - Building/Room queries filter theo `Building.owner_id == owner_id`
  - `_get_ktv_session` và `_save_profile` store owner_id

## Verification
- ✅ AppSetting.owner_id exists
- ✅ BotSession.owner_id exists
- ✅ TechnicianProfile.owner_id exists
- ✅ `_get_or_create_setting` accepts owner_id
- ✅ KTV webhook route: `/telegram/ktv/webhook/{owner_id}`
- ✅ `_ktv_dispatch` accepts owner_id
- ✅ All modules import cleanly

## Security
- T-jrq-01: Webhook validates owner_id exists + has KTV token, returns 404 if not
- T-jrq-02: All Building/Room queries filter by owner_id from URL
- T-jrq-03: PATCH /settings scoped to current_user.id
- T-jrq-04: KTV còn phải authenticate với owner-specific password
