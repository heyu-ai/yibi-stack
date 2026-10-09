## 1. 先驗證未實測的前提

- [x] 1.1 找出含 bot 留言的 GitHub issue 當樣本（本 repo 的留言只有單一作者，無法驗證），實測 bot 留言的 author.login 實際形式，定案「Last substantive human activity measurement」的 bot 判定規則（design 的「人為活動度量排除 skill 自己與 bot 的留言」）。驗證：把觀測到的 login 與最終規則寫回 design.md 的 Open Questions 並標示已解決；對樣本以 jq 套用規則，bot 留言被排除、人為留言保留。規則若與 spec 內的 [bot] 後綴與 app/ 前綴不同，同步修正 specs/issue-triage-staleness-review/spec.md

## 2. 基準檢查腳本（先寫測試再實作）

- [x] 2.1 先寫 plugins/dev-cycle/skills/issue-triage/scripts/tests/test_check_baseline.py：在暫時的 git repo fixture 上涵蓋 Distinct exit codes for baseline failures 的每一種結果（通過、不在 git repo、fetch 失敗、落後、領先、tracked 檔案被修改），斷言 Checkout must equal the origin main commit 的 ahead、behind、modified 數量出現在 stderr，並斷言 untracked 檔案不造成失敗；同時把新測試目錄加入 pyproject.toml 的 testpaths（該清單是明列的，不加入就不會被 make ci 收集）。驗證：腳本尚不存在時整份測試為紅（red-first），執行 uv run pytest 該檔確認
- [x] 2.2 實作 plugins/dev-cycle/skills/issue-triage/scripts/check-baseline.sh（design 的「以 origin/main 為證據基準並 fail loud」）：落實 Fetch before verification（fetch 失敗即停、不回退到本機 ref），通過時 stdout 輸出 BASELINE_SHA 與 FETCHED_AT，失敗時 stderr 輸出 [FAIL] 並以 2、3、4、5 區分。驗證：2.1 的測試全綠；再做 Baseline check is verified by a negative control 的突變驗證——只改一件事，把腳本主體短路成永遠 exit 0，斷言測試轉紅且突變錨點確實套用，最後以反向替換還原（不得用 git checkout 還原），還原後測試再次全綠

## 3. 漂移蒐集腳本（先寫測試再實作）

- [x] 3.1 先寫 plugins/dev-cycle/skills/issue-triage/scripts/tests/test_staleness_signals.py：在暫時 git repo 上涵蓋 Code drift signal 的五種狀態（unchanged、changed 附 commit 數、deleted 附刪除 commit、renamed、never-existed）、沒有任何路徑時回報不適用，以及基準 ref 不存在時 exit 非 0 且不輸出狀態行。驗證：腳本尚不存在時測試全紅
- [x] 3.2 實作 plugins/dev-cycle/skills/issue-triage/scripts/staleness-signals.sh（design 的「程式碼漂移訊號用 git 歷史計算」與「多步驟邏輯放進輔助腳本」）：輸入 issue 建立時間與一個以上 repo 相對路徑，每個路徑輸出一行 tab 分隔的路徑、狀態、細節。驗證：3.1 的測試全綠；對 deleted 狀態做單一突變（把刪除判斷改成永遠回報 unchanged），斷言對應測試轉紅，再以反向替換還原

- [x] 3.3 先寫 plugins/dev-cycle/skills/issue-triage/scripts/tests/test_last_human_activity.py：以 PATH 上的假 gh 執行檔回放 REST 留言 JSON，涵蓋 Last substantive human activity measurement 的情境——type 為 Bot 的留言被排除（含 login 沒有後綴的 Copilot 型態）、空 login 的已刪除作者視為人為活動、內文含 triage 標記且作者為目前登入帳號的留言被排除、同樣標記但作者是另一個帳號則計為人為活動、沒有留言時回傳 issue 建立時間、輸出附帶 stale notice 標記的時間、gh api user 失敗時 exit 非 0 且不輸出時間。驗證：腳本尚不存在時測試全紅
- [x] 3.4 實作 plugins/dev-cycle/skills/issue-triage/scripts/last-human-activity.sh（design 的「人為活動度量排除 skill 自己與 bot 的留言」與「多步驟邏輯放進輔助腳本」）：以 REST 逐 issue 取得留言與帳號型別，輸出最後實質人為活動時間與 stale notice 標記時間。驗證：3.3 的測試全綠；做單一突變——移除排除 Bot 型別的判斷，斷言 bot 相關測試轉紅且突變錨點確實套用，再以反向替換還原並確認測試再次全綠

## 4. SKILL.md 改寫

- [x] 4.1 在 plugins/dev-cycle/skills/issue-triage/SKILL.md 新增 Step 1c 證據基準檢查：只留單一 bash 呼叫 check-baseline.sh，並把 exit 0、2、3、4、5、1 各列為獨立分支與對應的 [FAIL] 訊息，不合併成單一失敗分支；Step 7 報告模板頂端加入 Baseline commit recorded in the report 所要求的基準 SHA 與 fetch 時間，且 Jira-only 與單一項目執行同樣先過基準檢查。驗證：閱讀 SKILL.md 確認六個 exit code 皆有分支，並 grep 確認報告模板第一個區塊含基準 SHA 欄位
- [x] 4.2 在 SKILL.md Step 3 加入 Last substantive human activity measurement 與 Triage marker on every skill-authored comment：定義活動度量（排除 bot 與 skill 自己、且標記必須搭配 viewerDidAuthor 才生效，見 design 的「過期狀態記在 issue 留言標記上而不是本機檔案」），活動度量以 last-human-activity.sh 的單一呼叫取得，不由 agent 現場推算，且只對「以全部留言計算天數仍小於 180」或「任一留言含 stale notice 標記」的 issue 呼叫；並落實 Unavailable staleness data fails safe（任一 issue 取不到過期資料時，不得升為 STALE-CANDIDATE 或 OBSOLETE，報告列為過期檢視不可用，且不得把缺資料當成人為活動）；並要求 Step 8 每一則 gh issue comment 的內文模板都帶標記。驗證：grep 確認 Step 8 每個 gh issue comment 區塊都含標記，且文件說明另一帳號貼出的標記視為人為活動
- [x] 4.3 在 SKILL.md Step 3c′ 前後加入 Inactivity tiers escalate the evidence burden 的分層表（30、90、180 天為初始值並註明首次執行與使用者校準），說明 fast 與 deep 都套用分層、archive 與 ADR 比對仍只在 deep（design 的「天數分層提高證據門檻而不決定結果」）；並把 Step 3c′ 的「越舊的 issue 越要查」改成指向此分層表。驗證：分層表與 spec 內 tier assignment 的邊界範例（29、30、89、90、179、180 天）逐列一致
- [x] 4.4 修改 SKILL.md Step 3e 決策表：新增 OBSOLETE verdict（含 design 的「OBSOLETE 需要正向對照」：零命中不是證據、搜尋目錄不存在為 UNCLEAR、部分症狀失去前提為 UPDATE-SCOPE、關閉原因為 not planned），並依 Verdict precedence with the new verdicts 把優先序改為 MERGE、CLOSE、OBSOLETE、UPDATE-SCOPE、STALE-CANDIDATE、KEEP，並落實 Staleness verdicts apply to GitHub issues only（OBSOLETE 與 STALE-CANDIDATE 不套用 Jira bug）。驗證：決策表每一列與 spec 的 scenario 逐項對照，且文件內不再有舊的三段優先序字串
- [x] 4.5 在 SKILL.md 決策表新增 STALE-CANDIDATE verdict and grace period（只由 KEEP 與 KEEP external 升級、14 天寬限期、寬限期滿且無人為活動才提議 not planned 關閉、有人為活動則重算、絕不僅憑天數關閉），並加入 Exemptions from staleness verdicts 的五種豁免與報告中列出豁免原因。驗證：對 spec 內 STALE-CANDIDATE 與豁免的每個 scenario 在 SKILL.md 找到對應規則
- [x] 4.6 修改 SKILL.md Step 6「時效」列與 FAQ 的 close-as-stale 條目，落實 Inactivity does not lower the priority of unresolved severe issues（design 的「久未更新拆成 review-urgency 而不是降優先」）：久未更新改為 review-urgency 註記，不降低嚴重且未解 issue 的優先級。驗證：grep 確認「KEEP 並降優先」舊字串不再出現，且 Step 6 與 FAQ 不再互相矛盾
- [x] 4.7 在 SKILL.md Step 8 新增 stale notice 與寬限期滿關閉兩個寫入動作，落實 Write actions for the new verdicts remain opt-in：只在 --apply 且逐項確認後執行、排程與 webhook 情境一律停在報告、寫入失敗跳過該筆並彙總。驗證：與 Core Contract 逐條對照，並在 spec 的兩個 scenario（排程情境、確認後貼 notice）找得到對應文字

## 5. 驗證與整合

- [x] 5.1 若 SKILL.md 的 description 或 Usage 文字有變，同步更新 skills/README.md 索引列；先 git add 新檔，再跑 make ci（--all-files 的 pre-commit 與 pytest，含 markdownlint MD013 與 lint-skill-overlap）。驗證：make ci 全綠，且確認 git diff --name-only 在 hook 跑完後為空
- [x] 5.2 以 spectra analyze 與 spectra validate 驗證本 change 的 artifact 一致性，並逐一對照兩份 spec 的 Requirement 與 SKILL.md、兩支腳本的行為，確認沒有只存在於其中一邊的 guard。驗證：analyze 無 Critical 與 Warning，validate 通過
- [x] 5.3 依 plugin 版本 lockstep 慣例，在 PR 內用 scripts/sync-plugin-versions.sh 升版（不在本 change 內執行 make release）。驗證：所有 plugin 的 package.json 與 .claude-plugin/plugin.json 版本一致
