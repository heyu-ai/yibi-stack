---
name: scheduler
type: exec
scope: project
description: 管理 Skill Scheduler — 設定定期自動執行的排程、查看執行狀態、手動觸發 job、安裝/卸載 LaunchAgent
---

# Skill: Scheduler

管理定期自動執行 skill 的排程基礎設施。

## 環境確認

```bash
# 確認在專案根目錄
pwd  # 應為 /Users/howie/Workspace/github/yibi-stack

# 確認 Python 環境
uv run python -m tasks.scheduler --help
```

---

## Mode A：初始化 + 安裝 LaunchAgent

### 適用情境：首次設定、重新安裝

```bash
# 1. 初始化設定檔與資料庫
uv run python -m tasks.scheduler setup

# 2. 編輯排程設定（視需求調整 enabled/time）
open .runtime/schedules.json

# 3. 安裝 LaunchAgent（每 60 秒自動 tick）
uv run python -m tasks.scheduler install

# 4. 確認已載入
launchctl list | grep ainization
```

**LaunchAgent 安裝後行為：**

- 每 60 秒執行一次 `tick`
- 時間未到：靜默退出（<50ms）
- 時間到了：執行對應 job，記錄結果到 `.runtime/scheduler.db`
- log 在 `/tmp/ainization-scheduler.log`

---

## Mode B：查看排程狀態

### 適用情境：確認排程是否正常運行

```bash
# 查看所有 job 狀態
uv run python -m tasks.scheduler status

# 查看執行歷史
uv run python -m tasks.scheduler history

# 查看特定 job 歷史（job id 以 .runtime/schedules.json 現行清單為準）
uv run python -m tasks.scheduler history --job-id nightly-self-improvement --limit 10

# 查看 LaunchAgent log
tail -f /tmp/ainization-scheduler.log
tail -f /tmp/ainization-scheduler.err
```

---

## Mode C：手動觸發 job

### 適用情境：測試、補跑、除錯

```bash
# 強制執行特定 job（忽略 is_due 判斷；job id 以 .runtime/schedules.json 現行清單為準）
uv run python -m tasks.scheduler run-job nightly-self-improvement
uv run python -m tasks.scheduler run-job billing-import

# Dry-run tick（只列出 due jobs，不實際執行）
uv run python -m tasks.scheduler tick --dry-run
```

---

## Mode D：卸載

```bash
uv run python -m tasks.scheduler uninstall
```

---

## 設定檔說明（.runtime/schedules.json）

| 欄位 | 說明 |
|------|------|
| `schedule` | `daily` / `weekly` / `monthly` / `bimonthly` / `quarterly` |
| `time` | 執行時間（HH:MM），Mac 睡眠後補跑不會漏 |
| `command` | subprocess 執行的指令陣列 |
| `claude.prompt_file` | Prompt template 路徑（透過 ACP Gateway 執行） |
| `skill` | skill 名稱（讀取 skills/{name}/SKILL.md 執行） |
| `depends_on` | 依賴的 job id 陣列 |
| `enabled` | 是否啟用 |

### Claude job 前提：MiniShell ACP Gateway 必須正在運行

以 MiniShell 專案的**絕對路徑**啟動 Gateway（`<minishell_repo>` 換成實際 clone 位置；
不要用相對路徑 `cd`——依呼叫時 cwd 而異且污染 session CWD）：

```bash
bash <minishell_repo>/scripts/start-acp-gateway.sh
```

---

## CLAUDE_CODE_SESSION_ID 追蹤

Scheduled job 在 Claude Code 環境中執行時，`$CLAUDE_CODE_SESSION_ID` 可用於將 log 與對應的 Claude Code session 關聯，方便事後追蹤：

> **注意**：此變數只在 Claude Code session 內有值。LaunchAgent 直接 spawn 的
> `command` 型 job 子行程**沒有**這個環境變數（值為空）——只有經 ACP Gateway
> 執行的 `claude:` / `skill:` job 才會帶到。

```bash
# 在 job script 中記錄 session ID（拆兩步，避免 $() 包在外層雙引號內）
TS=$(date -Iseconds)
echo "job_start: $TS session=$CLAUDE_CODE_SESSION_ID" >> /tmp/ainization-scheduler.log
```

也可以在 `command` 類型的 job 中直接使用環境變數：

```json
{
  "id": "my-job",
  "type": "command",
  "command": ["bash", "-c", "echo session=$CLAUDE_CODE_SESSION_ID >> /tmp/my-job.log && uv run ..."]
}
```

> 提示：將 session ID 記錄進 log 後，可透過 handover log 與 insight 交叉比對，
> 還原特定 session 觸發的 scheduled job 執行紀錄。
