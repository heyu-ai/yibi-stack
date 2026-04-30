#!/usr/bin/env bash
# Usage: safe_symlink.sh <src> <dst>
# Creates symlink dst→src with dangling/existing/real-dir state handling.
# Exits 0 on success or no-op; exits 1 on ln failure.

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "  ✗ safe_symlink.sh: src and dst arguments are required" >&2
    exit 1
fi

src="$1"
dst="$2"
name=$(basename "$dst")
dir=$(dirname "$dst")

if [ -L "$dst" ] && [ ! -e "$dst" ]; then
    rm -f "$dst" && ln -sf "$src" "$dst" \
        && echo "  ⚠ $name → relinked ($dir)" \
        || { echo "  ✗ $name → relink FAILED in $dir"; exit 1; }
elif [ -L "$dst" ]; then
    echo "  ↻ $name ($dir)"
elif [ -e "$dst" ]; then
    echo "  ⚠ $name (real path exists, skipping $dir)"
else
    ln -sf "$src" "$dst" \
        && echo "  ✓ $name → $dir" \
        || { echo "  ✗ $name → $dir FAILED"; exit 1; }
fi
