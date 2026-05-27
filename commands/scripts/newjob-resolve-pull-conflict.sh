#!/bin/bash
# Step 1: pull main with automatic conflict resolution for identical untracked files
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
python3 "$SCRIPT_DIR/newjob_resolve_pull_conflict.py"
