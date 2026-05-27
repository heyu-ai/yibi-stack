#!/bin/bash
# Step 2c: detect docker-compose and initialize port conflict prevention
# Outputs [SKIP] and exits 0 if no docker-compose file found.
# Outputs MAIN_REPO=, BRANCH_NAME=, DC_FILE= lines on success for agent consumption.
set -euo pipefail

BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
WT_LINE=$(git worktree list --porcelain | head -1)
MAIN_REPO=${WT_LINE#worktree }
if [ -z "$MAIN_REPO" ] || [ "$MAIN_REPO" = "$WT_LINE" ]; then
  echo '[FAIL] git worktree list --porcelain output has unexpected format' >&2
  exit 1
fi

DC_FILE=""
if [ -f docker-compose.yml ]; then
  DC_FILE=docker-compose.yml
elif [ -f docker-compose.yaml ]; then
  DC_FILE=docker-compose.yaml
fi

if [ -z "$DC_FILE" ]; then
  echo "  [SKIP] no docker-compose file found, skipping port conflict prevention"
  exit 0
fi

if ! uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager init; then
  echo "  [WARN] port registry init failed -- skipping port conflict prevention"
  exit 0
fi

echo "MAIN_REPO=$MAIN_REPO"
echo "BRANCH_NAME=$BRANCH_NAME"
echo "DC_FILE=$DC_FILE"
