#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "→ building fresh binary..."
cd "$DIR"
./build.sh

INSTALL=""
for candidate in /usr/local/bin "$HOME/go/bin" "$HOME/.local/bin"; do
    if [ -d "$candidate" ] && [ -w "$candidate" ]; then
        INSTALL="$candidate"
        break
    fi
done

if [ -z "$INSTALL" ]; then
    INSTALL="$HOME/.local/bin"
    mkdir -p "$INSTALL"
fi

TARGET="$INSTALL/learnit"
[ -f "$TARGET" ] && echo "→ replacing existing $TARGET"
cp "$DIR/learnit" "$TARGET"
chmod +x "$TARGET"

echo ""
echo "✓ installed: $TARGET"
echo ""
echo "Usage from any folder:"
echo "  cd /path/to/any/project"
echo "  learnit"
