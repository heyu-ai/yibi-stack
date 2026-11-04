---
type: feat
---

# Proposal：add-weekly-review-rule-loads

> 版本：v0.3 | 日期：2026-11-04 | 狀態：已實作；PR #628 完整 diff 重審後依 owner 裁決縮小宣稱（design.md D7），待下一輪 review
> 來源：yibi-mvp 2026-11-03 團隊會議「context 太肥」討論與其後續（yibi-mvp PR #2710）

## Summary

讓 harness-weekly-review 每週量出「每個 rule 檔與指令檔（根目錄與子目錄的 `CLAUDE.md`／`AGENTS.md`）在觀察期內**觀察到**被載入的 session 數」，寫進快照並在報告
最後一節列表，表頭附原始計數。資料來自 transcript 裡 Claude Code 自己記錄的兩種事件：`instructions`（session 開始時載入的指令檔）
與 `nested_memory`（讀到某路徑時才載入的 path-scoped rule 與子目錄 `CLAUDE.md`）。transcript 格式改變不保證自動偵測，
改由人比對表頭的原始計數。

## Motivation

既有的 rule 量測只有「成本」：每個 rule 檔的字元數、是否每次必載、哪些段落適合機械化。它回答不了「這條 rule
到底有沒有進過 context」。yibi-mvp 在縮減常駐 rule 時遇到三個只能靠載入次數回答的問題。以下數字取自同一份快照
（2026-11-04 量測、觀察期 14 天，量測指令與完整表見 design.md D3）。量測對象是 yibi-mvp 的
`worktree-trim-always-loaded-rules` 分支 checkout，不是 main。這份快照中已刪除 worktree 內的載入全部不計
（design.md D2 的限制），所以下列次數與分母都偏低：

1. **搬到子資料夾有沒有用？** 會議提議把 rule 搬進 `backend/`、`mobile/` 等子目錄延遲載入。該分支 37 個 rule 裡有
   30 個用 `paths:` 延遲載入（yibi-mvp main 為 35 個、28 個；差的兩個 incident-log 檔於 2026-11-03 才在該分支以
   commit `247f5ae11` 建立），但沒有數據說明它們實際多常被觸發。同一份快照裡有 15 個 path-scoped rule 兩週 0 次；
   其中 `15-retirement-sweep-incident-log.md` 是量測前一天才建立，不算兩週的觀察。
2. **path 有沒有寫錯？** yibi-mvp 的 `42-worktree-safety.md` 用 `paths: ".claude/worktrees/**"`，而多數 session 都在
   worktree 內執行。兩週內有載入專案指令的 24 個 session 中，它只載入 1 次。推論（未確認）：worktree session 的
   專案根目錄就是 worktree 本身，這個 glob 永遠對不上。沒有載入次數就看不出來。
3. **分母是什麼？** yibi-mvp 兩週內 130 個 session 裡，97 個是 Python Agent SDK 啟動的（`entrypoint`
   為 `sdk-py`），這份快照中它們一條專案指令都沒載入（單一 checkout 的一次量測）。若不分開計算，每次必載的 rule
   看起來只有 18%（24／130）的載入率。

## Proposed Solution

- 新增 `collect_rule_loads` collector：沿用既有的 `transcript_files` 與 `_read_lines`，依 sessionId 計數，把主 checkout
  與 `.claude/worktrees/<name>/`（名稱可含 `/`）的同一檔案正規化成同一個相對路徑，並依 entrypoint 記錄 session 數與
  其中載入了專案指令的 session 數。跨越觀察期起點的 session 以整個 session 計，觀察期以 `now` 為上界。
  worktree 名稱只取自 `git worktree list` 與 `.claude/worktrees/` 第一層的實際目錄（`collect_worktree_roots`），
  不從路徑或 transcript 目錄名稱推論；對不上的路徑（含已刪除的 worktree）不計，只記數量（design.md D2）。
- 來源完整性遵守既有的白名單語意（預設不完整），只在讀檔失敗、壞行、觀察期內 session 的 attachment 形狀不符、
  找不到 transcript、期內事件太少、rules 來源不完整、worktree 名稱列不出來時判為不完整。不以載入次數推論格式
  漂移（design.md D7）。
- 快照記錄原始計數（instructions 事件數、可解析與無法解析的 nested_memory 事件數、對不上的 worktree 路徑數等），
  報告表頭固定列出並註明「格式漂移不保證偵測」；有 session 卻沒看到任何 instructions 事件時加一行「注意」。
- 報告新增「rule 載入次數」一節；來源不完整時只寫「量不到」並直接列出原因，快照沒有這一節時寫明產生於此功能之前，
  都不印一張全是 0 的表。

## Non-Goals

- **不新增建議類型**（例如 `rule-never-loaded`）。新類型要同時改 `build_recommendations`、`evaluation_scope`、
  `resolution_evidence`、`diff_snapshots` 與失敗注入矩陣，`harden-weekly-review-measurement` 花了三輪才讓這些
  判定可信。先累積幾週資料，再決定門檻與是否需要。
- **不量「載入後有沒有照做」**。遵守率的探針綁定特定 rule 的字面內容，rule 改寫時會靜默失效，屬於各 repo 自己的
  一次性分析，不放進通用工具。
- **不自動偵測 transcript 格式漂移，不推論已刪除 worktree 的根目錄**。兩者在 PR #628 review 中同形狀出錯 5 次與
  4 次，且單週資料無法區分「壞了」與「這週沒發生」（design.md D7）。
- 不改 `SNAPSHOT_VERSION`：新欄位是附加的，舊快照缺這一節時報告寫明產生於此功能之前。
- 不新增 `InstructionsLoaded` hook 紀錄：transcript 已有結構化事件，另開資料源會多一個「紀錄中斷」的失效模式
  （同 `EVENTS_MAX_STALENESS` 處理的問題）。

## Alternatives Considered

- **用 regex 掃 transcript 原文的 `Contents of <path>` 字串**：否決。這是第一版一次性分析的作法，會同時命中
  `api-request-blob` 等重複記錄，也無法區分載入方式。改用結構化 attachment。
- **以所有 session 為分母**：否決。理由見 Motivation 第 3 點，SDK session 會把佔比稀釋到失去意義。
- **以載入次數或事件有無當格式對照**（任一條必載 rule 0 次、有 `cli` session 卻沒有 instructions、nested_memory
  事件為 0 等）：曾經實作，後來全數移除。理由與每個版本的失效見 design.md D7。
- **推論已刪除 worktree 的根目錄**（第一段、`/.claude/rules/` 錨點、transcript 目錄名稱）：曾經實作，後來全數移除，
  見 design.md D7。
