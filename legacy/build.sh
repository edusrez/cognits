#!/bin/bash
set -e

echo "=== typechecking frontend ==="
cd frontend && bun run typecheck && cd ..

echo "=== building frontend ==="
cd frontend && bun run build && cd ..

echo "=== copying frontend assets ==="
rm -rf internal/server/dist
cp -r frontend/dist internal/server/dist

echo "=== building backend ==="
BUILD_TIME=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
CGO_ENABLED=0 go build -ldflags "-X main.buildTime=${BUILD_TIME// /_}" -o learnit ./cmd/learnit

echo "=== installing to PATH ==="
INSTALL=""
for candidate in "$HOME/go/bin" "$HOME/.local/bin" /usr/local/bin; do
    if [ -d "$candidate" ] && [ -w "$candidate" ]; then
        INSTALL="$candidate"
        break
    fi
done
if [ -z "$INSTALL" ]; then
    INSTALL="$HOME/.local/bin"
    mkdir -p "$INSTALL"
fi
cp "$(dirname "${BASH_SOURCE[0]}")/learnit" "$INSTALL/learnit"
chmod +x "$INSTALL/learnit"

echo "=== done ==="
echo "Built: ${BUILD_TIME}"
echo "Installed: $INSTALL/learnit"
