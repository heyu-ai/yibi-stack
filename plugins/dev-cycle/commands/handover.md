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
| `files` | 字串 array（選填） | 這次碰過的檔案 |
| `test_status` | 字串（選填） | 測試狀態（例如「make ci 全綠」） |
| `tokens` | 字串（選填） | token 用量估計 |

只能用上表的 key，拼錯會直接報錯。array 欄位要寫成真正的 JSON array（不是字串），元素一律是
字串：`null`、數字、object 都會被拒絕。

檔案一律放在 `/tmp/handover-<YYYYMMDD-HHMM>-<4 位隨機 hex>.json`，例如
`/tmp/handover-20261020-1530-a1b2.json`。路徑由你直接組出完整的字面值（不需要展開任何環境變數），
檔名帶時間與隨機碼是為了避免讀到別的 session 留下的同名檔。這個完整絕對路徑記為 `<FILE>`。

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

exit code 非 0 時，先讀 stderr 判斷原因，**不要只看 exit code**（exit 2 是 click 所有用法錯誤共用的
代碼，不一定是 JSON 內容問題）：

- stderr 含 `No such option '--from-file'`：yibi-stack 主 checkout 還是舊版。停止，回報
  `[FAIL] handover write 執行失敗` 並附上 stderr 原文，請使用者在 yibi-stack 主 checkout 執行
  `git pull`。**不要修改 JSON 檔**，檔案本身沒有問題。
- stderr 含 `無法讀取`：`<FILE>` 路徑錯誤，或忘了把 `<FILE>` 換成實際路徑。確認路徑後重跑。
- stderr 含 `DB 資料已保存，但 JSONL 備份寫入失敗`：交班**已經寫進 DB**，只有 JSONL 備份缺了這一筆，
  **不要重跑**（重跑會再寫一筆重複的交班）。從 stderr 結尾的 `（id=<id>）` 取出記錄 id，回報
  `[WARN] 交班已寫入 DB（id=<id>），但 JSONL 備份缺少這筆記錄` 並附上 stderr 原文。
  到此結束，**跳過 Step 3**（這種情況 stdout 不會有 `✓` 行）。
- stderr 含 `交班記錄寫入失敗`：資料庫寫入失敗（ID 衝突、schema 不符或資料庫錯誤），交班**沒有寫入**。
  這是 DB 端的問題，**不要修改 JSON 檔**，檔案本身沒有問題。
  - stderr 同時含 `database is locked`：資料庫暫時被別的程序鎖住，等幾秒後用同一個檔案重跑 Step 2 **一次**。
    成功就照常進入 Step 3。
  - 其他原因，或重試後仍失敗：停止，回報 `[FAIL] handover write 執行失敗` 並附上 stderr 原文。
    到此結束，**跳過 Step 3**。
- 其他情況（未知欄位、型別錯誤、缺必填欄位、topic／summary 為空白、與指令列重複的欄位）：依錯誤訊息
  修正 JSON 檔後重跑。
- 修不好時停止，回報 `[FAIL] handover write 執行失敗` 並附上 stderr 原文。

不論哪一種情況，都**不要**改成把內容放回指令列。

未提供的環境 metadata 會自動偵測（`device` / `branch` / `project`）。

## Step 3 — 確認寫入

以 Step 2 寫入指令**自己的 stdout** 確認成功，不要另外跑 `read`（`read --last 1` 讀到的可能是別的
session 剛寫入的記錄）：

- 成功與否**只看** stdout 有沒有 `✓ handover 已寫入：<id>` 這一行。缺少這一行時，回報
  `[FAIL] handover 寫入結果無法確認` 並附上 stdout 原文。
- 有這一行時，再核對 topic：找出以 `topic` 開頭的那一行（實際輸出是縮排過的 `topic   = <topic>`，
  `topic` 與 `=` 之間有對齊用的空白），取 `=` 之後的值並去掉首尾空白；JSON 檔裡的 `topic` 先去掉
  首尾空白，再只取第一行（topic 含換行時，stdout 的 `topic` 行只會顯示第一行）。比對時忽略這些空白。
- topic 相符時，回報寫入成功並附上 `<id>`。
- topic 不符時，交班**已經寫入**（`✓` 行已出現），**不要重跑**（重跑會再寫一筆重複的交班）。回報
  `[WARN] 交班已寫入（id=<id>），但 topic 核對不符` 並附上 stdout 原文。
