# syntax=docker/dockerfile:1
# ^ Bật BuildKit — bắt buộc để dùng --mount=type=cache bên dưới

# =============================================================
# Stage 1 — Builder: cài deps và build Next.js production bundle
# =============================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Tắt telemetry ngay từ builder — tránh gọi network không cần thiết
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./

# --mount=type=cache cho npm:
#   /root/.npm → cache ~300MB packages NGOÀI layer, không commit vào image
#   --prefer-offline: ưu tiên cache, chỉ download khi thực sự thiếu
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline

COPY . .

# NEXT_PUBLIC_API_URL là build-time var: Next.js embed vào JS bundle lúc compile
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# =============================================================
# Aggressive cleanup standalone/node_modules TRƯỚC KHI copy sang runtime:
#
#   *.d.ts      → TypeScript declarations (IDE/tsc only)   (~8–12 MB)
#   *.map       → Source maps (browser devtools only)      (~5–8 MB)
#   *.md        → Package README/docs                      (~1–2 MB)
#   LICENSE*    → Tệp giấy phép, không cần ở runtime      (~0.5 MB)
#   CHANGELOG*  → Changelog packages                       (~0.5 MB)
#   AUTHORS*    → Author files                             (~0.1 MB)
#   NOTICE*     → Legal notice files                       (~0.1 MB)
#   docs/       → Thư mục tài liệu của packages           (~0.5 MB)
# =============================================================
RUN find /app/.next/standalone/node_modules \
        \( -name "*.d.ts" \
        -o -name "*.map" \
        -o -name "*.md" \
        -o -name "LICENSE" \
        -o -name "LICENSE.txt" \
        -o -name "LICENSE.md" \
        -o -name "LICENCE" \
        -o -name "CHANGELOG" \
        -o -name "CHANGELOG.md" \
        -o -name "CHANGELOG.txt" \
        -o -name "HISTORY.md" \
        -o -name "AUTHORS" \
        -o -name "AUTHORS.md" \
        -o -name "NOTICE" \
        -o -name "NOTICE.md" \
        \) -delete 2>/dev/null; \
    find /app/.next/standalone/node_modules \
        -maxdepth 4 -type d -name "docs" \
        -exec rm -rf {} + 2>/dev/null; \
    true


# =============================================================
# Stage 2 — Runtime: image nhỏ gọn chỉ chứa standalone output
# =============================================================
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production
# Tắt telemetry ở runtime (Next.js standalone server cũng gửi nếu không tắt)
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user — giảm attack surface
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy standalone server: Node.js server + tree-shaken node_modules đã làm sạch
# output: 'standalone' trong next.config.mjs → không cần ~300MB full node_modules
COPY --from=builder --chown=appuser:appgroup /app/.next/standalone ./

# Copy static assets: JS chunks, CSS được Next.js generate ở build time
COPY --from=builder --chown=appuser:appgroup /app/.next/static ./.next/static

# public/ chưa có → tạo rỗng để server không báo warning
RUN mkdir -p ./public

USER appuser

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Chạy standalone Node.js server — không cần npm, không cần next CLI
CMD ["node", "server.js"]
