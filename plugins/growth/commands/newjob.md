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

- 在 `.claude/worktrees/<name>` 建立 worktree（branch `<name>` based on `origin/main`，因 `worktree.baseRef: "fresh"`）
- **自動切換 session cwd** 到新 worktree

> **注意**：呼叫 `EnterWorktree` 後，session 已在 worktree 內。後續所有指令的相對路徑都以 worktree 為基礎。

### 2a. ⚠️ Push 安全驗證（必做）

`EnterWorktree` 建立的 worktree branch 預設追蹤 `origin/main`。
`push.default=upstream` + 追蹤 `origin/main` = `git push` 直推 main，繞過 PR 流程。

```bash
NAME=<worktree-name>
WT=$(git rev-parse --show-toplevel)
if [ -z "$WT" ]; then
  echo '[FAIL] git rev-parse --show-toplevel 失敗，無法確認 worktree 路徑' >&2
  exit 1
fi

# EnterWorktree 建立的 linked worktree 其根目錄的 .git 是 file（gitdir: 指標）；
# 主 worktree 的 .git 是 directory。此 guard 假設使用標準 linked-worktree 佈局。
if [ -d "$WT/.git" ]; then
  echo '[FAIL] cwd 仍在主 repo，EnterWorktree contract 失效' >&2
  exit 1
fi

# Git linked worktree 鎖定被 checkout 的 branch，讓主 repo 無法再 checkout 同一 branch。
# 此 repo 預設分支為 main，故只檢查 main；若改用其他預設分支名稱，需同步更新此處。
CURRENT_BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)
if [ -z "$CURRENT_BRANCH" ]; then
  echo '[FAIL] 無法取得 worktree 當前 branch 名稱' >&2
  exit 1
fi
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
  echo '[FAIL] worktree 處於 detached HEAD 狀態 -- 請先 git checkout <branch>' >&2
  exit 1
fi
if [ "$CURRENT_BRANCH" = "main" ]; then
  echo '[FAIL] worktree 正在 checkout main -- 請刪除此 worktree 並重新執行 /newjob' >&2
  exit 1
fi

UPSTREAM=$(git rev-parse --abbrev-ref 'HEAD@{upstream}' 2>/dev/null)
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
# --porcelain 第一行格式固定為 "worktree <path>"，路徑含空格也安全
# awk/cut 的單引號引數在 $() 內觸發 CC token scanner；改用 # prefix removal 規避
WT_LINE=$(git worktree list --porcelain | head -1)
MAIN_REPO=${WT_LINE#worktree }
if [ -z "$MAIN_REPO" ] || [ "$MAIN_REPO" = "$WT_LINE" ]; then
  echo '[FAIL] git worktree list --porcelain 輸出非預期格式，無法取得主 repo 路徑' >&2
  exit 1
fi
WT=$(git rev-parse --show-toplevel)

for f in .env backend/.env frontend/.env admin/.env mobile/.env; do
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
WT_LINE=$(git worktree list --porcelain | head -1)
MAIN_REPO=${WT_LINE#worktree }
if [ -z "$MAIN_REPO" ] || [ "$MAIN_REPO" = "$WT_LINE" ]; then
  echo '[FAIL] git worktree list --porcelain 輸出非預期格式，無法取得主 repo 路徑' >&2
  exit 1
fi

# 偵測 docker-compose 檔案：用相對路徑，cwd 已是 worktree 根目錄
# 避開 "$VAR/suffix" 形式（會觸發 CC parser 確認框）
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

環境驗證邏輯住在 script 檔，不在 markdown code block，避免 agent 重寫 bash 觸發 CC hook 確認框。

```bash
bash ~/.claude/commands/scripts/newjob-validate.sh
```

若 `~/.claude/commands/scripts/newjob-validate.sh` 不存在，先在 yibi-stack repo 執行 `make install`。

**每個步驟若失敗，診斷並修復後再繼續。** 測試失敗是 warning 不是 blocker。Lint 失敗時自動修復（`make format` 或 `uv run ruff format .`）後重跑。

**專案層級覆蓋**：在 `.claude/commands/newjob.md` 取代此步驟，可加入 `docker compose up -d` 及其他 infra 初始化指令。

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
