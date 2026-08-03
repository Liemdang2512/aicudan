# syntax=docker/dockerfile:1
# ^ Bật BuildKit — bắt buộc để dùng --mount=type=cache bên dưới

# =============================================================
# Stage 1 — Builder: cài dependencies có C/Rust extension
# =============================================================
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# [OPT-1] --mount=type=cache cho apt:
#   /var/cache/apt  → file .deb (~50MB) được cache NGOÀI layer, không commit vào image
#   /var/lib/apt    → package index (~8MB) cũng nằm ngoài layer
#   sharing=locked  → tránh race condition khi build song song
# → Không cần "rm -rf /var/lib/apt/lists/*" vì lists đã nằm ngoài layer
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    libffi-dev \
    libssl-dev

# Copy uv binary từ image chính thức (project đã dùng uv — có uv.lock)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy manifest trước để tận dụng Docker layer cache:
# deps chỉ rebuild khi pyproject.toml hoặc uv.lock thay đổi
COPY pyproject.toml uv.lock ./

# [OPT-2] --mount=type=cache cho uv download cache:
#   Lần build đầu: uv download wheels bình thường (~200MB bandwidth)
#   Lần rebuild:   uv đọc từ cache host → nhanh hơn ~5x, không cần internet
#   Cache KHÔNG được commit vào image → final image không bị phình
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# [OPT-3] Xóa các file không cần thiết ở runtime TRƯỚC KHI copy sang stage 2:
#
#   __pycache__/  → Python tự tạo lại khi import lần đầu → an toàn xóa
#                    Tiết kiệm ~10–20MB
#
#   *.pyi         → Type stubs cho IDE/mypy, không cần khi chạy production
#                    Tiết kiệm ~10–15MB (pydantic, sqlalchemy, google-genai đều ship .pyi)
#
#   tests/ test/  → Test suites của third-party packages (Pillow, cryptography...)
#                    Không bao giờ chạy trong container → xóa an toàn
#                    Tiết kiệm ~15–25MB
#
#   RECORD        → File inventory của pip/uv, chỉ cần khi uninstall package
#                    Tiết kiệm ~2–3MB
#
RUN find /app/.venv -type d -name "__pycache__" -print0 | xargs -0 rm -rf; \
    find /app/.venv -name "*.pyi" -delete; \
    find /app/.venv -type d -name "tests" -print0 | xargs -0 rm -rf 2>/dev/null; \
    find /app/.venv -type d -name "test" -print0 | xargs -0 rm -rf 2>/dev/null; \
    find /app/.venv -path "*dist-info/RECORD" -delete; \
    true


# =============================================================
# Stage 2 — Runtime: image gọn, chỉ chứa những gì cần để chạy
# =============================================================
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# [OPT-1] Dùng cache mount cho runtime apt:
#   Runtime chỉ cần shared libs (~1–2MB .deb)
#   Nhưng package index (~8MB) sẽ nằm ngoài layer thay vì phải rm -rf sau
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    zlib1g \
    libffi8 \
    libssl3

# Copy .venv đã được làm sạch từ builder
# Kết quả: chỉ có Python source + compiled extensions, không có stubs/tests/cache
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code ứng dụng
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Mount volume vào đây ở runtime để persist data
RUN mkdir -p /app/data /app/uploads

# Non-root user — giảm attack surface
RUN useradd -m -u 1001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 1 worker vì SQLite không hỗ trợ multi-writer an toàn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
