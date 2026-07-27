#!/usr/bin/env bash
# Go pre-release gate：go test ./...

set -euo pipefail

echo "[OK] 執行 go test ./..."
go test ./...
