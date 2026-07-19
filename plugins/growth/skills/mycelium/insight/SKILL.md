---
name: mycelium-insight
type: tool
scope: global
description: >
  Claude Code Stop hook，自動從 session transcript 擷取 ★ Insight 區塊，
  以 JSONL 格式累積至 ~/.agents/insight/insights.jsonl。
  被動式收集，不需手動觸發。每次 Claude 完成回應時自動執行。
  是 `mycelium` skill 的子 skill，整合跨 Agent / 跨帳號的 metadata。
  本 skill 只收 ★ Insight 教學洞察，不收 Claude Code 自動產生的工作狀態摘要（那由 sibling 負責）。
---

# mycelium insight：洞察自動收集器

## 設計哲學

Explanatory output style 在對話中產出的 `★ Insight` 區塊是揮發性的——context 壓縮或對話結束後就消失。
Insight Collector 以 Stop hook 的方式在每次 Claude 完成回應時靜默執行，將洞察持久化為 JSONL 記錄。

相比舊版 `insight-collector`：

- 儲存路徑從 `~/.claude/insight/` 移到 `~/.agents/insight/`
- 每筆記錄加上 `account` 與 `device` 欄位（三層 fallback 自動偵測）
- 之後接其他 Agent 只需擴充 `agent_type`

## 步驟

> **執行位置**：本 skill 可從任何 cwd 觸發。啟動時先捕捉原始 project，並
> preflight PATH 中 installed `mycelium`：
>
> ```bash
> _gcd=$(git rev-parse --git-common-dir 2>/dev/null)
> case "$_gcd" in
>     /*) _dir=$(dirname "$_gcd"); ORIG_PROJECT=$(basename "$_dir"); unset _dir ;;
>     ?*) _top=$(git rev-parse --show-toplevel); ORIG_PROJECT=$(basename "$_top"); unset _top ;;
>     *)  ORIG_PROJECT=$(basename "$PWD") ;;
> esac
> unset _gcd
> if ! command -v mycelium >/dev/null 2>&1; then
>   echo '[FAIL] 缺少 mycelium，請執行：uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"' >&2
>   exit 1
> fi
> ```

### Step 1 — 安裝 Stop hook

```bash
mycelium insight install-hook
```

會把以下 entry 寫入 `~/.claude/settings.json`：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/mycelium insight collect"
          }
        ]
      }
    ]
  }
}
```

冪等：已註冊時會跳過。

### Step 2 — 驗證安裝

```bash
python3 -c "import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.claude/settings.json').read_text()).get('hooks',{}).get('Stop', '(未設定)'))"
```

### Step 3 — 產生一個 Insight（觸發測試）

在 Claude Code 對話中讓模型產出一個 `★ Insight ─────` 區塊，等對話結束後：

```bash
mycelium insight list --last 1 --project "$ORIG_PROJECT"
```

應能看到剛才那筆。

### Step 4 — 移除

```bash
mycelium insight uninstall-hook
```

## JSONL Schema

每個 `★ Insight` 區塊產生一筆記錄：

| 欄位 | 說明 |
|------|------|
| `id` | UUID v4 |
| `timestamp` | ISO 8601（含時區） |
| `session_id` | Claude Code session ID |
| `project` | 工作目錄 basename |
| `working_dir` | 完整工作目錄路徑 |
| `branch` | Git branch 名稱 |
| `agent_type` | 固定 `"claude"`（Stop hook 只來自 Claude Code） |
| `account` | 三層 fallback 偵測結果 |
| `device` | config.json 的 device_id |
| `insight_text` | 擷取的 Insight 內容 |
| `session_reason` | Claude 停止的原因 |

## ★ Insight 偵測格式

```text
`★ Insight ─────────────────────────────────────`
這裡寫洞察內容（支援多行）
`─────────────────────────────────────────────────`
```

開頭與結尾的 backtick 不可省略。

## 查詢

```bash
# CLI 列出最近 N 筆
mycelium insight list --last 10 --project "$ORIG_PROJECT"
mycelium insight list --project yibi-stack

# 也可直接用 jq
jq 'select(.project == "yibi-stack")' ~/.agents/insight/insights.jsonl
jq -r '.project' ~/.agents/insight/insights.jsonl | sort | uniq -c | sort -rn
```

## 常見問題

| 問題 | 解法 |
|------|------|
| 安裝後沒有記錄產生 | 確認對話中有完整的 `` `★ Insight ─────...` `` 區塊 |
| `insights.jsonl` 找不到 | 正常——首次收到 Insight 時才建立 |
| 想確認 hook 是否正確安裝 | 見 Step 2 的驗證指令 |
| 想停用但不移除 | 編輯 `~/.claude/settings.json` 手動移除對應 entry |
| 所有記錄 account 都是 unknown | 設定 `AGENT_ACCOUNT` env var 或 `agents account set-default` |
