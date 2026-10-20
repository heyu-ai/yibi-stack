---
model: sonnet
---

# Handover — 寫入工作交班記錄

結束本次工作階段前，將目前進度、決策、下一步寫入 handover 記錄，供下次（或其他 Agent）接手。

> **執行注意**：
>
> - **交班內容一律寫進 JSON 檔，不要放在指令列**。指令列帶自由文字時，內容裡的字眼會被其他 repo 的
>   permission deny 規則當成指令比對。實例：yibi-mvp 的 `Bash(uv run --directory * alembic upgrade*)`，
>   `*` 會跨參數比對，交班的 `--next` 只要寫到「alembic upgrade」，整條指令就被直接拒絕，不會跳確認框。
>   同類規則還有 `rm -rf *`、`ssh *`、`find * -delete*`。
> - **用 `~/.agents/bin/handover` wrapper，不要自己組 `SKILL_REPO=$(...)`**：wrapper 會自行解析
>   yibi-stack 路徑，並以目前工作目錄補上 `--workdir`（project 與 branch 由此偵測，在 worktree 內也會
>   回報主 repo 名稱）。有些 repo 的 PreToolUse hook 會擋下指令字串裡的 command substitution
>   （例如 yibi-mvp 的 `protect-bash-cd.py`），所以指令列不要出現 `$(...)`。
> - wrapper 不存在（`no such file`、exit 127）或回報 `[FAIL] 無法解析 skill repo` 時停止，請使用者在
>   yibi-stack 目錄執行 `make install`。

## Step 1 — 從對話萃取摘要並寫成 JSON 檔

根據目前對話內容整理以下欄位，用 **Write 工具**寫成一個 JSON object 檔：

| key | 型別 | 內容 |
|-----|------|------|
| `session_type` | 字串（必填） | `sdd` / `debug` / `discussion` / `admin` |
| `topic` | 字串（必填） | 本次工作的主題（一句話） |
| `summary` | 字串（必填） | 對話重點摘要（2-4 句） |
| `completed` | 字串 array | 完成了什麼 |
| `decisions` | 字串 array | 做了哪些決策 |
| `blocked` | 字串 array | 卡住的事項（若無則 `[]`） |
| `next` | 字串 array | 下一步優先事項 |
| `lessons` | 字串 array | 學到什麼（若無則 `[]`） |
| `approaches` | 字串 array | 試過的方案（debug 時特別重要） |
| `tags` | 字串 array | 自由標籤 |

只能用上表的 key，拼錯會直接報錯。array 欄位要寫成真正的 JSON array，不是字串。

檔名要唯一，避免讀到別的 session 留下的同名檔（例如 `handover-20261020-1530-a1b2.json`）。
放在 background session 的 `$CLAUDE_JOB_DIR/tmp/` 底下；沒有這個環境變數時放在 `/tmp/`。
完整絕對路徑記為 `<FILE>`。

```json
{
  "session_type": "sdd",
  "topic": "change 0187 實作",
  "summary": "完成 tasks 1.1 到 7.4，已 push。",
  "completed": ["tasks 1.1-7.4 完成"],
  "decisions": [],
  "blocked": [],
  "next": ["人跑 alembic upgrade"],
  "lessons": [],
  "approaches": [],
  "tags": ["0187"]
}
```

## Step 2 — 寫入交班

在目前的工作目錄執行（不要先 `cd` 到 yibi-stack），把 `<FILE>` 換成上一步的絕對路徑，保留雙引號：

```bash
~/.agents/bin/handover write --from-file "<FILE>"
```

exit code 非 0 時停止，回報 `[FAIL] handover write 執行失敗` 並附上 stderr 原文。exit code 2 代表
JSON 檔內容不合格式，依錯誤訊息修正檔案後重跑；不要改成把內容放回指令列。

未提供的環境 metadata 會自動偵測（`device` / `branch` / `project`）。

## Step 3 — 確認寫入

```bash
~/.agents/bin/handover read --last 1
```

輸出最新一筆確認寫入成功。
