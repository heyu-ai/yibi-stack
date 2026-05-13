#!/usr/bin/env bash
# newjob-validate.sh: Step 3 環境驗證（newjob 全域版本）
# 從 project worktree root 執行（EnterWorktree 後 cwd 已自動切換）
# 內容由 script 掌管，不寫在 newjob.md 的 bash code block，避免 agent 重寫觸發 CC hook

# 3a. 同步依賴
echo "--- 3a. 同步依賴 ---"
if [ -f "pyproject.toml" ]; then uv sync --all-extras || echo "  [WARN] uv sync (root) 失敗"; fi
if [ -f "backend/pyproject.toml" ]; then uv sync --directory backend --all-extras || echo "  [WARN] uv sync (backend) 失敗"; fi
if [ -f "frontend/package.json" ]; then npm --prefix frontend install || echo "  [WARN] npm install (frontend) 失敗"; fi
if [ -f "admin/package.json" ]; then npm --prefix admin install || echo "  [WARN] npm install (admin) 失敗"; fi
if [ -f "mobile/pubspec.yaml" ]; then flutter pub get --directory mobile || echo "  [WARN] flutter pub get 失敗"; fi

# 3b. 啟動服務（全域跳過）
echo "  [SKIP] Step 3b 全域版本跳過（docker compose 由專案層級 newjob.md 負責）"

# 3c. 執行 Migration
echo "--- 3c. Migration ---"
HAS_MIGRATE=0
if [ -f "Makefile" ] && grep -q '^migrate:' Makefile; then HAS_MIGRATE=1; fi
if [ -f "alembic.ini" ]; then HAS_MIGRATE=1; fi
if [ -f "backend/alembic.ini" ]; then HAS_MIGRATE=1; fi
if [ "$HAS_MIGRATE" = "1" ]; then
  make migrate || echo "  [WARN] migration 失敗，請手動確認（必要時手動執行 alembic upgrade head）"
else
  echo "  [SKIP] 無 migration 設定，跳過"
fi

# 3d. 建立綠色 Baseline
echo "--- 3d. Tests ---"
HAS_PYTHON=0
if [ -f "pyproject.toml" ] || [ -f "backend/pyproject.toml" ]; then HAS_PYTHON=1; fi
HAS_FRONTEND=0
if [ -f "package.json" ] || [ -f "frontend/package.json" ] || [ -f "admin/package.json" ] || [ -f "mobile/pubspec.yaml" ]; then
  HAS_FRONTEND=1
fi
if [ "$HAS_PYTHON" = "1" ]; then
  make test || uv run pytest || echo "  [WARN] 測試失敗（非 blocker，繼續）"
elif [ "$HAS_FRONTEND" = "1" ]; then
  make test || npm test || echo "  [WARN] 測試失敗（非 blocker，繼續）"
else
  echo "  [SKIP] 無可測試的專案，跳過"
fi

# 3e. 確認 Lint 乾淨
echo "--- 3e. Lint ---"
if [ -f "pyproject.toml" ] || [ -f "backend/pyproject.toml" ]; then
  make lint || uv run ruff check . || echo "  [WARN] lint 失敗，請手動修復（make format 或 uv run ruff format .）"
else
  echo "  [SKIP] 無 Python 專案，跳過 lint"
fi

# 3f. 啟用 pre-commit hooks
echo "--- 3f. Hooks ---"
if [ -d ".githooks" ]; then
  git config core.hooksPath .githooks && echo "  [OK] hooks: .githooks" || echo "  [WARN] git config core.hooksPath 失敗"
elif [ -f ".pre-commit-config.yaml" ]; then
  uv run pre-commit install && echo "  [OK] pre-commit installed" || echo "  [WARN] pre-commit install 失敗，hooks 未啟用"
else
  echo "  [SKIP] 無 hooks 設定，跳過"
fi
