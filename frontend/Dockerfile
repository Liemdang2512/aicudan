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

# [OPT-1] --mount=type=cache cho npm:
#   /root/.npm → cache ~300MB of packages được giữ NGOÀI layer
#   Lần rebuild: npm đọc từ cache → nhanh hơn ~4x, không cần download lại
#   --prefer-offline: ưu tiên dùng cache, chỉ download khi thực sự thiếu
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline

COPY . .

# NEXT_PUBLIC_API_URL là build-time var: Next.js embed vào JS bundle lúc compile
# Phải truyền qua --build-arg khi docker build
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# [OPT-2] Xóa dev artifacts khỏi standalone node_modules TRƯỚC KHI copy sang runtime:
#
#   *.d.ts   → TypeScript declaration files (cho IDE/tsc), không cần ở runtime
#              Tiết kiệm ~8–12MB
#
#   *.map    → Source maps (cho debug với browser devtools), không cần production
#              Tiết kiệm ~5–8MB
#
#   *.md     → Tài liệu package, chỉ dùng để đọc → không cần trong container
#              Tiết kiệm ~1–2MB
#
RUN find /app/.next/standalone/node_modules \
        \( -name "*.d.ts" -o -name "*.map" -o -name "*.md" \) \
        -delete 2>/dev/null; true


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

# Copy standalone server: Node.js server + tree-shaken node_modules đã được làm sạch
# Nhờ output: 'standalone', không cần ~300MB full node_modules
COPY --from=builder --chown=appuser:appgroup /app/.next/standalone ./

# Copy static assets: JS chunks, CSS được Next.js generate ở build time
COPY --from=builder --chown=appuser:appgroup /app/.next/static ./.next/static

# public/ chưa có trong project này → tạo rỗng để server không báo warning
RUN mkdir -p ./public

USER appuser

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Chạy standalone Node.js server — không cần npm, không cần next CLI
CMD ["node", "server.js"]
