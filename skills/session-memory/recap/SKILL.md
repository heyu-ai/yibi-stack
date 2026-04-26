---
name: session-memory-recap
type: tool
description: >
  擷取 Claude Code 內建 away_summary（recap）並寫入 ~/.agents/recap/session-recap.jsonl。
  關鍵字：recap、away summary、工作進度軌跡、session 回顧、session-recap。
  與 insight 不同：insight 收集 ★ Insight 教學洞察；recap 收集 Claude Code 自動產生的工作狀態摘要。
---

# session-memory recap：Away Summary 自動收集

## Why（為什麼需要這個）

Claude Code v2.1+ 內建 **Away Summary** 功能：使用者離開 session 一段時間後重返，
Claude Code 會自動產生「目前在做什麼」的進度摘要，UI 上以 `※ recap: ...` 顯示。

這份摘要以 `type=system, subtype=away_summary` 寫入 transcript JSONL。
recap hook 是消費者，只負責讀取；**Claude Code 是生產者，不需要任何 CLAUDE.md 規則**。

同一 session 可能有多筆（每次離開再回來都會產生），依時間排序就是**工作軌跡時序**。

## 安裝

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m tasks.session_memory recap install-hook
```

安裝後每次 Claude Code session 結束（Stop event）時自動觸發。

## JSONL Schema

| 欄位 | 來源 | 說明 |
|------|------|------|
| `id` | transcript entry `uuid` | 冪等 key，同筆不重複寫入 |
| `timestamp` | transcript entry `timestamp` | entry 自帶時間，保留正確時序 |
| `session_id` | entry `sessionId` | Claude Code session UUID |
| `project` | entry `cwd` basename | 專案名稱 |
| `working_dir` | entry `cwd` tilde-encoded | 工作目錄（~/... 格式） |
| `branch` | entry `gitBranch` | git branch |
| `agent_type` | 固定 `"claude"` | Agent 類型 |
| `account` | detect_account() | 偵測到的帳號 |
| `device` | detect_device() | 裝置識別 |
| `recap_text` | entry `content` | Away summary 內容 |
| `cc_version` | entry `version` | Claude Code 版本（如 `2.1.112`）|
| `session_reason` | hook payload `reason` | Stop 原因 |

## Transcript entry 原始結構

```json
{
  "type": "system",
  "subtype": "away_summary",
  "content": "目前正在實作 recap hook，已完成 models.py 與 recap_hook.py...",
  "timestamp": "2026-04-25T10:30:00+08:00",
  "uuid": "4c6cec93-a48c-4d8f-...",
  "sessionId": "4c6cec93-a48c-4d8f-93b2-2ad43150c263",
  "cwd": "/Users/howie/Workspace/github/ainization-skill",
  "gitBranch": "fix/metrics-test-warning",
  "version": "2.1.112"
}
```

## 查詢範例

```bash
# 列出最近 10 筆（預設）
uv run python -m tasks.session_memory recap list

# 過濾特定 project
uv run python -m tasks.session_memory recap list --project ainization-skill

# 查單一 session 的時序軌跡
SESSION_ID="4c6cec93-a48c-4d8f-93b2-2ad43150c263"
uv run python -m tasks.session_memory recap list --session "$SESSION_ID"

# jq：按時間排序看工作軌跡
jq -r 'select(.session_id == "4c6cec93") | "\(.timestamp) — \(.recap_text)"' \
  ~/.agents/recap/session-recap.jsonl | sort

# jq：列出所有 project 的最後一筆 recap
jq -s 'group_by(.project)[] | sort_by(.timestamp) | last | "\(.project): \(.recap_text[:80])"' \
  ~/.agents/recap/session-recap.jsonl
```

## 端對端驗證

```bash
# 模擬 Stop event（用已知有 away_summary 的 transcript）
TRANSCRIPT=~/.claude/projects/-Users-howie-.../XXXXX.jsonl
echo "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$TRANSCRIPT\",\"reason\":\"\"}" | \
  uv run python -m tasks.session_memory recap collect

# 確認寫入
wc -l ~/.agents/recap/session-recap.jsonl
jq -r '.recap_text' ~/.agents/recap/session-recap.jsonl | head -3

# 驗證冪等（再跑一次，行數不變）
echo "{\"hook_event_name\":\"Stop\",\"transcript_path\":\"$TRANSCRIPT\",\"reason\":\"\"}" | \
  uv run python -m tasks.session_memory recap collect
wc -l ~/.agents/recap/session-recap.jsonl
```

## 移除 hook

```bash
uv run python -m tasks.session_memory recap uninstall-hook
```

## 常見問題

| 問題 | 解法 |
|------|------|
| 為什麼不直接讀 transcript？ | transcript 分散在各 session 目錄，recap 統一彙整到 `~/.agents/recap/` 方便跨 session 查詢 |
| 跟 insight 有什麼差異？ | insight 收集 `★ Insight` 教學洞察；recap 收集 Claude Code 內建的工作進度摘要 |
| `/recap` command 跟這個有關係嗎？ | 無直接關係；這個 hook 是 Stop event 驅動的自動收集，`/recap` 若存在是另一個 skill |
| away_summary 沒有出現？ | 需要離開 session 一段時間後重返才會產生；快速來回不會觸發 |
| 同 session 有多筆是正常的嗎？ | 是，每次 away 都會產生一筆，這正是「工作軌跡時序」的設計 |
