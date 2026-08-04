#!/bin/bash
# deploy.sh — chạy trên VPS để update code và restart services
set -e

echo "[deploy] Pulling latest code..."
git fetch origin
git reset --hard origin/main

echo "[deploy] Building and restarting containers..."
docker compose build --no-cache
docker compose up -d

echo "[deploy] Done. Status:"
docker compose ps
