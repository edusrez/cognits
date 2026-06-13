#!/usr/bin/env bash
# Smoke test: full pipeline — frontend build + package + install locally.
# Use this after code changes to verify the installed tool end-to-end
# before publishing to PyPI.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== building frontend ==="
(cd frontend && bun install --frozen-lockfile && bun run build)

echo "=== copying frontend assets into package ==="
rm -rf src/cognits/frontend_dist
cp -r frontend/dist src/cognits/frontend_dist

echo "=== installing locally from source ==="
uv tool install --reinstall --force .

echo ""
echo "=== smoke test: --version ==="
cognits --version

echo ""
echo "Ready. Run 'cognits' to start the full application."
