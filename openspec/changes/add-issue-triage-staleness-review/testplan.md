# add-issue-triage-staleness-review — Test Plan

trace: enforced

本 testplan 在 PR #532 的 pre-review check（amplifier-verify）擋下「feat 缺 testplan」後補上，追溯**已存在**的測試，
並新增一組 SKILL.md 文字契約測試；它不聲稱 agent 執行期行為已通過驗證。
Review Contract AC-1～AC-14 已由 howie 確認。

## 可測性前提（讀 TC 表之前必讀）

本 change 的行為分成兩層，證明力不同：

| 層 | 對象 | 能證明什麼 | 不能證明什麼 |
|----|------|-----------|--------------|
| 腳本層（`ITB`／`ITD`／`ITA`） | 三支 shell 腳本，以真實 git repo 與假 `gh`（回放 REST 形狀的 JSON）執行 | 腳本行為本身：exit code、輸出格式、守衛是否會擋下壞輸入 | agent 會不會在對的時機呼叫它們 |
| runbook 層（`ITS`，`[doc]`） | SKILL.md 的文字 | runbook **有明文寫**這條規則，且舊的、已被推翻的措辭沒有被寫回來 | **agent 在任意未來 issue 上會不會遵守**（OBSOLETE 的證據判斷、寬限期狀態機、豁免、優先級都是 agent 執行期行為） |

所以 Coverage 中凡是依賴 agent 執行期判斷的 scenario 一律標 `partial`，並指向 Manual Verification。
`ITS` 測試的 PASS 不得被讀成行為證明。

三支腳本各自做過單點突變驗證（記錄於 commit `3d0d08c9`、`83cd4509`、`2f446f92`）。`ITS` 另有突變自檢（`ITS-EG-014`、`ITS-EG-015`、`ITS-EG-016`）：
把任一錨點從真實 SKILL.md 的所有出現處移除、或把舊措辭注入，檢查器必須變紅。

## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| baseline-script | check-baseline.sh，在拋棄式 git repo（bare origin 加 clone）內以 subprocess 執行 | 基準檢查的全部行為都在 exit code 與 stdout／stderr；不 mock 本 repo 模組 |
| drift-script | staleness-signals.sh，在帶受控 commit 時間的真實 git 歷史上執行 | 狀態（unchanged、changed、deleted、renamed、never-existed）只能由 git 歷史產生，假的 git 會讓測試失去意義 |
| activity-script | last-human-activity.sh，PATH 上放假的 gh 回放 REST 形狀的 JSON | 外部邊界只有 gh；JSON 形狀取自 cli/cli 的實測，不 mock 本 repo 模組 |
| skill-runbook-doc | plugins/dev-cycle/skills/issue-triage/SKILL.md 的文字 | runbook 是 agent 的執行介面；只能斷言規則「有寫」，不能斷言「會遵守」 |

## TC Table

| TC-ID | Kind | Seam | Scenario Slug | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|------|------|---------------|--------------|-----------|------|--------------|-------|-----------|-----------------|
| ITB-ST-001 | auto | baseline-script | clean-and-equal | 乾淨且等於 origin/main 通過並輸出基準 | ST | High | 乾淨 clone | 執行腳本 | 無 | exit 0；stdout 為 BASELINE_SHA 加 FETCHED_AT |
| ITB-ST-002 | auto | baseline-script | checkout-is-behind | 本機未 fetch 就偵測到落後 | ST | High | origin 前進 3 個 commit、本機未 fetch | 執行腳本 | behind=3 | exit 4；stderr 含 behind=3；stdout 為空 |
| ITB-ST-003 | auto | baseline-script | checkout-is-on-an-unmerged-branch | 領先 origin/main 的 commit 被擋下 | ST | High | 本機多 2 個 commit | 執行腳本 | ahead=2 | exit 4；stderr 含 ahead=2 |
| ITB-ST-004 | auto | baseline-script | tracked-file-modified | tracked 檔案有未提交修改 | ST | High | 修改 tracked 檔案 | 執行腳本 | modified=1 | exit 5；stderr 含檔案數與檔名 |
| ITB-ST-005 | auto | baseline-script | fetch-fails | fetch 失敗不回退本機 ref | ST | High | origin URL 無效，且本機 ref 恰等於 HEAD | 執行腳本 | 不存在的 remote | exit 3；stdout 為空 |
| ITB-DT-006 | auto | baseline-script | each-failure-is-distinguishable | 四種失敗是四個互異的非 0 code | DT | High | 四個 fixture | 各執行一次 | 不在 repo／fetch 失敗／落後／tracked 修改 | 2、3、4、5 |
| ITB-EG-007 | auto | baseline-script | each-failure-is-distinguishable | 不在 git repo | EP | Medium | 一般目錄 | 執行腳本 | 無 .git | exit 2；stdout 為空 |
| ITB-EG-008 | auto | baseline-script | clean-and-equal | untracked 檔案不使檢查失敗 | EP | Medium | 工作樹有 untracked 檔 | 執行腳本 | scratch.txt | exit 0 |
| ITB-ST-006 | auto | baseline-script | hidden-tracked-modification | assume-unchanged 隱藏的 tracked 修改被擋下 | ST | High | 檔案設 assume-unchanged 後被改寫，status 為空 | 執行腳本 | LOCAL TAMPER | exit 5；stderr 含 modified=1 與檔名 |
| ITB-ST-007 | auto | baseline-script | hidden-tracked-modification | skip-worktree 隱藏的 tracked 修改被擋下 | ST | High | 檔案設 skip-worktree 後被改寫，status 為空 | 執行腳本 | LOCAL TAMPER | exit 5；stderr 含檔名 |
| ITB-ST-008 | auto | baseline-script | hidden-tracked-modification | 旗標但內容等於 HEAD、sparse 缺檔都通過（對照） | EP | High | assume-unchanged 未改動的檔案；skip-worktree 且已從磁碟移除的檔案 | 執行腳本 | sparse.txt | exit 0 |
| ITB-ST-009 | auto | baseline-script | fetch-succeeds | 本機同名分支 origin/main 不蓋過遠端 ref，ambiguity warning 不混進訊息 | ST | Medium | 本機分支 origin/main 指向別的 commit；之後 origin 前進 1 個 | 執行腳本兩次 | 同名分支 | 第一次 exit 0 且 BASELINE_SHA 為遠端 SHA；第二次 exit 4，stderr 為 ahead=0 behind=1 且不含 warning |
| ITD-ST-001 | auto | drift-script | referenced-file-was-deleted | 已刪除的路徑回報刪除它的 commit | ST | High | 檔案於建立後被刪除 | 執行腳本 | src/legacy.py | deleted 加刪除 commit SHA |
| ITD-ST-002 | auto | drift-script | referenced-file-changed-repeatedly | 只計建立之後的 commit 數 | ST | High | 建立前 1 次、建立後 3 次修改 | 執行腳本 | src/hot.py | changed 加 3 |
| ITD-ST-003 | auto | drift-script | issue-references-no-paths | 沒有路徑時是 NOT_APPLICABLE | EP | Medium | 有 origin/main | 不帶路徑執行 | 無 | stdout 為 NOT_APPLICABLE |
| ITD-ST-005 | auto | drift-script | referenced-file-changed-repeatedly | 從 repo 子目錄執行時路徑仍是根目錄相對 | EP | High | 檔案在 sub/ 內，建立後被動過一次 | 從根目錄與從 sub/ 各執行一次，引數相同 | sub/x.txt、sub/y.txt | 兩次輸出相同：changed 加 1、unchanged |
| ITD-ST-004 | auto | drift-script | never-existed-path-is-not-evidence-of-absence | 從未存在的路徑回報 never-existed | EP | Medium | 路徑從未出現 | 執行腳本 | src/typo_path.py | never-existed |
| ITA-ST-001 | auto | activity-script | issue-without-comments | 無留言時取 issue 建立時間 | BVA | High | 空留言陣列 | 執行腳本 | 無 | 輸出 issue 建立時間 |
| ITA-ST-002 | auto | activity-script | bot-comment-does-not-reset-the-clock | type 為 Bot 的留言被排除 | DT | High | github-actions[bot] 的新留言 | 執行腳本 | 3 天前的 bot 留言 | 取較舊的人為留言時間 |
| ITA-ST-003 | auto | activity-script | bot-account-without-a-login-suffix | 沒有後綴的 bot 仍被排除 | DT | High | Copilot（type 為 Bot） | 執行腳本 | login 無 [bot] | 取較舊的人為留言時間 |
| ITA-ST-004 | auto | activity-script | deleted-author-counts-as-human | 已刪除帳號算人為活動 | EP | Medium | user 為 null | 執行腳本 | 無 user | 該留言時間被採用 |
| ITA-ST-005 | auto | activity-script | triage-comment-does-not-reset-the-clock | 標記加上目前帳號才是 skill 的留言 | DT | High | 目前帳號貼出帶標記的留言 | 執行腳本 | close 標記 | 該留言不計入 |
| ITA-ST-006 | auto | activity-script | pasted-marker-from-another-account-counts-as-activity | 他人貼上標記仍算活動 | DT | High | 另一帳號貼出帶標記的留言 | 執行腳本 | mallory 加標記 | 該留言時間被採用 |
| ITA-ST-007 | auto | activity-script | grace-period-elapsed-without-response | stale notice 時間單獨回報且不計入活動 | ST | High | 目前帳號貼出 stale notice | 執行腳本 | stale-notice 標記 | 第二欄為 notice 時間；第一欄不含它 |
| ITA-ST-008 | auto | activity-script | stale-notice-marker-from-another-account-is-ignored | 他人的 notice 標記不被辨識 | DT | High | 另一帳號貼出 notice 標記 | 執行腳本 | mallory 加標記 | 第二欄為空；該留言算活動 |
| ITA-EG-009 | auto | activity-script | comment-lookup-fails-for-one-issue | 取不到目前帳號時失敗而不回退 | EP | High | 假 gh 讓 api user 失敗 | 執行腳本 | FAKE_GH_FAIL=user | exit 3；stdout 為空 |
| ITA-ST-009 | auto | activity-script | incomplete-marker-is-human-activity | 內文只提到標記前綴（無日期、無結尾）的留言算人為活動 | DT | High | 目前帳號貼出含前綴文字的留言 | 執行腳本 | parser token 是 前綴 | 該留言時間被採用；第二欄為空 |
| ITA-ST-010 | auto | activity-script | incomplete-marker-is-human-activity | 長得像的種類不是已知標記 | DT | High | 最後一行是 stale-notice-foo、stale-noticex、closed、unknown-kind 的標記 | 執行腳本 | 四種 look-alike | 各自算人為活動；第二欄為空 |
| ITA-ST-011 | auto | activity-script | incomplete-marker-is-human-activity | 完整標記在內文中段、後面還有文字不算標記 | DT | High | 標記後接一行補充 | 執行腳本 | 標記加後續文字 | 該留言時間被採用 |
| ITA-ST-012 | auto | activity-script | grace-period-elapsed-without-response | 對照：CRLF 與尾端空白行的真標記仍被辨識 | EP | High | 網頁編輯器格式的 stale notice | 執行腳本 | CRLF 加空白行 | 第二欄為 notice 時間；第一欄不含它 |
| ITA-ST-013 | auto | activity-script | incomplete-marker-is-human-activity | 最後一行前後有別的文字（前綴、後綴、引用符號）不算標記 | DT | High | 最後一行為文字加標記、標記加文字、引用標記 | 執行腳本 | 三種形狀 | 各自算人為活動 |
| ITS-DT-001 | auto | skill-runbook-doc | jira-only-run | [doc] Step 1c 在 Step 2 之前且涵蓋 Jira-only，exit 0 到 5 各一列 | DT | High | 真實 SKILL.md | 讀取並比對錨點 | 無 | 錨點與順序皆成立 |
| ITS-DT-002 | auto | skill-runbook-doc | report-header | [doc] 報告模板第一區塊是證據基準 | DT | Medium | 真實 SKILL.md | 讀取並比對 | 無 | 證據基準在來源之前 |
| ITS-DT-003 | auto | skill-runbook-doc | closing-note-carries-the-marker | [doc] 各留言模板都明寫 triage 標記 | DT | High | 真實 SKILL.md | 讀取並比對 | close、update-scope、merge、stale-notice | 四種標記錨點在場 |
| ITS-DT-004 | auto | skill-runbook-doc | tier-2-keep-requires-affirmative-evidence | [doc] 分層表、邊界與 premise-unverified | DT | High | 真實 SKILL.md | 讀取並比對 | 29／30／89／90／179／180 | 四列與邊界句在場 |
| ITS-DT-005 | auto | skill-runbook-doc | premise-artifacts-removed-with-positive-control | [doc] OBSOLETE 的證據標準 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 正向對照、UNCLEAR、not planned 錨點在場 |
| ITS-DT-006 | auto | skill-runbook-doc | first-stale-candidate | [doc] 寬限期狀態機與寫入前重新量測 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 14 天、已辨識的 notice、重新呼叫錨點在場 |
| ITS-DT-007 | auto | skill-runbook-doc | assigned-issue-is-exempt | [doc] 五種豁免與其邊界 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | assignees、dueOn、authorAssociation 錨點在場 |
| ITS-DT-008 | auto | skill-runbook-doc | all-symptoms-done-and-premise-also-gone | [doc] 新優先序，舊優先序不得出現 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 新優先序在場、舊優先序不存在 |
| ITS-DT-009 | auto | skill-runbook-doc | old-severe-bug-keeps-its-priority | [doc] 久未更新不降優先 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | review-urgency 在場、「KEEP 並降優先」不存在 |
| ITS-DT-010 | auto | skill-runbook-doc | scheduled-run | [doc] 新寫入動作 opt-in，排程只進報告 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 錨點在場 |
| ITS-DT-011 | auto | skill-runbook-doc | old-jira-bug | [doc] 過期 verdict 只適用 GitHub issue | DT | Medium | 真實 SKILL.md | 讀取並比對 | 無 | 錨點在場 |
| ITS-DT-012 | auto | skill-runbook-doc | comment-lookup-fails-for-one-issue | [doc] 過期資料取不到時 fail-safe | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 錨點在場 |
| ITS-DT-013 | auto | skill-runbook-doc | never-existed-path-is-not-evidence-of-absence | [doc] 沒有漂移訊號不是前提仍成立的證據 | DT | High | 真實 SKILL.md | 讀取並比對 | 無 | 錨點在場 |
| ITS-EG-014 | auto | skill-runbook-doc | age-alone-never-closes | 突變自檢：一次只移除錨點的一個出現處；段落內的那一處變紅，段落外的不影響 | EP | High | 真實 SKILL.md | 對每個錨點的每個出現處逐一移除 | 全部錨點 | 段落內的移除使檢查器回報該錨點；段落外的移除不改變結果 |
| ITS-DT-014 | auto | skill-runbook-doc | all-symptoms-done-and-premise-also-gone | [doc] 決策表 guard 與每一列的逐列錨點 | DT | High | 真實 SKILL.md | 讀取並在決策表段落內比對 | 兩個 guard 列、列 1 到 8、RELABEL | 單一欄位（天數、not planned、無豁免）被改掉時變紅 |
| ITS-EG-015 | auto | skill-runbook-doc | old-severe-bug-keeps-its-priority | 突變自檢：注入舊措辭檢查器必須抓到 | EP | High | 真實 SKILL.md | 注入舊優先序、舊 FAQ 句 | 三個舊措辭 | 檢查器回報該措辭，原文本身乾淨 |
| ITS-EG-016 | auto | skill-runbook-doc | age-alone-never-closes | 每個錨點在負責段落內恰好出現一次 | EP | Medium | 真實 SKILL.md | 計算錨點在段落內的出現次數 | 全部錨點 | 每個錨點恰好一次；否則「移除它」沒有明確意義 |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| fetch-succeeds | covered | ITB-ST-002, ITB-ST-009 | 本機未 fetch 就偵測到落後，證明腳本自己 fetch；ITB-ST-009 證明用完整 ref，同名本機分支不干擾 |
| fetch-fails | covered | ITB-ST-005 | 不回退本機 ref；突變驗證（移除 fetch）6 個測試轉紅 |
| jira-only-run | partial | ITS-DT-001 | runbook 有寫；實際執行期見 MV-001 |
| checkout-is-behind | covered | ITB-ST-002 | |
| checkout-is-on-an-unmerged-branch | covered | ITB-ST-003 | |
| tracked-file-modified | covered | ITB-ST-004 | |
| hidden-tracked-modification | covered | ITB-ST-006, ITB-ST-007, ITB-ST-008 | assume-unchanged 與 skip-worktree 各一，另有旗標但內容相同與 sparse 缺檔的對照；突變（旗標清單只留 S、只留小寫）各被擊殺 |
| clean-and-equal | covered | ITB-ST-001, ITB-EG-008 | 含 untracked 不失敗 |
| each-failure-is-distinguishable | covered | ITB-DT-006, ITB-EG-007 | |
| passing-baseline | covered | ITB-ST-001 | |
| report-header | partial | ITS-DT-002 | 模板有寫；報告實際產出屬執行期，MV-001 |
| short-circuited-check-is-detected | covered | ITB-ST-002, ITB-ST-004, ITB-ST-005, ITB-DT-006 | 突變驗證：整支短路成 exit 0 時 10 個測試轉紅（commit 3d0d08c9） |
| triage-comment-does-not-reset-the-clock | covered | ITA-ST-005 | |
| pasted-marker-from-another-account-counts-as-activity | covered | ITA-ST-006 | |
| bot-comment-does-not-reset-the-clock | covered | ITA-ST-002 | 並以 cli/cli 真實 issue 核對 |
| bot-account-without-a-login-suffix | covered | ITA-ST-003 | |
| deleted-author-counts-as-human | covered | ITA-ST-004 | |
| issue-without-comments | covered | ITA-ST-001 | |
| closing-note-carries-the-marker | partial | ITS-DT-003 | 模板有寫；實際貼出的留言屬執行期，MV-003 |
| scope-update-carries-the-marker | partial | ITS-DT-003 | 同上 |
| tier-2-keep-requires-affirmative-evidence | partial | ITS-DT-004 | 證據判斷屬 agent 執行期，MV-001 |
| tier-2-keep-without-affirmative-evidence-is-flagged | partial | ITS-DT-004 | 同上 |
| tier-1-collects-drift-only | partial | ITS-DT-004 | 同上 |
| referenced-file-was-deleted | covered | ITD-ST-001 | |
| referenced-file-changed-repeatedly | covered | ITD-ST-002, ITD-ST-005 | ITD-ST-005：從子目錄執行路徑仍是根目錄相對 |
| issue-references-no-paths | partial | ITD-ST-003, ITS-DT-013 | 腳本輸出 NOT_APPLICABLE 已測；「不是證據」由 runbook 規定，只有 `[doc]` 層 |
| never-existed-path-is-not-evidence-of-absence | partial | ITD-ST-004, ITS-DT-013 | 腳本層回報 never-existed 已測；「不是消失的證據」只有 runbook 的 `[doc]` 層，agent 是否遵守見 MV-001 |
| premise-artifacts-removed-with-positive-control | partial | ITS-DT-005 | 正向對照屬 agent 執行期，MV-002 |
| zero-hits-without-positive-control | partial | ITS-DT-005 | 同上 |
| partial-loss-of-premise | partial | ITS-DT-005 | 同上 |
| first-stale-candidate | partial | ITS-DT-006, ITS-DT-014 | 狀態機屬 agent 執行期，MV-003 |
| grace-period-elapsed-without-response | partial | ITA-ST-007, ITA-ST-012, ITS-DT-006 | notice 時間由腳本回報；GitHub 無法回填留言時間，寬限期滿路徑無法端到端驗證 |
| human-responds-during-grace-period | partial | ITS-DT-006 | 同上，MV-003 |
| stale-notice-marker-from-another-account-is-ignored | covered | ITA-ST-008 | |
| age-alone-never-closes | partial | ITS-DT-006, ITS-EG-014 | 錨點在場且有突變自檢；agent 是否遵守見 MV-003 |
| reply-arrives-between-the-verdict-and-the-write | partial | ITS-DT-006 | 寫入前重新量測有寫；執行期見 MV-003 |
| assigned-issue-is-exempt | partial | ITS-DT-007 | 豁免判斷屬執行期，MV-001 |
| keep-open-comment-from-a-non-maintainer | partial | ITS-DT-007 | 同上 |
| all-symptoms-done-and-premise-also-gone | partial | ITS-DT-008, ITS-DT-014 | 優先序有寫；套用屬執行期 |
| duplicate-of-another-issue-and-stale | partial | ITS-DT-008 | 同上 |
| old-severe-bug-keeps-its-priority | partial | ITS-DT-009, ITS-EG-015 | 錨點與舊措辭突變自檢；排序結果屬執行期，MV-001 |
| scheduled-run | partial | ITS-DT-010 | 文字有寫；排程情境實際行為，MV-004 |
| apply-run-with-confirmation | partial | ITS-DT-010 | 同上，MV-003 |
| incomplete-marker-is-human-activity | partial | ITA-ST-009, ITA-ST-010, ITA-ST-011, ITA-ST-013, ITS-DT-003 | 腳本層四種不完整標記都算人為活動（已測）；runbook 要求標記是最後一行的完整標記只有 `[doc]` 層 |
| merge-note-carries-the-marker | partial | ITS-DT-003 | 8g 的 GitHub 端留言模板有寫；實際貼出的留言屬執行期，MV-003 |
| drift-lookup-fails-for-one-issue | partial | ITS-DT-012 | 漂移腳本 exit 1、3 的分支有寫；執行期見 MV-001 |
| repeated-comment-lookup-failure | partial | ITS-DT-012 | 第二次 exit 3 即停止的數字門檻有寫；執行期見 MV-001 |
| comment-lookup-fails-for-one-issue | partial | ITA-EG-009, ITS-DT-012 | 腳本 exit 3 且無輸出已測；「其餘 issue 照常」屬執行期，MV-001 |
| old-jira-bug | partial | ITS-DT-011 | 文字有寫；執行期不驗 |

Legend: covered 只用於**腳本層**：行為由真實腳本在拋棄式 repo 或假 gh 上機械驗證，且不依賴 SKILL.md 的文字或 agent 的執行期判斷 · partial 含 `[doc]` 層（只證明 runbook 有寫）或依賴 agent 執行期判斷，agent 是否遵守見 Manual Verification · manual 無自動測試

## Manual Verification

- [ ] MV-001 AC-2、AC-6、AC-8、AC-9：對真實 repo（例如 yibi-stack 自己）以唯讀方式跑 `/issue-triage`，確認報告頂端有 origin/main@SHA；沒有對任何 issue 寫入；分層與 review-urgency 註記出現；有豁免的 issue 被列在豁免清單；單一 issue 的過期資料失敗時其餘 issue 照常。
- [ ] MV-002 AC-3：用一個引用已刪除檔案的 issue（可在拋棄式 repo 建立）走查 OBSOLETE 判定，確認必須做正向對照、零命中或搜尋目錄不存在時結論是 UNCLEAR、建議關閉原因是 not planned。
- [ ] MV-003 AC-4、AC-10：在拋棄式 repo 以 `--apply` 走查 stale notice 路徑（貼出帶標記的留言、不關閉），再以 last-human-activity.sh 確認 notice 時間被找回；寬限期滿與「判定到寫入之間有人回覆」兩條路徑無法在 GitHub 回填留言時間，只以 ITA-ST-007 與文件走查支撐，不冒稱已端到端驗證。
- [ ] MV-004 AC-10：走查排程與 webhook 情境，確認即使帶 `--apply` 也只進報告、不貼任何留言。

## Missing Coverage

- OBSOLETE 的證據判斷、寬限期狀態機、豁免套用、優先級排序都是 agent 讀 runbook 後的執行期行為，pytest 無法驗證，只有 `[doc]` 層與人工走查。
- 寬限期滿的關閉路徑無法端到端驗證（GitHub 留言時間無法回填）。
- 腳本層未測：bot 判定遇到 Bot 與 User 以外的帳號型別（只驗證「視為人為活動」的保守分支）。

## Redundant TCs

無；ITB-ST-003 與 ITB-ST-002 分別覆蓋 ahead 與 behind 兩個互斥方向。

## Traceability Matrix

TC 與 scenario 的對應以 TC Table、Coverage Analysis 與 pytest docstring 的 `tc:`／`spec:` 為唯一資料來源。
測試檔：plugins/dev-cycle/skills/issue-triage/scripts/tests/ 下的 test_check_baseline.py、test_staleness_signals.py、test_last_human_activity.py、test_skill_contract.py；該目錄已列於 pyproject.toml 的 testpaths。

Review Contract AC-14（修正 check_testplan_trace.py 在 worktree 內略過所有測試檔）屬於另一個 capability（testplan-trace），
不對應本 change 的 spec scenario，所以不在上面的 TC 表；它的驗證是 plugins/sdd/scripts/tests/test_check_testplan_trace.py 的
TPT-ST-009 到 014（013、014 鎖住 `.claude` 與 `worktrees` 必須同時出現才略過），細節見 tasks.md 的 6.2 與 7.8。
