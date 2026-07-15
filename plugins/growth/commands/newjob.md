---
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

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
git fetch origin main
git checkout main
git pull origin main
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
bash ~/.claude/commands/scripts/newjob-push-guard.sh
```

### 2b. 複製 Gitignored 開發檔案

Worktree 建立後，從主 repo 複製被 `.gitignore` 排除但開發必需的檔案。

```bash
bash ~/.claude/commands/scripts/newjob-copy-gitignored.sh
```

**維護提示**：在專案的 `.claude/commands/newjob.md` 覆蓋此 user-level 版本，加入專案特定內容。常見覆蓋項目：

- 額外的 gitignored 檔案（如 `certs/`, `secrets/`）
- **Step 3b 的 `docker compose up -d`**（全域版本不執行，專案版才啟動）
- 其他 infra 初始化指令（如 `make seed`、`terraform init`）

### 2c. Port 衝突預防（多 Worktree 支援）

若專案有 `docker-compose.yml`，在啟動服務前先透過 `local-port-manager` 確認 host port 不與其他 worktree 衝突。

```bash
bash ~/.claude/commands/scripts/newjob-port-setup.sh
```

**若輸出包含 `[SKIP]` 或 `[WARN]`，停止執行 Step 2c 其餘步驟，直接跳到 Step 3。**

腳本成功時輸出 `MAIN_REPO=`、`BRANCH_NAME=`、`DC_FILE=` 三行，記錄這些值供後續步驟使用。

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

**收尾提示**：Worktree 刪除時（`/clean-wt`），port 登記會隨 branch 一併清理——前提是 `BRANCH_NAME` 與 git branch name 完全一致（即使用 `git rev-parse --abbrev-ref HEAD` 取得的值）。

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
