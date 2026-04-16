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
   - 跳過 Step 2，直接執行 Step 3（Baseline Check）→ Step 4（Report）

2. **在主 repo 或其他位置**：
   - 如有 uncommitted changes，**警告**使用者（提醒 stash 或 commit）
   - 用 `AskUserQuestion` 詢問新任務的描述，推導 worktree 名稱，然後執行 Step 2

## Step 2: 建立 Worktree

根據使用者描述推導 worktree 名稱（簡短有意義，例如 `fix-csv-parse`、`feat-receipt-upload`）。

**先確保 main 是最新的：**

```bash
MAIN_REPO=$(git rev-parse --show-toplevel)
git -C "$MAIN_REPO" fetch origin main
```

**使用 `EnterWorktree` tool 建立並切換 worktree**（傳入推導出的 `name`）。
`EnterWorktree` 會自動建立 `.claude/worktrees/<name>` 並將 session cwd 切換過去。

### 2a. ⚠️ Push 安全驗證（必做）

`EnterWorktree` 建立的 worktree branch 預設追蹤 `origin/main`。
`push.default=upstream` + 追蹤 `origin/main` = commit 直推 main，繞過 PR 流程。

```bash
NAME=<worktree-name>
WT="$(git rev-parse --show-toplevel)"

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

Worktree 建立後，session cwd 已切換到 worktree 目錄。從主 repo 複製被 `.gitignore` 排除但開發必需的檔案。

```bash
# EnterWorktree 後 cwd 已切換到 worktree；用 git worktree list 找主 repo 路徑
# （git rev-parse --show-toplevel 在 worktree 內會回傳 worktree 路徑，不是主 repo）
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
WT=$(git rev-parse --show-toplevel)

for f in \
  .env \
; do
  [ -f "$MAIN_REPO/$f" ] && cp "$MAIN_REPO/$f" "$WT/$f" && echo "  ✓ copied $f"
done

# 複製 .runtime/ 目錄（若存在）
[ -d "$MAIN_REPO/.runtime" ] && cp -r "$MAIN_REPO/.runtime" "$WT/.runtime" && echo "  ✓ copied .runtime/"
```

**維護提示**：若日後有其他 gitignored 開發檔案，在上方 `for` 清單中加入路徑即可。

## Step 3: Baseline Check

在目標 worktree 目錄中執行。**每個步驟若失敗，診斷並修復後再繼續。**

### 3a. 同步依賴

確保 `.venv` 與最新 `pyproject.toml` 一致。

```bash
uv sync --all-extras
```

### 3b. 跑測試

```bash
uv run pytest
```

測試失敗是 **warning** 不是 blocker（使用者可能正要修 broken main）。

### 3c. Lint 檢查

```bash
make lint
```

Lint 失敗時自動嘗試修復（`make format`），然後重跑確認通過。

## Step 4: Go/No-Go Report

全部通過後才輸出就緒報告：

```text
=== New Job Report ===
Branch:      <name>
Worktree:    .claude/worktrees/<name>
uv sync:     ✅ OK
pytest:      ✅ passed / ⚠️ failed (N issues)
lint:        ✅ clean / ⚠️ failed
Issues fixed: <若有，列出修復的項目>
─────────────────────────
✅ Environment is ready.
```

如有任何步驟無法修復，列出具體錯誤並停在此，請使用者介入。

## Step 5: 確認切換成功

`EnterWorktree` 會自動將 session cwd 切換到 worktree。
確認目前位置正確：

```bash
pwd
git rev-parse --abbrev-ref HEAD
```

輸出應顯示 `.claude/worktrees/<name>` 路徑，以及 branch name 為 `<name>`。
