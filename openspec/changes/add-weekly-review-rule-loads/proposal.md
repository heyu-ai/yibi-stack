---
type: feat
---

# Proposal：add-weekly-review-rule-loads

> 版本：v0.1 | 日期：2026-11-03 | 狀態：已實作，待 review
> 來源：yibi-mvp 2026-11-03 團隊會議「context 太肥」討論與其後續（yibi-mvp PR #2710）

## Summary

讓 harness-weekly-review 每週量出「每個 rule 檔與指令檔（根目錄與子目錄的 `CLAUDE.md`／`AGENTS.md`）實際被載入的 session 數」，寫進快照並在報告
最後一節列表。資料來自 transcript 裡 Claude Code 自己記錄的兩種事件：`instructions`（session 開始時載入的指令檔）
與 `nested_memory`（讀到某路徑時才載入的 path-scoped rule 與子目錄 `CLAUDE.md`）。

## Motivation

既有的 rule 量測只有「成本」：每個 rule 檔的字元數、是否每次必載、哪些段落適合機械化。它回答不了「這條 rule
到底有沒有進過 context」。yibi-mvp 在縮減常駐 rule 時遇到三個只能靠載入次數回答的問題。以下數字取自同一份快照
（2026-11-03 量測、觀察期 14 天，量測指令與完整表見 design.md D3）：

1. **搬到子資料夾有沒有用？** 會議提議把 rule 搬進 `backend/`、`mobile/` 等子目錄延遲載入。實測 37 個 rule 裡已有
   30 個用 `paths:` 延遲載入，但沒有數據說明它們實際多常被觸發；同一份快照裡有 5 個兩週 0 次。
2. **path 有沒有寫錯？** yibi-mvp 的 `42-worktree-safety.md` 用 `paths: ".claude/worktrees/**"`，而多數 session 都在
   worktree 內執行。兩週內有載入專案指令的 30 個 session 中，它只載入 1 次。推論（未確認）：worktree session 的
   專案根目錄就是 worktree 本身，這個 glob 永遠對不上。沒有載入次數就看不出來。
3. **分母是什麼？** yibi-mvp 兩週內 127 個 session 裡，96 個是 Python Agent SDK 啟動的（`entrypoint`
   為 `sdk-py`），它們一條專案指令都沒載入。若不分開計算，每次必載的 rule 看起來只有 23%（30／127）的載入率。

## Proposed Solution

- 新增 `collect_rule_loads` collector：沿用既有的 `transcript_files` 與 `_read_lines`，依 sessionId 計數，把主 checkout
  與 `.claude/worktrees/<name>/`（名稱可含 `/`）的同一檔案正規化成同一個相對路徑，並依 entrypoint 記錄 session 數與
  其中載入了專案指令的 session 數。跨越觀察期起點的 session 以整個 session 計。
- 來源完整性遵守既有的白名單語意（預設不完整），另加一個領域對照：觀察期內有 `entrypoint` 等於 `cli` 的 session，
  卻看不到任何 `instructions` 事件，或每次必載的 rule 一條都沒有載入，就判定 transcript 格式可能已改變，來源不完整。
  只有部分必載 rule 為 0 次時（期間才新增或剛改成必載）只在報告列出，不判為不完整。
- 報告新增「rule 載入次數」一節；來源不完整或快照沒有這一節時，只寫「量不到」，不印一張全是 0 的表。

## Non-Goals

- **不新增建議類型**（例如 `rule-never-loaded`）。新類型要同時改 `build_recommendations`、`evaluation_scope`、
  `resolution_evidence`、`diff_snapshots` 與失敗注入矩陣，`harden-weekly-review-measurement` 花了三輪才讓這些
  判定可信。先累積幾週資料，再決定門檻與是否需要。
- **不量「載入後有沒有照做」**。遵守率的探針綁定特定 rule 的字面內容，rule 改寫時會靜默失效，屬於各 repo 自己的
  一次性分析，不放進通用工具。
- 不改 `SNAPSHOT_VERSION`：新欄位是附加的，舊快照缺這一節時報告顯示「量不到」。
- 不新增 `InstructionsLoaded` hook 紀錄：transcript 已有結構化事件，另開資料源會多一個「紀錄中斷」的失效模式
  （同 `EVENTS_MAX_STALENESS` 處理的問題）。

## Alternatives Considered

- **用 regex 掃 transcript 原文的 `Contents of <path>` 字串**：否決。這是第一版一次性分析的作法，會同時命中
  `api-request-blob` 等重複記錄，也無法區分載入方式。改用結構化 attachment。
- **以所有 session 為分母**：否決。理由見 Motivation 第 3 點，SDK session 會把佔比稀釋到失去意義。
- **以「任何 session 都必須看到每次必載的 rule」當格式對照**：否決。一整週只有 SDK session 時會誤判格式改變；
  對照的前提改為「互動式 CLI session 一定會載入專案指令」。
