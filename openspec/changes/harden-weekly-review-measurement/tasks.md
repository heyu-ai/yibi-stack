## 1. 前置確認

- [x] 1.1 owner 已裁決 design.md 的 Q1–Q4，裁決結果寫回 design.md「待裁決」段落（改為「已裁決」並註明日期）；驗證：design.md 不再有未決的 Q 項
- [x] 1.2 #508 已 merge，本分支 rebase 到含 `weekly` 子命令的 origin/main；列出 D4 改為精確比對後會從「可歸因」變成「不可歸因」的 gate 清單並附在 PR 描述；驗證：清單由對本 repo `.github/workflows` 實跑新舊兩種比對的差集產生（本 repo 沒有 `scripts/harness` gate，差集為空，改對 yibi-mvp 實跑，結果寫在 design.md 的 Q3 實測；分支用 merge 而非 rebase，因為已推上 PR #516）

## 2. 家族層級注入測試（先寫，預期紅燈）

- [x] 2.1 在 scripts/tests/test_harness_weekly_review.py 新增注入 helper：對 collector 注入檔案讀取失敗、目錄列舉失敗、格式錯誤行、API 回應形狀不符，搭配一份含每種建議類型各一筆的上週快照；先寫「Read-failure injection is tested per source family」的矩陣測試；驗證：實作前在 issue #509 第 1、3、4、7、8、9 項對應的注入格為紅燈，紅燈原因是斷言失敗而非 helper 錯誤
- [x] 2.2 先寫失敗測試涵蓋「A previous recommendation is resolved only with positive evidence」四個 Scenario，並把 DT-029 的預期由 resolved 改為 unmeasured；驗證：實作前 hook-below-sample-threshold、hook-not-observed、gate-job-never-ran 為紅燈，hook-observed-and-clean 為綠燈

## 3. 來源完整性（D1、D2）

- [x] 3.1 新增共用的目錄列舉 helper（以 os.scandir 包 try，錯誤寫入 errors），取代 collect_hook_inventory、hook_event_files、transcript_files、collect_rules、collect_gate_inventory 內的 glob、未防護的 iterdir、沒有 onerror 的 os.walk；驗證：2.1 的目錄列舉注入格全綠，並對 helper 做一次「吞掉 OSError」的 mutation，至少一個測試轉紅
- [x] 3.2 讓每個 collector 回傳 `source: {complete, errors}`，`complete` 在函式最後才依 errors 是否為空設定；hook-events 讀檔傳入 failed，格式錯誤行與 transcript 截斷行計入 errors，hook 腳本讀取失敗使 inventory 不完整；驗證：「Every data source reports completeness that defaults to incomplete」四個 Scenario 的測試全綠
- [x] 3.3 evaluation_scope 改讀 source 記錄，缺漏、型別不符或 complete 不為 True 一律視為量不到，ci.measured 缺漏不再拋 KeyError，docstring 改為描述實際行為；驗證：「Missing or malformed completeness fields are treated as unmeasured」兩個 Scenario 全綠

## 4. 判定與歸因（D3–D6）

- [x] 4.1 diff_snapshots 依 design.md D3 表格，逐類型檢查本週觀察證據與樣本門檻（採 Q1 裁決值），不滿足者判 unmeasured 並 carried；驗證：2.2 全綠，且對每一列觀察證據檢查各做一次移除 mutation，各至少一個測試轉紅
- [x] 4.2 gate-silent 改為 step 名稱精確比對（名稱唯一性由既有的歧義檢查確立，見 design.md D4），移除子字串比對；_gate_attribution_problem 新增動態名稱、跳脫序列、多行 plain scalar 三種不可歸因（範圍是同一個 workflow 檔）；yaml_scalar 無法完整解析時回傳 None；驗證：「Gate attribution uses exact identity only」三個 Scenario 全綠
- [x] 4.3 gate 上線日期改用 --follow，shallow clone 時為未知；CI runs 清單比對 total_count，形狀不符即標記不完整；驗證：shallow-clone 與 runs-response-wrong-shape 兩個 Scenario 全綠
- [x] 4.4 上週快照缺 carried／weeks 時標記 streak_reset 並在報告寫出原因；SNAPSHOT_VERSION 升為 3（依 Q2 裁決）；驗證：previous-snapshot-collect-only Scenario 全綠，且 TestPrevAutoCompat 中 v2 快照被略過的測試更新後通過

## 5. 文件與收尾

- [x] 5.1 cmd_collect 的 evaluation_scope 接線補上測試：以 cmd_collect 端到端執行，斷言 max_rule_candidates 的截斷邊界被套用；驗證：把接線改成不傳上限、或把截斷改為 [N+1:]，兩種 mutation 各至少一個測試轉紅（issue #509 的 C5 缺口）
- [x] 5.2 更新 SKILL.md：exit 2 列補上「--prev auto 遇到壞 JSON 舊快照」、「最後一份」說明會略過版本不符的快照、新增 unmeasured 的讀法與 streak_reset 原因；驗證：以 grep 確認三處文字存在，且 markdownlint 通過
- [x] 5.3 git add 後跑 make ci 全綠，git status 無 formatter 改寫；PR 描述逐條列出 issue #509 的 13 項與 3 個缺口各由哪個測試守住；驗證：make ci exit 0，PR 描述的對照表無空格
