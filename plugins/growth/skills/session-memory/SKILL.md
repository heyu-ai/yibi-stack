---
name: session-memory
type: tool
scope: global
description: >
  Multi-Agent 工作協作中樞：跨 Agent（Claude / Gemini / Codex / Gemma）、
  跨帳號（claude-pro / claude-team）、跨機器（MacBook / Mac mini / cloud）的
  統一 handover、insight 系統。所有產出收斂到 ~/.agents/ 根目錄。
  整合原本的 handover 與 insight-collector 兩個 skill，提供：
  - handover 交班記錄讀寫搜尋（SQLite + JSONL 鏡像）
  - insight 自動收集（Claude Code Stop hook）
  - 一次性 migrate 舊資料
  - 四層 fallback 的 account 偵測（env var → adapter → config → unknown）
---

# agents：Multi-Agent 工作協作中樞

## 設計哲學

個人 AI 工作資料目前分散在各 Agent 的獨立目錄（`~/.claude/`、`~/.codex/`、`~/.gemini/`），
換機器、換帳號、換 Agent 時脈絡就斷了。

`agents` 把所有跨 Agent / 跨帳號 / 跨機器的工作產出收斂到單一 `~/.agents/` 根目錄，
用 metadata 欄位（`agent_type` / `account` / `device` / `project`）切片，不用資料夾物理分隔。

子 skill：

| 子 skill | 用途 |
|---|---|
| `handover` | 結構化交班：`agents handover write/read/search` |
| `insight`  | 自動收集 ★ Insight 區塊（Stop hook）：`agents insight install-hook` / `collect` / `list` |
| `recap`    | 自動收集 Claude Code away_summary（Stop hook）：`agents recap install-hook` / `collect` / `list` |
| `debug-report` | 解完 bug 後主動萃取除錯知識、清理過渡產物，寫入 `debugs/*.md` 與 `~/.agents/debugs/debug-reports.jsonl` |

## 目錄結構

```text
~/.agents/
├── config.json                # 本機設定（device_id, default_account）— 不同步
├── _registry/                 # devices / accounts / projects 清單
├── handover/
│   ├── handover.db            # SQLite（主要查詢）
│   └── handover.jsonl         # append-only 鏡像（git / Syncthing 友善）
├── insight/
│   └── insights.jsonl         # 所有 Agent 的洞察
├── recap/
│   └── session-recap.jsonl    # Claude Code away_summary 時序
├── debugs/
│   └── debug-reports.jsonl    # Debug report 摘要（/debug_report 寫入）
└── inbox/                     # 外部匯入暫存（第二階段才用）
```

## 步驟

> **執行位置**：本 skill 可從任何 cwd 觸發，底層實作住在 yibi-stack repo。
> 執行所有 `uv run python -m tasks.*` 指令前，先捕捉原始 project 並解析 SKILL_REPO（Step 1 有完整腳本）：
>
> ```bash
> _gcd=$(git rev-parse --git-common-dir 2>/dev/null)
> case "$_gcd" in
>     /*)
>       _dir=$(dirname "$_gcd")
>       ORIG_PROJECT=$(basename "$_dir")
>       unset _dir ;;
>     ?*)
>       _top=$(git rev-parse --show-toplevel)
>       ORIG_PROJECT=$(basename "$_top")
>       unset _top ;;
>     *)
>       ORIG_PROJECT=$(basename "$PWD") ;;
> esac
> unset _gcd
> if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
> if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
> if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
> ```

### Step 1 — 環境確認

```bash
_gcd=$(git rev-parse --git-common-dir 2>/dev/null)
case "$_gcd" in
    /*)
      _dir=$(dirname "$_gcd")
      ORIG_PROJECT=$(basename "$_dir")
      unset _dir ;;
    ?*)
      _top=$(git rev-parse --show-toplevel)
      ORIG_PROJECT=$(basename "$_top")
      unset _top ;;
    *)
      ORIG_PROJECT=$(basename "$PWD") ;;
esac
unset _gcd
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi

uv --version
python3 --version
```

### Step 2 — 初始化

```bash
uv run --directory "$SKILL_REPO" python -m tasks.session_memory init \
  --device-id {{device_id}} \
  --default-account {{default_account}}
```

說明：

- `--device-id` 未指定會用主機名
- `--default-account` 寫入 `~/.agents/config.json` 供 fallback；之後可用 `AGENT_ACCOUNT` env var 臨時覆蓋

### Step 3 — 搬遷舊資料（若有）

```bash
uv run --directory "$SKILL_REPO" python -m tasks.session_memory migrate
```

從 `~/.handover/` 與 `~/.claude/insight/` 一次性搬到 `~/.agents/`。冪等、可重跑。

### Step 4 — 安裝 Stop hook

```bash
uv run --directory "$SKILL_REPO" python -m tasks.session_memory insight install-hook
```

> **延伸（PostToolUse hook 升級）**：PostToolUse hook 現在支援所有工具輸出替換
> （`hookSpecificOutput.updatedToolOutput`），不再只限 MCP 工具。
> 可考慮在特定高價值工具（如 `Write`、`Bash`）執行後自動記錄 insight：
>
> ```json
> {
>   "hooks": {
>     "PostToolUse": [
>       {
>         "matcher": "Write",
>         "hooks": [{ "type": "command", "command": "python3 ~/.agents/scripts/capture-write-insight.py" }]
>       }
>     ]
>   }
> }
> ```
>
> 評估建議：只為「寫入重要產出」的工具加 hook，避免 Bash/Read 等高頻工具造成過多雜訊。

### Step 5 — 驗證

```bash
uv run --directory "$SKILL_REPO" python -m tasks.session_memory account detect
uv run --directory "$SKILL_REPO" python -m tasks.session_memory handover read --last 4
uv run --directory "$SKILL_REPO" python -m tasks.session_memory insight list --last 5
```

## 子 skill

詳見：

- [handover/SKILL.md](handover/SKILL.md)
- [insight/SKILL.md](insight/SKILL.md)
- [recap/SKILL.md](recap/SKILL.md)
- [debug-report/SKILL.md](debug-report/SKILL.md)

## 跨機器同步

`~/.agents/` 建議用 Syncthing 同步整個資料夾。已預先建立 `.stignore` 排除：

- SQLite journal / WAL 臨時檔
- `config.json`（每台機器自己一份）
- Syncthing 衝突檔

## 帳號偵測（四層 fallback）

| 優先序 | 來源 | 覆蓋情境 |
|---|---|---|
| 1 | 環境變數 `AGENT_ACCOUNT` | 特定 session 手動指定 |
| 2 | Agent adapter 自動偵測（Gemini/Codex/Claude） | 大多數已登入場景 |
| 3 | `~/.agents/config.json` 的 `default_account` | 手動指定固定帳號 |
| 4 | `unknown`（+ stderr 警告） | 未設定時 |

切換帳號：

```bash
export AGENT_ACCOUNT=claude-team      # 臨時切
uv run --directory "$SKILL_REPO" python -m tasks.session_memory account set-default claude-pro
```

## 常見問題

| 問題 | 解法 |
|------|------|
| `init` 後 config.json 已存在 | 用 `--force` 覆蓋，或手動編輯 `~/.agents/config.json` |
| Stop hook 不觸發 | 確認 `~/.claude/settings.json` 有 entry；用 `insight install-hook` 重新註冊 |
| `migrate` 跑兩次會重複嗎 | 不會，以 `id` 去重 |
| 想讓 account 自動偵測 | 已支援：`detect_account(agent_type=...)` 自動讀取 Gemini/Codex credential；Claude 需先執行 `agents account link-claude` 建立 hash 對照 |
| Syncthing 衝突 | 單台機器每天寫入次數低，衝突機率極低；真的衝突會以 `.sync-conflict-*` 副本保留 |
