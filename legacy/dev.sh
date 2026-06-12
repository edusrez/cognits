#!/bin/bash
set -e

if ! command -v air &> /dev/null; then
  echo "Installing air..."
  go install github.com/air-verse/air@latest
fi

cleanup() {
  echo -e "\nstopping..."
  kill 0 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

export ENV=dev

echo "=== starting dev environment ==="
echo "Go server:  http://localhost:5173"
echo "Vite HMR:   http://localhost:5174 (proxied by Go)"
echo ""

cd frontend && bun run dev &
VITE_PID=$!
cd ..

air &
AIR_PID=$!

wait
