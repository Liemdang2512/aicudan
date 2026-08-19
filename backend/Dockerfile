# syntax=docker/dockerfile:1
# ^ Bật BuildKit — bắt buộc để dùng --mount=type=cache bên dưới

# =============================================================
# Stage 1 — Builder: cài dependencies có C/Rust extension
# =============================================================
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# --mount=type=cache cho apt:
#   /var/cache/apt  → file .deb (~50MB) được cache NGOÀI layer, không commit vào image
#   /var/lib/apt    → package index (~8MB) cũng nằm ngoài layer
#   sharing=locked  → tránh race condition khi build song song
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    libffi-dev \
    libssl-dev \
    libpq-dev

# Copy uv binary từ image chính thức
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy manifest trước để tận dụng Docker layer cache
COPY pyproject.toml uv.lock ./

# --mount=type=cache cho uv: wheel cache nằm ngoài layer → không commit vào image
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# =============================================================
# Aggressive cleanup TRƯỚC KHI copy sang runtime stage:
#
#   __pycache__   → Python tự tạo lại khi import → an toàn xóa     (~10–20 MB)
#   *.pyi         → Type stubs cho IDE/mypy, không cần production   (~10–15 MB)
#   tests/ test/  → Test suites của third-party packages            (~15–25 MB)
#   *.dist-info/  → pip/uv metadata, không cần sau khi install      (~  1–2 MB)
#   docs/ examples/ → Tài liệu & ví dụ trong packages               (~  3–5 MB)
#   share/        → Font data assets (fontTools), không dùng server (~  5–8 MB)
#   *.txt *.rst   → Documentation text files trong packages         (~  2–4 MB)
# =============================================================
RUN \
    # Remove compiled Python cache
    find /app/.venv -type d -name "__pycache__" -print0 | xargs -0 rm -rf; \
    # Remove type stubs (IDE only)
    find /app/.venv -name "*.pyi" -delete; \
    # Remove test suites from third-party packages
    find /app/.venv -type d \( -name "tests" -o -name "test" \) -print0 \
        | xargs -0 rm -rf 2>/dev/null; \
    # Remove entire dist-info directories (pip metadata, not needed at runtime)
    find /app/.venv -maxdepth 5 -type d -name "*.dist-info" -print0 \
        | xargs -0 rm -rf 2>/dev/null; \
    # Remove documentation directories from packages
    find /app/.venv -maxdepth 6 -type d \( -name "docs" -o -name "doc" -o -name "examples" -o -name "example" \) \
        -print0 | xargs -0 rm -rf 2>/dev/null; \
    # Remove share/ directory (fontTools font data, locale files, etc.)
    rm -rf /app/.venv/share; \
    # Remove documentation text files from packages (keep only code)
    find /app/.venv -name "*.txt" -not -name "requirements*.txt" -delete 2>/dev/null; \
    find /app/.venv -name "*.rst" -delete 2>/dev/null; \
    true


# =============================================================
# Stage 2 — Runtime: image gọn, chỉ chứa những gì cần để chạy
# =============================================================
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Runtime chỉ cần shared libs (không cần -dev headers)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    zlib1g \
    libffi8 \
    libssl3 \
    libpq5

# Strip Python stdlib modules không bao giờ cần trong server context:
#
#   idlelib    → Python IDLE GUI editor                 (~2 MB)
#   ensurepip  → Bootstrapper để cài pip               (~4 MB)
#   lib2to3    → Python 2→3 migration tool             (~1 MB)
#   turtle     → Turtle graphics (requires display)    (~0.5 MB)
#   turtledemo → Turtle demo programs                  (~0.5 MB)
#   tkinter    → GUI toolkit (absent in slim, safe)    (~0 MB)
#
# Các module này an toàn xóa vì không có server application nào cần chúng.
# Python sẽ báo ImportError nếu code cố import — nhưng app không làm vậy.
RUN find /usr/local/lib/python3.11 -maxdepth 1 -type d \
        \( -name "idlelib" -o -name "ensurepip" \
        -o -name "lib2to3" -o -name "turtledemo" \) \
        -exec rm -rf {} + 2>/dev/null; \
    find /usr/local/lib/python3.11 -maxdepth 1 -name "turtle.py" -delete 2>/dev/null; \
    true

# Copy .venv đã được làm sạch từ builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code ứng dụng
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Persist data và uploads qua Docker volume
RUN mkdir -p /app/data /app/uploads

# Non-root user — giảm attack surface
RUN useradd -m -u 1001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Chạy migration trước, rồi mới start uvicorn
CMD ["./entrypoint.sh"]
