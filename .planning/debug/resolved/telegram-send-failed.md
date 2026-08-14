---
status: resolved
slug: telegram-send-failed
trigger: "Gửi Telegram thất bại: 0 thành công, 3 thất bại cho rooms B 2543, B 3491, B 3925"
created: 2026-08-14
updated: 2026-08-14
---

## Symptoms

- expected: 3 hóa đơn gửi Telegram thành công
- actual: 0 thành công, 3 thất bại (rooms B 2543, B 3491, B 3925 đều badge "Gửi lỗi")
- error_messages: UI shows "Gửi hoàn tất: 0 thành công, 3 thất bại". No detailed reason shown.
- timeline: Xảy ra khi user test tính năng gửi thông báo Telegram
- reproduction: Upload ảnh đồng hồ → xác nhận duyệt → chọn gửi Telegram → 0 success 3 failed

## Evidence

- timestamp: 2026-08-14T09:44
  finding: Room B 3491 has telegram_id='' (empty string) in DB
  source: docker exec query

- timestamp: 2026-08-14T09:44
  finding: Room B 3925 has telegram_id='' (empty string) in DB
  source: docker exec query

- timestamp: 2026-08-14T09:44
  finding: Room B 2543 has telegram_id='5421019219' (non-empty) but still failed
  source: docker exec query

- timestamp: 2026-08-14T09:44
  finding: TELEGRAM_BOT_TOKEN is configured (not empty)
  source: docker exec query

- timestamp: 2026-08-14T09:44
  finding: Backend logs show only health checks, no Telegram errors logged
  source: docker compose logs backend

- timestamp: 2026-08-14T09:44
  finding: notification_service.py line 100 only logs "Telegram message delivery failed" without actual error detail (no error_code, no description from Telegram API response)
  source: code review

- timestamp: 2026-08-14T09:44
  finding: No batch_jobs rows found in local DB for job_type=notification — test may have been on different env
  source: docker exec query

- timestamp: 2026-08-14T16:48
  finding: Telegram API returns 401 Unauthorized for chat_id=5421019219 when using settings.TELEGRAM_BOT_TOKEN (first 10 chars 8660903278)
  source: direct httpx test in container

- timestamp: 2026-08-14T16:49
  finding: app_settings DB has telegram_bot_token (first 10 chars 8620977034) — different from .env token
  source: docker exec query app_settings

- timestamp: 2026-08-14T16:52
  finding: DB token (8620977034...) passes getMe — username=Baocaodiencudan_bot — valid token
  source: httpx getMe call with DB token

- timestamp: 2026-08-14T16:52
  finding: .env token (8660903278...) fails getMe with 401 Unauthorized — invalid/revoked token
  source: httpx getMe call with settings.TELEGRAM_BOT_TOKEN

- timestamp: 2026-08-14T16:52
  finding: main.py lifespan has no DB hydration — on container restart settings.TELEGRAM_BOT_TOKEN reverts to .env value (invalid), discarding the valid token saved via UI settings page
  source: code review app/main.py

## Eliminated

- TELEGRAM_BOT_TOKEN not configured at all — eliminated (token exists but wrong)
- Network connectivity — eliminated (getMe call reaches Telegram API)
- Bug in send_telegram_message HTTP logic — eliminated (logic correct, token is the problem)

## Current Focus

hypothesis: "Two root causes confirmed: (1) B 3491/B 3925 — empty telegram_id string caught by not room.telegram_id check → missing_telegram_id (user must register via bot). (2) B 2543 — valid telegram_id but container restart caused settings.TELEGRAM_BOT_TOKEN to revert to revoked .env token instead of valid DB token; Telegram returns 401 Unauthorized."
test: "Fix applied: (1) _hydrate_settings_from_db() added to main.py lifespan; (2) notification_service.py now logs error_code+description on not-ok response"
expecting: "After rebuild+restart: settings.TELEGRAM_BOT_TOKEN loaded from DB (valid token) → B 2543 sends successfully. B 3491/B 3925 still fail with missing_telegram_id until users start bot."
next_action: "DONE"
reasoning_checkpoint: "Root cause confirmed by: DB has valid token via getMe, .env has revoked token, no startup hydration existed."

## Resolution

root_cause: "Token mismatch on container restart: (1) valid TELEGRAM_BOT_TOKEN saved in app_settings DB via UI was not reloaded into settings object on restart — lifespan lacked DB hydration, so .env token (401 Unauthorized) was used instead; (2) rooms B 3491/B 3925 have empty telegram_id — residents have not /start the bot."
fix: "Added _hydrate_settings_from_db() to main.py lifespan (after seed_data) — reads app_settings row on startup and applies all stored credentials to settings.* and os.environ; also improved notification_service.py to log Telegram API error_code+description on not-ok response and exc_info=True on exceptions."
verification: "Rebuilt image, restarted container. DB SELECT for app_settings visible in startup logs. DB token validated via getMe → ok=True username=Baocaodiencudan_bot. Token mismatch resolved structurally."
files_changed:
  - backend/app/main.py (added _hydrate_settings_from_db, called in lifespan)
  - backend/app/services/notification_service.py (improved error logging)
