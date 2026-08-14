---
phase: quick-260814-nr2
plan: "01"
subsystem: backend-api, frontend
tags: [performance, n+1-queries, cache, sqlite-index, react-suspense]
status: complete

dependency_graph:
  requires: []
  provides:
    - ix_meter_readings_batch_job_id index trong SQLite
    - batch_status O(1) room lookup thay O(N)
    - generate_invoices 3 batch queries thay 3N queries
    - Cache-Control: private, max-age=3600 cho ảnh đồng hồ
    - HTTP cache headers cho static assets trong next.config.mjs
    - React.Suspense boundaries cho Step 3 và Step 4 trong workflow
  affects:
    - backend/app/api/v1/readings.py
    - backend/app/api/v1/invoices.py
    - backend/alembic/versions/20260814_01_add_batch_job_id_index.py
    - frontend/next.config.mjs
    - frontend/src/app/(dashboard)/workflow/page.tsx

tech_stack:
  patterns:
    - Pre-fetch + dict map pattern để tránh N+1 trong SQLAlchemy async
    - React.Suspense boundary cho conditional heavy render sections
    - Cache-Control: private cho auth-protected endpoints, public cho static assets

key_files:
  created:
    - backend/alembic/versions/20260814_01_add_batch_job_id_index.py
  modified:
    - backend/app/api/v1/readings.py
    - backend/app/api/v1/invoices.py
    - frontend/next.config.mjs
    - frontend/src/app/(dashboard)/workflow/page.tsx

decisions:
  - "Cache-Control: private (không public) cho ảnh đồng hồ vì endpoint yêu cầu auth Bearer token"
  - "Dùng Python-side deduplication thay DISTINCT ON vì SQLite không support DISTINCT ON"
  - "Ownership check early-exit trong staged endpoints: skip job thay raise 404 để không leak thông tin"
  - "React.Suspense wrap tại component level thay extract component riêng — tránh rủi ro refactor state/closure trong 1464-line monolith"

metrics:
  duration: "~20 phút"
  completed_date: "2026-08-14T10:13:05Z"
  tasks: 5
  commits: 5

actuals:
  tokens: 28000
  tasks: 5
  commits: 5
---

# Phase quick-260814-nr2 Plan 01: Tối ưu N+1 queries, cache headers, DB index — Summary

**One-liner:** Batch pre-fetch với dict maps thay 3N invoice queries, IN clause thay N room queries, ix_meter_readings_batch_job_id index, Cache-Control header cho ảnh auth-protected, React.Suspense cho Step 3+4 workflow.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Alembic migration ix_meter_readings_batch_job_id | 45c3df3 | backend/alembic/versions/20260814_01_add_batch_job_id_index.py |
| 2 | Fix N+1 trong readings.py (3 fixes) | 32e716d | backend/app/api/v1/readings.py |
| 3 | Fix N+1 trong invoices.py + Cache-Control header | 0892a5b | backend/app/api/v1/invoices.py, backend/app/api/v1/readings.py |
| 4 | next.config.mjs HTTP cache headers | 44cc6df | frontend/next.config.mjs |
| 5 | React.Suspense boundaries workflow/page.tsx | e4a0078 | frontend/src/app/(dashboard)/workflow/page.tsx |

## Kết quả verify

1. **Backend compiles:** `python -m py_compile readings.py invoices.py` — OK
2. **DB index:** `PRAGMA index_list('meter_readings')` chứa `ix_meter_readings_batch_job_id` trong `data/app.db`
3. **Cache header:** `get_reading_image` endpoint trả `FileResponse` với `headers={"Cache-Control": "private, max-age=3600"}`
4. **next.config.mjs:** `typeof config.headers === 'function'`, returns 2 rules (images + fonts)
5. **TypeScript:** `npx tsc --noEmit` không có lỗi mới trong workflow/page.tsx
6. **React.Suspense:** `grep -c "Suspense" workflow/page.tsx` = 4 (2 open + 2 close tags)

## Chi tiết thay đổi

### Task 1: Alembic migration

- File: `backend/alembic/versions/20260814_01_add_batch_job_id_index.py`
- revision: `20260814_01`, down_revision: `20260813_02`
- `op.create_index("ix_meter_readings_batch_job_id", "meter_readings", ["batch_job_id"], if_not_exists=True)`
- `alembic upgrade head` thành công trên `data/app.db`

### Task 2: Fix N+1 trong readings.py

**Fix A — process_batch_images:** Move `select(Room).where(building_id, is_active)` ra ngoài vòng lặp ảnh. Từ N queries → 1 query, reuse `building_rooms` list trong mỗi iteration.

**Fix B — batch_status:** Collect `room_ids` từ tất cả readings, query 1 lần với `Room.id.in_(room_ids)`, build `room_map = {room.id: room}`. Trong loop dùng `room_map.get(r.room_id)`. Từ N queries → 1 query.

**Fix C — get_staged_reading_image + approve_staged_reading (security + perf):** Ownership check (`Building.owner_id == current_user.id`) xảy ra TRƯỚC khi scan unmatched items. Nếu building không thuộc user, `continue` ngay — không leak thông tin về job tồn tại. Trước đó: scan unmatched trước, check ownership sau (T-nr2-01, T-nr2-02 từ threat model).

### Task 3: Fix N+1 trong invoices.py + Cache-Control

**generate_invoices:** 3 batch pre-fetch trước `for room in rooms:`:
1. `existing_invoice_map: dict[int, int]` — map room_id → invoice_id
2. `current_reading_map: dict[int, MeterReading]` — latest approved reading per room trong tháng (Python deduplication vì SQLite thiếu DISTINCT ON)
3. `prev_reading_map: dict[int, MeterReading]` — latest approved reading per room trước tháng (chỉ cho rooms có current reading)

Trong loop: thay 3 `await db.execute(...)` bằng `.get()` từ maps. Từ 3N queries → 3 queries.

Xóa import `and_`, `or_` khỏi invoices.py (không còn dùng sau refactor).

**get_reading_image Cache-Control:** `FileResponse(..., headers={"Cache-Control": "private, max-age=3600"})`. `private` vì endpoint yêu cầu Bearer token auth — không cache ở CDN/proxy public.

### Task 4: next.config.mjs cache headers

Thêm `async headers()` vào `nextConfig`:
- `/:path*\.(jpg|jpeg|png|gif|webp|svg|ico)` → `public, max-age=86400, stale-while-revalidate=604800`
- `/:path*\.(woff|woff2|ttf|otf|eot)` → `public, max-age=31536000, immutable`

Giữ nguyên `output`, `poweredByHeader`, `compress`, `webpack`.

### Task 5: React.Suspense boundaries

File workflow/page.tsx là "use client" monolithic component 1464 dòng. Không extract component riêng (rủi ro refactor state/closure cao). Thay vào đó wrap conditional render sections:

- Step 3 (`currentStep === 3`): wrap `<Card>` bằng `<React.Suspense fallback={<div className="h-32 animate-pulse bg-muted rounded-lg" />}>`
- Step 4 (`currentStep === 4`): wrap tương tự

Không thay đổi logic, state, polling, hay API calls.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Cleanup] Xóa orphan imports `and_`, `or_` khỏi invoices.py**
- **Found during:** Task 3
- **Issue:** Sau khi refactor bỏ `prev_result` query inline với `or_/and_`, imports `and_` và `or_` không còn được dùng
- **Fix:** Xóa khỏi `from sqlalchemy import and_, or_, select` → `from sqlalchemy import select`
- **Files modified:** backend/app/api/v1/invoices.py
- **Commit:** 0892a5b

**2. [Rule 1 - Security Improvement] Ownership check trước khi scan trong get_staged_reading_image**
- **Found during:** Task 2 (áp dụng threat model T-nr2-01)
- **Issue:** Logic cũ: scan unmatched items → tìm staged_id match → RỒII MỚI check ownership. Nếu staged_id match nhưng job thuộc user khác → raise 404 (leak: confirm staged_id tồn tại)
- **Fix:** Move ownership check lên đầu loop, `continue` thay `raise HTTPException` khi building không thuộc user
- **Files modified:** backend/app/api/v1/readings.py
- **Commit:** 32e716d

## Known Stubs

Không có stubs trong plan này. Tất cả changes là functional improvements không tạo placeholder data.

## Self-Check: PASSED

- backend/alembic/versions/20260814_01_add_batch_job_id_index.py: FOUND
- backend/app/api/v1/readings.py: FOUND, compiles OK
- backend/app/api/v1/invoices.py: FOUND, compiles OK
- frontend/next.config.mjs: FOUND, headers() function verified
- frontend/src/app/(dashboard)/workflow/page.tsx: FOUND, 4x Suspense, TypeScript OK
- Commits: 45c3df3, 32e716d, 0892a5b, 44cc6df, e4a0078 — all exist in git log
