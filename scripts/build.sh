#!/bin/bash
# Build completo: frontend (bun + vite) → package data → wheel (uv build).
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== typechecking frontend ==="
(cd frontend && bun run typecheck)

echo "=== building frontend ==="
(cd frontend && bun run build)

echo "=== copying frontend assets into package ==="
rm -rf src/cognits/frontend_dist
cp -r frontend/dist src/cognits/frontend_dist

echo "=== building wheel ==="
rm -rf dist
uv build

echo ""
echo "Hecho. Instalar localmente con:"
echo "  uv tool install --force dist/cognits-*.whl"
echo "Publicar en PyPI con:"
echo "  uv publish"
