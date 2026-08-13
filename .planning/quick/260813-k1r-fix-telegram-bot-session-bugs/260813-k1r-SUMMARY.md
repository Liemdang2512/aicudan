---
quick_id: 260813-k1r
slug: fix-telegram-bot-session-bugs
status: complete
date: 2026-08-13
commit: 67d1720
---

# Summary: Fix 5 bugs in Telegram bot files

## Changes

| File | Change |
|------|--------|
| `backend/app/models/bot_session.py` | Thêm `bot_type` vào composite PK `(chat_id, bot_type)` |
| `backend/app/api/v1/telegram_bot.py` | `_get_session` filter `bot_type="manager"`; fix `_cmd_huy` message; update docstring |
| `backend/app/api/v1/telegram_bot_ktv.py` | `_get_ktv_session` filter `bot_type="ktv"`; thêm secret token validation webhook |
| `backend/app/core/config.py` | Thêm `TELEGRAM_KTV_WEBHOOK_SECRET` setting |
| `backend/tests/test_telegram_ktv_bot.py` | Fix mock `_notify_manager` signature (3 → 4 params) |

## Verification

- 10/10 tests PASSED (`test_telegram_ktv_bot.py` + `test_telegram_manager_bot.py`)
- Commit: `67d1720`

## Notes

- Production DB cần thêm column: `ALTER TABLE bot_sessions ADD COLUMN bot_type VARCHAR(20) DEFAULT 'manager'`
- Alembic migration nên được tạo nếu dùng production DB có data cũ
