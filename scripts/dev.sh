#!/bin/bash
# Development environment: Vite with HMR (5174) + uvicorn --reload (5173).
# The backend in ENV=dev proxies the frontend to Vite (HTTP and WebSocket).
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

cleanup() {
  echo -e "\nstopping..."
  kill 0 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

export ENV=dev

echo "=== starting dev environment ==="
echo "Backend:    http://localhost:${PORT:-5173}"
echo "Vite HMR:   http://localhost:5174 (proxied by backend)"
echo ""

(cd frontend && bun run dev) &

uv run uvicorn --factory cognits.server.app:create_app \
  --reload --port "${PORT:-5173}" &

wait
