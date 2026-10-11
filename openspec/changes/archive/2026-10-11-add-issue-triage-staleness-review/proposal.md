## Why

issue-triage 目前的偏誤是單向的：只防「誤關」，沒有任何機制對抗「堆積」。三個具體缺口讓過期 issue 永遠關不掉，且判斷依據可能不可信：

1. **沒有「前提已消失」的結論。** CLOSE 要求所有症狀都 DONE；功能被移除、模組改名的 issue，症狀既非 DONE 也非 NOT DONE，加上 UNCLEAR 視同 NOT DONE、存疑傾向 KEEP，這類 issue 只會落進 KEEP。
2. **久未更新被當成降優先的理由，而不是重新檢視前提的理由。** Step 6 的「時效」訊號與 FAQ 的 close-as-stale 條目都把「長期無活動」導向降優先；Step 3c′ 雖寫了「越舊的 issue 越要查」，卻沒有門檻也沒有對應動作。`updatedAt` 與 `createdAt` 已被抓取，但完全沒進入任何判斷。
3. **查證基準沒有固定。** Step 3b 的探索 subagent 對本機 checkout 做 grep，但沒有要求先 fetch，也沒有確認 checkout 等於 origin/main。本機 main 落後、或停在別的 feature 分支時，「已修」與「未修」都可能判反。

## What Changes

- 新增 **OBSOLETE** verdict：issue 引用的前提（檔案、符號、功能、change）在 origin/main 基準上已被證實不存在，才可成立；建議以「not planned」關閉，不得以「completed」關閉。
- 新增 **STALE-CANDIDATE** verdict：只能由原本會落在 KEEP 的 issue 升級而來；行動是提議貼出「仍需要嗎」提醒並進入寬限期；寬限期滿且無人為活動時，才升為「建議關閉」。任何情況都不得僅憑天數關閉。
- 用「最後一次實質人為活動」與「程式碼漂移」決定**檢視深度**：天數分層（30／90／180 天為初始值，首次執行與使用者校準）決定要多查什麼；程式碼漂移（issue 引用的路徑自建立以來被刪除、改名或大量變動）作為比天數更直接的過期訊號。
- skill 自己貼出的所有留言一律帶辨識標記，且該標記不計入「人為活動」，避免盤點動作自己重置時鐘；STALE-CANDIDATE 的狀態也記在 issue 上（提醒留言的標記加時間），skill 本身維持無狀態。
- 新增**豁免**：security label、已有 assignee、milestone 尚未到期、綁定進行中的 change、維護者（以 authorAssociation 判定）的 keep-open 留言。
- 修改 Step 6：「時效」訊號不得僅因久未更新就降低一個嚴重且未解的 issue 的優先級；FAQ 的 close-as-stale 條目同步改寫，避免與新 verdict 矛盾。
- 新增**證據基準前置步驟**：Step 3b 之前必須 fetch origin/main，並確認被檢視的程式碼就是 origin/main 的內容；fetch 失敗或基準不符時 fail loud 停止，報告頂端記錄基準 commit。
- 決策表優先序改為：MERGE > CLOSE > OBSOLETE > UPDATE-SCOPE > STALE-CANDIDATE > KEEP。
- 三支輔助腳本承載多步驟邏輯（基準檢查、過期訊號蒐集、最後人為活動蒐集），SKILL.md 只留單一 bash 呼叫；腳本附 negative control 測試。第三支是 apply 階段實測發現 gh JSON 會去掉 bot 帳號的 [bot] 後綴、必須改用 REST 帳號型別判定後補上的。

## Non-Goals (optional)

以下是同一份分析找到、但**刻意不在本 change** 處理的缺口，列出以免被誤認為已解決，各自應另開 change：

- 決策表的缺口（「全部症狀 DONE 但有 keep-open 留言」沒有對應列、keep-open 與 close-authorization 同時出現的決勝規則、MERGE 的鏈式解析）。
- close-authorization 留言的來源身分檢查，以及把 issue 內容視為不受信任輸入的處理。
- 「--limit 300」與 Jira 查詢的截斷與分頁。
- 跨次盤點的紀錄與差異比對。
- 優先級排序的權重與決勝規則（本 change 只修正「時效」與新 verdict 之間的矛盾）。
- Jira bug 的過期判斷：Jira 的 updated 欄位、留言者與自動化帳號的語意與 GitHub 不同，需要獨立設計；本 change 只涵蓋 GitHub issue。
- fork 情境下以 upstream 為基準：本 change 的基準固定為 origin/main，fork 的 origin 落後 upstream 的處理留待後續。
- 純依天數自動關閉：明確否決。理由是真實 bug 會因為沒人處理而被關掉，且違反本 skill 的「誤關成本高於留著」原則。

## Capabilities

### New Capabilities

- `issue-triage-staleness-review`: OBSOLETE 與 STALE-CANDIDATE verdict、最後實質人為活動的度量、程式碼漂移訊號、天數分層的檢視深度、豁免條件、寬限期狀態機、時效與優先級的關係。
- `issue-triage-evidence-baseline`: 驗證程式碼症狀之前必須 fetch origin/main 並確認檢視對象即 origin/main；失敗時 fail loud；報告記錄基準 commit。

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 issue-triage-staleness-review 與 issue-triage-evidence-baseline 兩個 capability（目前 openspec/specs 沒有任何 issue-triage 相關 spec）。
- Affected code:
  - Modified: plugins/dev-cycle/skills/issue-triage/SKILL.md
  - Modified: skills/README.md（僅在 description 文字變動時更新索引列）
  - New: plugins/dev-cycle/skills/issue-triage/scripts/check-baseline.sh
  - New: plugins/dev-cycle/skills/issue-triage/scripts/staleness-signals.sh
  - New: plugins/dev-cycle/skills/issue-triage/scripts/last-human-activity.sh
  - New: plugins/dev-cycle/skills/issue-triage/scripts/tests/test_last_human_activity.py
  - New: plugins/dev-cycle/skills/issue-triage/scripts/tests/test_check_baseline.py
  - New: plugins/dev-cycle/skills/issue-triage/scripts/tests/test_staleness_signals.py
  - New: plugins/dev-cycle/skills/issue-triage/scripts/tests/test_skill_contract.py
  - New: openspec/changes/add-issue-triage-staleness-review/testplan.md
  - Modified: plugins/sdd/scripts/check_testplan_trace.py（範圍追加，見 Review Contract AC-14）
  - Modified: plugins/sdd/scripts/tests/test_check_testplan_trace.py（回歸測試 TPT-ST-009 到 014）
  - Removed: (none)
- 動到 plugins 下的檔案，發版時需走 plugin 版本 lockstep bump，由 PR 流程處理，不在本 change 內執行 make release。
