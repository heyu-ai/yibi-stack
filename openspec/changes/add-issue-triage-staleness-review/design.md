## Context

issue-triage（plugins/dev-cycle/skills/issue-triage/SKILL.md）的決策表只有「誤關」的防線：UNCLEAR 視同 NOT DONE、存疑傾向 KEEP、keep-open 留言絕對優先。沒有任何機制對抗堆積，結果是前提已消失的 issue（模組被移除、功能改名）落不進 CLOSE，只能永遠 KEEP。

三個已查證的事實決定了設計邊界：

- `gh issue list --json` 已抓取 `createdAt`、`updatedAt`、`assignees`、`milestone`（SKILL.md Step 2a），但決策表與排序都沒用到。
- 留言物件的欄位（以 gh 2.102.0 實測）：`author`（只有 `login`）、`authorAssociation`、`body`、`createdAt`、`viewerDidAuthor`、`id`、`url` 等；**沒有 `is_bot`**。這個 repo 的 200 則留言樣本只有 howie（MEMBER）一個作者，沒有 bot 樣本；apply 階段改以公開 repo cli/cli 的 200 則 issue 留言實測（見「人為活動度量排除 skill 自己與 bot 的留言」）。
- `viewerDidAuthor` 是「目前登入的帳號是否為作者」，skill 以使用者自己的帳號貼留言，所以它無法單獨區分「skill 貼的」與「使用者手打的」，必須搭配 body 標記。

Step 3b 的探索 subagent 以 Read/Grep 讀本機 checkout，不檢查 checkout 是否等於 origin/main。本機 main 落後、或停在別的 feature 分支時，DONE 與 NOT DONE 都可能判反；這個 repo 的 CLAUDE.md 已記錄同類事故（共用 checkout 被前一個 session 留在別的分支）。

## Goals / Non-Goals

**Goals:**

- 讓「前提已消失」與「久未更新」成為決策表內一等公民的結論，且仍遵守「誤關成本高於留著」：任何關閉都需要證據或寬限期，不得僅憑天數。
- 讓天數與程式碼漂移決定「要多查什麼」，並把證據門檻隨天數提高。
- 固定證據基準為 origin/main，基準不成立時 fail loud。
- skill 本身維持無狀態：跨次狀態記在 issue 上，不記在本機檔案。

**Non-Goals:**

- proposal 的 Non-Goals 列出的其他缺口（決策表缺口、留言來源身分檢查、截斷與分頁、跨次紀錄、排序權重、Jira 過期判斷、fork 基準、純天數自動關閉）不在本 change。
- 不新增任何 CLI flag：天數分層與寬限期是 SKILL.md 內的常數，避免出現「文件有寫但沒接線」的 flag。
- 不改動 pr-cycle 系列或其他 skill。

## Decisions

### 以 origin/main 為證據基準並 fail loud

做法：Step 1 新增 1c「證據基準檢查」，在任何程式碼驗證之前先 fetch origin main，再確認目前 checkout 的 commit 等於 origin/main、且沒有被修改的 tracked 檔案；任一不成立就 `[FAIL]` 並說明 ahead／behind／modified 的數量與補救方式（從 origin/main 開乾淨 worktree，或更新主 checkout）。

被否決的方案 B：不要求 checkout 對齊，改讓 subagent 用 `git grep origin/main` 與 `git show origin/main:<path>` 讀基準內容。它對 checkout 狀態完全免疫，但 Step 3b／3c 目前依賴 Read／Grep 工具（本 repo 的 bash 規則偏好它們），改成 git 指令會讓每個 subagent prompt 與 tasks.md 讀取都變複雜，且 openspec/changes 的讀取也要改。方案 A 的代價是 checkout 不乾淨時使用者要多一步，但失敗訊息會直接給補救方式，符合 repo 一貫的「fail loud 且自帶修法」。B 保留為之後的選項（Open Questions）。

已知殘餘風險：untracked 檔案不會觸發失敗，但 Grep 工具會搜到它們，可能造成假的 DONE。接受這個風險，因為 untracked 的暫存目錄在主 checkout 極為常見，把它們列為失敗會讓檢查幾乎永遠紅。

### 過期狀態記在 issue 留言標記上而不是本機檔案

stale notice 的狀態（是否已提醒、何時提醒）以 skill 貼出的留言內的 HTML 註解標記記錄，格式為 issue-triage、冒號、留言種類、ISO 日期。這個標記同時承擔兩個功能：讓下一次盤點知道寬限期從何時開始，以及讓盤點自己的留言不重置「人為活動」時鐘。

被否決的方案：

- 只用 label（例如 stale-candidate）：label 可被任何有權限的人增減、不帶日期、且 repo 不一定有這個 label，需要再多一個「先確認 label 存在」的失敗路徑。本 change 不新增 label。
- 本機檔案或 DB：報告目前寫在 job 目錄，job 結束就清掉，跨次不可靠，也與 skill「唯讀預設」的合約衝突。

標記容易被偽造或誤貼，所以標記必須搭配「作者是正在執行 skill 的帳號」（viewerDidAuthor 為真）才生效。另一個帳號貼出的標記一律視為人為活動，這個失敗方向是安全的：它只會讓 issue 看起來比較活躍而被 KEEP，不會導致誤關。

### 人為活動度量排除 skill 自己與 bot 的留言

最後一次實質人為活動 = max(issue 建立時間, 所有「非 bot 且非 skill 自己」的留言時間)。label、assignee、reaction 變動不計入（它們不在 comments 欄位內，也不代表有人處理）。issue body 的編輯不計入，因為 gh 的 JSON 沒有穩定的 body 編輯時間欄位；這個低估活躍度的方向同樣是安全的。

bot 的判定以 GitHub 回報的帳號型別（type 為 Bot）為準，**不看 login 文字**。這是 apply 階段在公開 repo cli/cli（gh 2.102.0）實測後推翻原假設的結果：

- 透過 gh issue list 的 comments JSON（GraphQL），github-actions[bot] 與 cli-triage[bot] 的 login 被去掉後綴，顯示為 github-actions 與 cli-triage；authorAssociation 分別是 CONTRIBUTOR 與 NONE，無法用來辨識 bot。
- 透過 REST（repos/{owner}/{repo}/issues/comments），同兩個帳號的 login 帶 [bot] 後綴且 type 為 Bot；Copilot 的 type 也是 Bot，但 login 本來就沒有後綴。
- 已刪除帳號的留言在 gh JSON 中 login 為空字串，authorAssociation 為 NONE。視為人為活動（較安全的方向）。

所以原本「login 以 [bot] 結尾或以 app/ 開頭」的規則在 gh JSON 上永遠不會命中，bot 留言會全被當成人為活動，過期檢視等於失效。改用 REST 逐 issue 取得每則留言的 user.type；為了不對每個 issue 都呼叫，只有符合下列任一條件才需要查：（一）用全部留言計算的天數仍小於 180（天數已達 180 的 issue 排除 bot 後只會更久，分層結果不變）；（二）任一留言內文含 stale notice 標記（notice 可能早於 180 天，沒有它就無法判斷寬限期，會把已經過了寬限期的 issue 誤當成第一次提醒）。

被否決的方案：只信 authorAssociation 為 OWNER、MEMBER、COLLABORATOR 的留言才算人為活動。它會把外部使用者補充的重現步驟也排除，語意從「有人在處理」變成「維護者有回應」，與 spec 不符。

### 天數分層提高證據門檻而不決定結果

天數只改變「KEEP 需要多少證據」，從不直接產生關閉結論。0–29 天走標準流程；30–89 天加蒐集漂移訊號；90–179 天的 KEEP 必須引用「前提仍成立」的正向證據，而不是預設 KEEP；180 天以上才具備 STALE-CANDIDATE 資格。30／90／180 與 14 天寬限期都是初始值，沿用 SKILL.md 既有的「首次執行請與使用者校準」做法（Step 6 末段）。分層在 fast 與 deep 兩種模式都生效，因為它是便宜的存在性檢查；與 archive／ADR 的交叉比對仍只在 deep。

### 程式碼漂移訊號用 git 歷史計算

對 issue body 內提到的 repo 相對路徑，在 origin/main 上判斷：仍存在且自 issue 建立後未變動、有變動（附 commit 數）、已刪除（附刪除的 commit）、已改名、從未存在。路徑的抽取是啟發式的（含斜線與副檔名的 token），會漏掉只提到符號或功能名稱的 issue，因此規格規定「沒有漂移訊號」或「不適用」都不得被當成前提仍成立的證據。

### OBSOLETE 需要正向對照

零命中的搜尋沒有資訊量：搜尋目錄不存在、拼錯路徑、或工具本身出錯，都會得到零命中。OBSOLETE 因此要求同一種搜尋方法在同一位置找得到一個已知存在的對象（正向對照）；搜尋目錄不存在則該症狀為 UNCLEAR。只有部分症狀失去前提時是 UPDATE-SCOPE，不是 OBSOLETE。建議關閉原因用「not planned」，因為工作沒有被完成。

### 久未更新拆成 review-urgency 而不是降優先

Step 6 的「時效」列把長期無活動導向低優先，與新的過期檢視直接矛盾，FAQ 的 close-as-stale 條目也寫「KEEP 並降優先」。改為：時效訊號只看 milestone 到期與近期活動帶來的急迫性；久未更新另外標成 review-urgency 註記，不影響嚴重度排序。一個又舊又嚴重又未解的 issue 不得被排在同等條件的新 issue 之後。本 change 只修正這個矛盾，不重做排序的權重。

### 多步驟邏輯放進輔助腳本

基準檢查、漂移蒐集與最後人為活動蒐集各一支腳本（最後一支是 apply 階段發現 bot 判定需要 REST 呼叫後補上的），SKILL.md 只留單一 bash 呼叫（rule 13 AP1；rule 11 要求每個外部呼叫都有明確的 `[FAIL]` 停止條件與 exit code 分支）。

## Implementation Contract

**Behavior**

- 每次盤點在第一次程式碼驗證前執行基準檢查；通過時報告頂端寫出基準 commit 的完整 SHA 與 fetch 完成時間。
- 每個 GitHub issue 取得「最後一次實質人為活動」與天數分層；Jira bug 不套用本 change 的過期判斷。
- 決策表新增兩列並改優先序：MERGE > CLOSE > OBSOLETE > UPDATE-SCOPE > STALE-CANDIDATE > KEEP。
- STALE-CANDIDATE 只能由原本會 KEEP（含 KEEP external）的 issue 升級；先提議貼 stale notice，寬限期滿且無人為活動才提議以 not planned 關閉；有人為活動即重新計算。
- 寬限期滿的關閉，在寫入前重新量測最後人為活動；有新活動就取消，列入「已取消」，因為從判定到使用者逐項確認之間可能有人回覆了。
- skill 貼出的每則留言都帶標記；寫入動作仍然是 opt-in、逐項確認、排程情境一律停在報告。

**Interface / data shape**

基準檢查腳本 check-baseline.sh：

- 輸入：無必要參數；在目標 repo 的目錄執行。
- 成功：exit 0；stdout 一行，格式為 BASELINE_SHA=<40 字元 SHA> FETCHED_AT=<ISO 8601>。
- 失敗：stdout 不輸出，stderr 輸出以 `[FAIL]` 開頭的說明；exit code 分別為 2（不在 git repo）、3（fetch 失敗）、4（commit 與 origin/main 不一致，訊息含 ahead 與 behind 數）、5（tracked 檔案被修改，訊息含檔案數）。exit 1 保留給腳本自身的未預期錯誤。

最後人為活動腳本 last-human-activity.sh：

- 輸入：一個 issue 編號；目標 repo 取自目前目錄的 gh 設定。
- 行為：以 REST 取得該 issue 的全部留言（含分頁）與 issue 自身的建立時間，排除 type 為 Bot 的留言，以及「內文含 triage 標記且作者是目前登入帳號」的留言，輸出剩下的最新時間。
- 輸出：stdout 一行 ISO 8601 時間，之後接一個 tab 與 stale notice 標記所在留言的時間（沒有標記則為空欄）；失敗時 stderr 輸出 `[FAIL]`，exit 非 0，不輸出任何時間。
- 目前登入帳號以 gh api user 取得；取得失敗視為失敗，不回退成「沒有人是 skill」。

漂移蒐集腳本 staleness-signals.sh：

- 輸入：issue 建立時間（ISO 8601），以及一個或多個 repo 相對路徑。
- 輸出：每個路徑一行，以 tab 分隔三欄：路徑、狀態（unchanged、changed、deleted、renamed、never-existed 其中之一）、細節（changed 時為 commit 數，deleted 或 renamed 時為相關 commit）。
- 失敗：基準 ref 不存在時 exit 非 0 並在 stderr 輸出 `[FAIL]`，不輸出任何狀態行。

**Failure modes**

- fetch 失敗、基準不一致、tracked 檔案被修改：整個盤點停止，不產出任何 verdict。
- 腳本自身未預期錯誤（exit 1）：視為工具錯誤，回報並停止，不當成「沒有漂移」。
- 單一 issue 的過期資料取不到（last-human-activity.sh 或 staleness-signals.sh 失敗）：該 issue 不得升為 STALE-CANDIDATE 或 OBSOLETE，報告列為「過期檢視不可用」，其餘 verdict 照常計算；缺資料不得被當成人為活動，也不得被當成沒有漂移。
- tier 2 以上的 KEEP 找不到「前提仍成立」的正向證據：維持 KEEP，報告標 premise-unverified；這個旗標本身不得導致任何關閉建議。
- 無法判定 bot 或 skill 留言：往「視為人為活動」的方向失敗（較安全）。

**Acceptance criteria**

- 兩支腳本各有 pytest 測試，在暫時的 git repo fixture 上涵蓋：通過狀態，以及每一種失敗狀態（不同 exit code 各一個 fixture）。
- 負向對照：把 check-baseline.sh 短路成永遠 exit 0，測試必須轉紅。
- 以 spectra analyze 與 spectra validate 驗證 artifact 一致性。
- SKILL.md 的 verdict 表、Step 6、FAQ 與兩份 spec 的決策表一致；刪除或改寫的段落以 grep 檢查沒有殘留的舊引用（例如「KEEP 並降優先」）。

**Scope boundaries**

- 在範圍內：SKILL.md 的 Step 1c、Step 3（新 verdict 與分層）、Step 6（時效）、Step 7（報告頂端基準）、Step 8（標記與兩個新寫入動作）、FAQ；兩支腳本與測試。
- 不在範圍內：Jira、決策表既有缺口、留言身分檢查、截斷與分頁、跨次紀錄、排序權重、fork 基準。

## Risks / Trade-offs

- [bot 判定需要每個 issue 一次 REST 呼叫] → 只對天數小於 180 的 issue 查，上限約為 open issue 數；GitHub 的速率限制遠高於此，且查詢失敗時以失敗方向安全（視為人為活動）處理。
- [bot 型別只在 cli/cli 的 200 則留言樣本驗證過 Bot 與 User 兩種型別] → 其他型別（例如 Organization 或 Mannequin）未見樣本，一律視為人為活動，往安全方向失敗。
- [路徑抽取是啟發式，會漏掉只提到符號的 issue] → 規格規定缺席不是證據；這類 issue 只會停留在 KEEP 並被標示 premise 無法驗證，不會被誤關。
- [untracked 檔案造成假的 DONE] → 已知並接受，見第一個 Decision。
- [基準檢查讓在髒 checkout 上跑 skill 變得困難] → 這是刻意的 fail loud；失敗訊息直接給出補救方式。
- [天數門檻是主觀的] → 標示為初始值，首次執行與使用者校準；分層只改證據門檻，所以門檻設錯的代價是多查或少查，不是誤關。
- [stale notice 對貢獻者形成雜訊] → 只對 180 天以上、無豁免、前提未被證實消失的 issue 提議，且一律需使用者逐項確認。

## Open Questions

- （已解決）bot 留言的 login 實際長相：gh JSON 會去掉後綴、Copilot 本來就沒有後綴，所以改用 REST 的帳號型別判定，見「人為活動度量排除 skill 自己與 bot 的留言」。
- 30／90／180 天與 14 天寬限期是否符合使用者的實際節奏。
- 基準固定為 origin/main 是否足夠；fork 情境下 origin 可能落後 upstream，需要另一個 change 決定。
- 是否要把方案 B（直接讀 origin/main 內容，不要求 checkout 對齊）作為後續的備案。
