# Proposal：harden-weekly-review-measurement

> 版本：v0.2 | 日期：2026-10-03 | 狀態：Q1–Q4 已裁決，apply 中（裁決與實作時的修訂見 design.md）
> 來源：issue #509；前置：#504（原 skill）、#506（Round 2 修正，本 change 處理其 Accepted Residual Risk）

## Summary

把 harness-weekly-review 判定「上週建議已解除（resolved）」的規則，從「列舉會量不到的情況再排除」（黑名單）改成「每個資料來源明確證明自己完整、且該對象本週確實被觀察到，才可判 resolved」（白名單）。名稱歸因也改為只接受精確身分比對。

## Motivation

同一族問題已連續三輪出現：#504 Round 1 數條、#504 Round 2 有 7 條 Critical（由 #506 修正）、#506 Round 1 又有約 12 條同族漏網。依「同形狀累積到 3 次，停止逐條補、改為重新設計」的紀律，owner 已於 2026-09-30 裁決：#506 照現況 merge，剩下的問題以獨立 PR 重新設計。

2026-10-01 對 `8edb41d8`（#506 merge 後的 main）重新對照，issue 的 13 個 finding 全部仍然成立。共通的形狀有兩種：

1. **完整性旗標預設為 True，只有被列舉到的失敗才把它設成 False。** 例如 hook inventory 的 `complete` 起始為 True，讀不到 hook 腳本只加一行 warning（harness_review.py 的 collect_hook_inventory）。workflows 目錄用 `glob` 列舉，失敗時靜默回空。hook-events 讀檔沒有傳入 `failed` 收集器。每補一條失敗路徑，就還有下一條沒列到。
2. **resolved 不需要正向證據。** diff_snapshots 對「上週有、本週沒有」的建議，只要該類型在 evaluation scope 內就判 resolved，不檢查該對象本週有沒有被觀察到、樣本夠不夠。所以 hook 本週只被呼叫 2 次，上週的 hook-slow 就會被判 resolved。現有的 DT-029 正向對照甚至把這個行為寫成預期。

此外，evaluation_scope 的 docstring 宣稱「欄位缺漏一律當量不到」，但 `complete` 與 `workflows_complete` 缺漏時預設為 True，`ci.measured` 缺漏則直接拋 KeyError。文件與實作互相矛盾。

## Proposed Solution

三個設計方向，**每一個都需要 owner 裁決**（細節與待決問題見 design.md）：

1. **來源完整性白名單**：每個 collector 回傳 `complete`，預設 False。只有在目錄列舉、每個檔案讀取、每一行解析全部成功時才設為 True。列舉一律改用會回報錯誤的形式（取代 `glob` 的靜默回空、`os.walk` 沒有 `onerror`、未防護的 `iterdir`）。evaluation_scope 對缺漏的欄位一律視為量不到。
2. **resolved 需要正向證據**：一筆上週建議判為 resolved，必須同時滿足：(a) 該類型的資料來源本週完整；(b) 該對象本週被觀察到，且樣本達到該類型的門檻。缺任何一項就判 unmeasured 並保留（carried）。
3. **歸因只接受精確身分**：gate-silent 改用 workflow／job／step 的精確身分比對，移除 `stem in key` 這類子字串比對。名稱無法確定時（含 `${{ }}`、跳脫字元、多行 plain scalar）一律視為不可歸因。

並以**家族層級測試**取代逐條補洞：對每個 collector 注入四種讀取失敗（檔案、目錄、單行、API 回應形狀），斷言沒有任何上週建議變成 resolved，再以 mutation 確認每個注入點都有測試守住。

## Non-Goals

- 不新增建議類型，也不改既有建議的觸發門檻（例如 hook 的 `calls >= 3` 只用於產生新建議，維持不變）
- 不處理 #508 的 `weekly` 子命令。該 PR 疊在 #506 之上，本 change 實作時要 rebase 到包含 #508 的 main
- 不改 CI cache 的格式（CI_CACHE_SCHEMA 維持 2）

## Alternatives Considered

- **繼續逐條補黑名單**：否決。三輪實測證明每補一條就漏下一條；issue 中多數 finding 是 subagent 用 probe 才發現的，人工 review 不可靠。
- **只修 resolved 判定（方向 2），不動 collector（方向 1）**：否決。正向證據的前提是「本週完整觀察到」，collector 若在讀取失敗時仍回報 complete，方向 2 會建立在錯誤的完整性上。
- **讀取失敗直接讓整份報告 exit 2**：否決。一個 hook-events 月檔讀不到，不該讓 rules、CI 等完整來源的結論一起作廢；應該只讓受影響的建議類型變成 unmeasured。

## Impact

- Affected specs: weekly-review-measurement（新 capability）
- Affected code:
  - Modified: plugins/harness/skills/harness-weekly-review/scripts/harness_review.py
  - Modified: plugins/harness/skills/harness-weekly-review/SKILL.md
  - Modified: scripts/tests/test_harness_weekly_review.py
  - New: openspec/specs/weekly-review-measurement/spec.md（archive 時由 delta 產生）
