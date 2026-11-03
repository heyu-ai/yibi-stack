# Design：add-weekly-review-rule-loads

## D1 — 資料來源：transcript 的兩種 attachment

實測（yibi-mvp，Claude Code 2.1.316／2.1.317，2026-11-03）：

| attachment `type` | 何時出現 | 帶的路徑欄位 | 載入的內容 |
|---|---|---|---|
| `instructions` | session 開始（`reason: session_start` 或缺漏），設定變更時重載（`reason: account_change`，另帶 `removed`） | `files[].path`，`files[].type` 為 `Project` 或 `User` | 根目錄 `CLAUDE.md`／`AGENTS.md`、沒有 `paths:` 或 `paths: "**"` 的 rule、`~/.claude/CLAUDE.md`（`User`） |
| `nested_memory` | 工具第一次碰到符合 `paths:` 的檔案時 | `path` | path-scoped rule、子目錄 `CLAUDE.md` |

確認方式：在最近 60 份 transcript 中，每次必載的 `14-retirement-residual-sweep.md` 只出現在 `instructions`（26 次），
從未出現在 `nested_memory`。

## D2 — 計數單位與正規化

- 單位是 sessionId，每個 rule 對應一個 session 集合。同一 session 重載、或同一事件在主 checkout 與 worktree 的
  transcript 各出現一次，都不會重複計數；因此不需要像 `collect_transcript_blocks` 那樣依 uuid 去重。
- 路徑：去掉 `<main_repo>/` 與 `<main_repo>/.claude/worktrees/<name>/` 前綴後，只收 `.claude/rules/<file>.md`
  （rule）與 `**/CLAUDE.md`、`**/AGENTS.md`（指令檔）。不在 repo 底下的路徑不計。
- `instructions.files[].type == "User"` 不計。這不能只靠路徑判斷：repo 就是家目錄時（dotfiles repo），
  `~/.claude/CLAUDE.md` 也在 repo 底下。
- 只計觀察期內（`timestamp >= since`）的事件。

## D3 — 分母

實測（yibi-mvp，2026-10-20 起兩週，主 repo 與其 worktree 的 transcript）：

| entrypoint | session 數 | 有 `instructions` 事件 | 看得到 rule 14 |
|---|---:|---:|---:|
| `cli` | 25 | 25 | 25 |
| `sdk-cli` | 2 | 2 | 2 |
| `sdk-py` | 91 | 0 | 0 |

所以佔比的分母是「觀察期內有 `instructions` 事件的 session 數」，報告另依 entrypoint 列出兩個數字。`sdk-py`
session 為什麼不載入專案指令不在本 change 範圍；報告讓它看得見即可。

## D4 — 來源完整性與格式對照

沿用 `make_source`：任一檔案讀取失敗、任一行不是合法 JSON、找不到 transcript、或 `rules` 來源不完整，都使本來源
不完整。另加格式對照，前提是觀察期內至少有一個 `entrypoint` 含 `cli` 的 session：

- 沒有任何 `instructions` 事件 → 不完整
- `collect_rules` 判定為每次必載的 rule 有任一條 0 次 → 不完整

對照只在全部失效時觸發，不會抓到「部分 session 的格式不同」。後者的偵測依賴報告上的 entrypoint 分母：每次必載
的 rule 佔比若明顯低於 100%，就是訊號。這是已知的剩餘風險，不另加門檻，以免在新增 rule 的那一週誤判。

「找不到 transcript」不重複發 warning，因為 `collect_transcript_blocks` 已經發過；其他錯誤照常進 `warnings`，
使 `collect` 回傳 3。

## D5 — 報告

報告最後新增「rule 載入次數（本期，以 session 計）」：

- 表頭：session 總數、有載入專案指令的 session 數、依 entrypoint 的兩個數字
- rule 表：每次必載或前 3 個 `paths:` pattern、session 數、佔比；硬碟上存在但 0 次的 rule 與已不存在但有載入紀錄的
  rule 都列出
- 子目錄指令檔表：依 session 數排序
- 來源不完整，或快照沒有 `rule_loads`（本 change 之前的快照）：只寫「量不到」

## 驗證

- 單元與端對端測試：HWR-DT-080..083、HWR-ST-026、HWR-ST-027（見測試檔開頭的覆蓋對映）
- mutation：對 9 個單點各做一次突變，全數被新測試抓到；兩個先前存活的突變分別導致刪掉無作用的 uuid 去重，
  以及把使用者層指令檔的測試改放在 repo 路徑底下
- 真實資料：對 yibi-mvp 兩週 transcript 執行 `collect` 與 `report`，7 條每次必載的 rule 皆為 28/28
