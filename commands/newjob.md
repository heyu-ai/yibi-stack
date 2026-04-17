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

UPSTREAM=$(git -C "$WT" rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo "none")
if [ "$UPSTREAM" = "origin/main" ]; then
  echo "⚠️ DANGER: branch 追蹤 origin/main，修正中..."
  git -C "$WT" branch --unset-upstream
  git -C "$WT" push origin "HEAD:$NAME"
  git -C "$WT" branch -u "origin/$NAME"
  echo "✓ 修正完成，現在追蹤 origin/$NAME"
else
  echo "✓ Push tracking OK: $UPSTREAM"
fi
```

### 2b. 複製 Gitignored 開發檔案

Worktree 建立後，從主 repo 複製被 `.gitignore` 排除但開發必需的檔案。

```bash
# EnterWorktree 後 cwd 已切換；用 git worktree list 找主 repo 路徑
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
WT=$(git rev-parse --show-toplevel)

for f in \
  .env \
  backend/.env \
  frontend/.env \
  admin/.env \
  mobile/.env \
; do
  [ -f "$MAIN_REPO/$f" ] && cp "$MAIN_REPO/$f" "$WT/$f" && echo "  ✓ copied $f"
done

# 複製 .runtime/ 目錄（若存在）
[ -d "$MAIN_REPO/.runtime" ] && cp -r "$MAIN_REPO/.runtime" "$WT/.runtime" && echo "  ✓ copied .runtime/"
```

**維護提示**：在專案的 `.claude/commands/newjob.md` 覆蓋此 user-level 版本，可加入專案特定的 gitignored 檔案清單。

## Step 3: Environment Validation

在目標工作目錄中執行（已在 worktree，直接使用相對路徑）。**每個步驟若失敗，診斷並修復後再繼續。**

### 3a. 同步依賴

```bash
# Python（pyproject.toml）
[ -f "pyproject.toml" ] && uv sync --all-extras
[ -f "backend/pyproject.toml" ] && cd backend && uv sync --all-extras && cd ..
# Node（package.json）
[ -f "frontend/package.json" ] && cd frontend && npm install && cd ..
[ -f "admin/package.json" ] && cd admin && npm install && cd ..
# Flutter（pubspec.yaml）
[ -f "mobile/pubspec.yaml" ] && cd mobile && flutter pub get && cd ..
```

### 3b. 啟動服務並等待健康

```bash
docker compose up -d
docker compose ps
```

服務未 healthy 時，查看 logs 診斷並修復：`docker compose logs <service>`

若專案無 Docker，跳過此步驟。

### 3c. 執行 Migration

```bash
make migrate 2>/dev/null || (cd backend && uv run alembic upgrade head) 2>/dev/null || true
```

### 3d. 建立綠色 Baseline

```bash
make test 2>/dev/null || uv run pytest
```

測試失敗是 **warning** 不是 blocker（使用者可能正要修 broken main）。

### 3e. 確認 Lint 乾淨

```bash
make lint 2>/dev/null || uv run ruff check .
```

Lint 失敗時自動修復（`make format` 或 `uv run ruff format .`），然後重跑確認通過。

### 3f. 啟用 pre-commit hooks

```bash
[ -d ".githooks" ] && git config core.hooksPath .githooks && echo "  ✓ hooks: .githooks" && exit 0
[ -f ".pre-commit-config.yaml" ] && uv run pre-commit install && echo "  ✓ pre-commit installed" || true
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
