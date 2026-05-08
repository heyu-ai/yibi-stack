# New Job — 開啟新工作前準備（Worktree-First）

開始新 feature 或 fix 之前，執行此結構化流程確保環境乾淨並建立隔離工作空間。

**自主執行原則**：執行所有步驟，不要問問題。任何步驟失敗時，診斷並修復後繼續。只在全部通過後才告知環境就緒。

## Step 1: 環境偵測

```bash
git rev-parse --show-toplevel
git status --short
```

**判斷邏輯**：

1. **已在 worktree**（`--show-toplevel` 路徑包含 `.claude/worktrees/`）：
   - 告知使用者「偵測到已在 worktree 中」
   - 跳過 Step 2，直接執行 Step 3（Environment Validation）→ Step 4（Report）

2. **在主 repo**：
   - 記錄主 repo 路徑：`MAIN_REPO=$(git rev-parse --show-toplevel)`
   - 如有 uncommitted changes，**警告**使用者（提醒 stash 或 commit）
   - 根據使用者提供的 feature name 自動命名（簡短有意義，例如 `fix-auth-bug`、`feat-dashboard`）
   - 繼續 Step 2

## Step 2: 建立 Worktree

確保主 repo 是最新的，然後呼叫 `EnterWorktree` 工具切換 session：

```bash
git -C "$MAIN_REPO" fetch origin main
git -C "$MAIN_REPO" checkout main
git -C "$MAIN_REPO" pull origin main
```

然後**呼叫 `EnterWorktree` 工具**，傳入推導出的 `name`（如 `feat-dashboard`）。

`EnterWorktree` 會：

- 在 `.claude/worktrees/<name>` 建立 worktree（branch `<name>` based on HEAD）
- **自動切換 session cwd** 到新 worktree

> **注意**：呼叫 `EnterWorktree` 後，session 已在 worktree 內。後續所有指令的相對路徑都以 worktree 為基礎。

### 2a. ⚠️ Push 安全驗證（必做）

`EnterWorktree` 建立的 worktree branch 預設追蹤 `origin/main`。
`push.default=upstream` + 追蹤 `origin/main` = `git push` 直推 main，繞過 PR 流程。

```bash
NAME=<worktree-name>
WT=$(git rev-parse --show-toplevel)

# linked worktree 的 .git 是 file（gitdir: 指標）；主 repo 的 .git 是 directory
[ -d "$WT/.git" ] && { echo "[FAIL] cwd 仍在主 repo，EnterWorktree contract 失效" >&2; exit 1; }

UPSTREAM=$(git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null)
[ -z "$UPSTREAM" ] && UPSTREAM="none"
if [ "$UPSTREAM" = "origin/main" ]; then
  echo "[WARN] DANGER: branch 追蹤 origin/main，修正中..."
  git -C "$WT" branch --unset-upstream
  git -C "$WT" push origin "HEAD:$NAME"
  git -C "$WT" branch -u "origin/$NAME"
  echo "[OK] 修正完成，現在追蹤 origin/$NAME"
else
  echo "[OK] Push tracking OK: $UPSTREAM"
fi
```

### 2b. 複製 Gitignored 開發檔案

Worktree 建立後，從主 repo 複製被 `.gitignore` 排除但開發必需的檔案。

```bash
# EnterWorktree 後 cwd 已切換；用 git worktree list 找主 repo 路徑
MAIN_REPO=$(git worktree list | head -1 | python3 -c "import sys; print(sys.stdin.read().split()[0])")
[ -z "$MAIN_REPO" ] && { echo "[FAIL] git worktree list 無法取得主 repo 路徑" >&2; exit 1; }
WT=$(git rev-parse --show-toplevel)

for f in \
  .env \
  backend/.env \
  frontend/.env \
  admin/.env \
  mobile/.env \
; do
  [ -f "$MAIN_REPO/$f" ] && cp "$MAIN_REPO/$f" "$WT/$f" && echo "  [OK] copied $f"
done

# 複製 .runtime/ 目錄（若存在）
[ -d "$MAIN_REPO/.runtime" ] && cp -r "$MAIN_REPO/.runtime" "$WT/.runtime" && echo "  [OK] copied .runtime/"

# 複製 .claude/settings.local.json（Claude Code allowlist，不進 git）
# 刻意複製完整 allowlist：worktree 與主 repo 屬同一開發者，繼承所有本地授權是預期行為。
# 含絕對路徑的 allow rule 仍指向主 repo 路徑（對 cross-repo 命令仍有效）。
if [ "$MAIN_REPO" = "$WT" ]; then
  echo "  [WARN] MAIN_REPO == WT，跳過複製 settings.local.json"
elif [ -f "$MAIN_REPO/.claude/settings.local.json" ]; then
  mkdir -p "$WT/.claude"
  cp "$MAIN_REPO/.claude/settings.local.json" "$WT/.claude/settings.local.json"
  echo "  [OK] copied .claude/settings.local.json"
fi
```

**維護提示**：在專案的 `.claude/commands/newjob.md` 覆蓋此 user-level 版本，加入專案特定內容。常見覆蓋項目：

- 額外的 gitignored 檔案（如 `certs/`, `secrets/`）
- **Step 3b 的 `docker compose up -d`**（全域版本不執行，專案版才啟動）
- 其他 infra 初始化指令（如 `make seed`、`terraform init`）

### 2c. Port 衝突預防（多 Worktree 支援）

若專案有 `docker-compose.yml`，在啟動服務前先透過 `local-port-manager` 確認 host port 不與其他 worktree 衝突。

```bash
# BRANCH_NAME 是 port registry 的 key，必須與 git branch name 一致
# 讓 /clean-gone 和 /clean-merged 的 release 步驟能對上
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
MAIN_REPO=$(git worktree list | head -1 | python3 -c "import sys; print(sys.stdin.read().split()[0])")
[ -z "$MAIN_REPO" ] && { echo "[FAIL] git worktree list 無法取得主 repo 路徑" >&2; exit 1; }

# 偵測 docker-compose 檔案（用 [ -f ] 取代 $(ls "...") 避免 quoted-in-subshell 問題）
DC_FILE=""
[ -f docker-compose.yml ] && DC_FILE=docker-compose.yml
[ -z "$DC_FILE" ] && [ -f docker-compose.yaml ] && DC_FILE=docker-compose.yaml

# 若無 docker-compose 檔案，跳過整個 port 衝突預防步驟
[ -z "$DC_FILE" ] && echo "  [SKIP] 無 docker-compose 檔案，跳過 port 衝突預防"
```

**若上方輸出 `[SKIP]`，停止執行 Step 2c 其餘所有 bash 指令，直接跳到 Step 3。**

**初始化 port registry（若尚未建立）：**

```bash
uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager init || echo "  [WARN] port registry init 失敗 -- 跳過 port 衝突預防"
```

**若上方輸出 `[WARN]`，停止執行 Step 2c 其餘所有 bash 指令，直接跳到 Step 3。**

**對每個需要 host port 的服務執行以下流程：**

1. `uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager suggest $BRANCH_NAME <service>` — 取得建議 port（不衝突）
2. 若建議 port 與 docker-compose 預設值**不同**，在 `docker-compose.override.yml` 加入 port 覆蓋，並更新 `.env` 中對應的變數（如 `POSTGRES_PORT=5433`）
3. `uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager reserve $BRANCH_NAME <service> --port <port>` — 寫入登記

常見需要檢查的服務對應：

| service | 預設 port | .env 變數（慣例） |
|---------|-----------|-------------------|
| postgres / db | 5432 | `POSTGRES_PORT` |
| redis | 6379 | `REDIS_PORT` |
| mysql | 3306 | `MYSQL_PORT` |
| elasticsearch | 9200 | `ES_PORT` |

若專案無 docker-compose.yml，跳過此步驟。

**收尾提示**：Worktree 刪除時（`/clean-gone` 或 `/clean-merged`），port 登記會隨 branch 一併清理——前提是 `BRANCH_NAME` 與 git branch name 完全一致（即使用 `git rev-parse --abbrev-ref HEAD` 取得的值）。

## Step 3: Environment Validation

**重要**：EnterWorktree 後 session cwd 已自動切換到 worktree。以下所有 bash 指令**必須**照 code block 原文執行：

- **不要** `cd <any-path>` 切換目錄（AP3 CWD 污染）
- **不要** 在指令中加 `WT=$(git rev-parse --show-toplevel)` 或 `$WT/` 前綴（`$(cmd "$WT/...")` 形式觸發 CC 內建 "Unhandled node type: string"；`"${WT}/..."` 括號形式另觸發 Rule 5 false positive）
- **直接用相對路徑**，code block 已寫好，複製貼上即可

**每個步驟若失敗，診斷並修復後再繼續。**

### 3a. 同步依賴

```bash
# Python（pyproject.toml）
[ -f "pyproject.toml" ] && uv sync --all-extras
[ -f "backend/pyproject.toml" ] && uv sync --directory backend --all-extras
# Node（package.json）
[ -f "frontend/package.json" ] && npm --prefix frontend install
[ -f "admin/package.json" ] && npm --prefix admin install
# Flutter（pubspec.yaml）
[ -f "mobile/pubspec.yaml" ] && (cd mobile && flutter pub get)
```

### 3b. 啟動服務（Project Hook — 全域版本跳過）

**全域版本不執行此步驟。** `docker compose up -d` 有副作用（網路、資源、port 佔用），不在全域命令中自動觸發。

```bash
echo "  [SKIP] Step 3b 全域版本跳過（docker compose 由專案層級 newjob.md 負責）"
```

若需要啟動服務，在**專案層級 `.claude/commands/newjob.md`** 中加入下方範本（此處不執行）：

```text
# 專案 Step 3b 範本（複製到專案 newjob.md 後，取消 # 前綴）：
# WT=$(git rev-parse --show-toplevel)
# DC_FILE=$(ls "$WT/docker-compose.yml" "$WT/docker-compose.yaml" 2>/dev/null | head -1)  # Step 2c 已算過，若同 shell context 可直接沿用
# if [ -z "$DC_FILE" ]; then echo "  [SKIP] 無 docker-compose 檔案，跳過"; else
#   docker compose up -d && docker compose ps
# fi
```

### 3c. 執行 Migration

```bash
# Guard：只在有 Makefile 頂層 migrate target（^migrate:）或 alembic.ini 時才執行
if { [ -f "Makefile" ] && grep -q "^migrate:" Makefile; } || \
   { [ -f "alembic.ini" ] || [ -f "backend/alembic.ini" ]; }; then
  make migrate 2>/dev/null || \
    uv run --directory backend alembic upgrade head || \
    echo "  [WARN] migration 失敗，請手動確認"
else
  echo "  [SKIP] 無 migration 設定，跳過"
fi
```

### 3d. 建立綠色 Baseline

```bash
# Guard：依技術棧分別執行測試，避免 Python 工具跑在 Node-only 專案上
if [ -f "pyproject.toml" ] || [ -f "backend/pyproject.toml" ]; then
  make test 2>/dev/null || uv run pytest
elif [ -f "package.json" ] || [ -f "frontend/package.json" ] || \
     [ -f "admin/package.json" ] || [ -f "mobile/pubspec.yaml" ]; then
  make test || npm test || echo "  [WARN] 測試失敗（非 blocker，繼續）"
else
  echo "  [SKIP] 無可測試的專案，跳過"
fi
```

測試失敗是 **warning** 不是 blocker（使用者可能正要修 broken main）。

### 3e. 確認 Lint 乾淨

```bash
# Guard：只在有 pyproject.toml 或 backend/pyproject.toml 時才執行 ruff
if [ -f "pyproject.toml" ] || [ -f "backend/pyproject.toml" ]; then
  make lint 2>/dev/null || uv run ruff check .
else
  echo "  [SKIP] 無 Python 專案，跳過 lint"
fi
```

Lint 失敗時自動修復（`make format` 或 `uv run ruff format .`），然後重跑確認通過。

### 3f. 啟用 pre-commit hooks

```bash
if [ -d ".githooks" ]; then
  git config core.hooksPath .githooks && echo "  [OK] hooks: .githooks" || echo "  [WARN] git config core.hooksPath 失敗"
elif [ -f ".pre-commit-config.yaml" ]; then
  uv run pre-commit install && echo "  [OK] pre-commit installed" || echo "  [WARN] pre-commit install 失敗，hooks 未啟用"
fi
```

## Step 4: Go/No-Go Report

全部通過後才輸出就緒報告：

```text
=== New Job Report ===
Branch:      <name>
Worktree:    .claude/worktrees/<name>
Session cwd: ✅ 已自動切換至 worktree
Services:    ✅ all healthy / ⏭ skipped (no Docker)
Tests:       ✅ N passed / ⚠️ N failed (see above)
Lint:        ✅ clean
Issues fixed: <若有，列出修復的項目>
─────────────────────────
✅ Environment is ready. 可直接開始開發。
```

如有任何步驟無法修復，列出具體錯誤並停在此，請使用者介入。
