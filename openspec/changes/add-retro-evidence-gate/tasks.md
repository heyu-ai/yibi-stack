# Tasks：add-retro-evidence-gate

## 1. 前置確認

- [ ] 1.1 讀 `tasks/mycelium` 的 typed-lessons models，確認是否已有 `parked` 狀態值與 recurrence 計數欄位。行為：產出「park 是加欄或沿用既有欄位」的明確結論並記於本檔；若需加欄，確認為向後相容擴充（rule 02 type guard）。驗證：貼出 schema 相關程式碼片段與結論一句話。
- [ ] 1.2 量測本 change 前 `.claude/rules/` 中 frontmatter 無 `paths:` key（每 session 全量載入）的檔案總行數，作為「本 change 自我約束——always-loaded 面淨增為零」的 baseline。行為：baseline 數字被記錄。驗證：印出數字並寫入本檔。

## 2. commit-time lint（純函式檢查器）

- [ ] 2.1 實作 `scripts/lint_rule_evidence.py` 的純函式 `check_rule_evidence(diff_text) -> list[str]`，滿足需求「commit-time lint 分層強制且以純函式暴露」與設計決策「lint 分層強制 + 純函式檢查器」。行為：對 git-staged diff 判定證據標記存在性，接受結構化（`<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`）與 prose（`Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`）擇一；回傳失敗訊息清單。驗證：`uv run pytest scripts/tests/test_lint_rule_evidence.py -q`。
- [ ] 2.2 實作分層強制：新增 `.claude/rules/NN-*.md` 檔或 settings.json 新註冊 hook 及其 script 缺標記 → 非零 exit 擋 commit；既有 rule 檔新增 section 缺標記 → warn-only。行為：兩類輸入產生 error vs `[WARN]` 兩種可觀察結果。驗證：test 對兩類合成 diff 分別斷言 exit code 與訊息。
- [ ] 2.3 實作 new-section 偵測 heuristic（以 diff hunk 新增行中的 `^#{2,3} ` heading 為錨點）與錨點 fail-loud + UTF-8 讀取。行為：編輯既有 section 的行內變更不誤觸發 warn。驗證：fixture「編輯既有 section」不產生 `[WARN]`；錨點字串缺失時 `[FAIL]` 而非略過。
- [ ] 2.4 合成 fixture 負向測試（滿足「commit-time lint 分層強制且以純函式暴露」的可測性）。行為：`check_rule_evidence` 對空輸入與錨點缺失皆回傳非空清單，不空洞通過。驗證：pytest 對兩案例斷言回傳非空。
- [ ] 2.5 於 `.pre-commit-config.yaml` 註冊 hook，warn-only 段設 `verbose: true` 使警告可見。行為：`make ci` 執行該 hook 且警告不被靜默。驗證：`pre-commit run lint-rule-evidence --all-files` 顯示輸出。

## 3. `/pr-retro` Evidence Gate runbook

- [ ] 3.1 於 `plugins/pr-flow/skills/pr-retrospective/SKILL.md` 新增 Step 5.0 Evidence Gate，滿足需求「每個「加 rule/hook」action item 寫入前必須分級」與設計決策「Evidence Gate 置於既有三道 gate 之上游」。行為：Step 5 在 Q5→action 映射前先分級，未分級者不進 Promotion Gate；分級依「有無可接受證據形式」而非 `--source` 分數。驗證：字串錨點測試確認 Step 5.0 段存在且位於 Promotion Gate 敘述之前。
- [ ] 3.2 於 Step 5.0 加入證據形式表，滿足需求「證據形式依 lesson 類型封閉列舉且無 catch-all」與設計決策「證據形式表以 lesson 類型封閉列舉（見 spec SBE Example）」「複用姊妹 change 的證據模式，不重新發明」。行為：表為封閉列舉、最後一列標「無可接受形式，恆 park」、無 `other`/`etc.` catch-all 列。驗證：錨點測試確認最後一列存在且全文無 catch-all 列字樣。
- [ ] 3.3 於 Step 5.0 加入三種執行結果規則，滿足需求「Tier 1 probe 必有三種執行結果且無效不等於不成立」。行為：文件明載重現／未重現／無效三分法、「無效先修一次、修不好降 Tier 3 park、不記為未重現、不 drop」。驗證：錨點測試確認「無效」「repair once」「不記為未重現」三個錨點皆存在。
- [ ] 3.4 於 Step 5.0 加入成本分層規則，滿足需求「驗證成本分層」與設計決策「成本分層：便宜當場跑、昂貴派 subagent 或降級」。行為：文件明載結構檢查零成本、秒級 probe 當場跑、昂貴 probe 派 subagent 或降 Tier 2，並指向 `verification-recipes` 配方 9/10。驗證：錨點測試確認「派 subagent」與「降級 Tier 2」措辭存在。
- [ ] 3.5 於 Step 5 的 Q5→action 映射表加入證據前置條件。行為：`寫入規則文件` 與 `新增 hook` 兩列各標「須先通過 Evidence Gate（Tier 1/2 帶證據）」。驗證：錨點測試確認兩列含該前置條件字串。
- [ ] 3.6 於 Step 5.0 加入 Tier 3 park 與升級規則，滿足需求「Tier 3 park 與 recurrence 升級契約」與設計決策「Tier 3 park 複用 typed-lessons，recurrence 升級但不繞過證據」。行為：Tier 3 park 到 typed-lessons（confidence ≤ 4、parked），recurrence ≥ 2 解除 park 重新受評但仍須通過 Tier 1/2 證據。驗證：錨點測試確認「recurrence ≥ 2」「解除 park」「仍須通過 Tier 1 或 Tier 2」錨點存在。

## 4. rule 11 作者面規範

- [ ] 4.1 於 `.claude/rules/11-skill-authoring.md` 新增「Retro-authored rule/hook 的三層證據標準」段，滿足設計決策「規範內容寫入 rule 11 而非新增 always-loaded rule 檔」，複用既有 verify-before-authoring / Cross-doc Cite 脈絡。行為：規範只在編輯 `skills/**` 時載入，非全量。驗證：錨點測試確認該段存在於 rule 11。
- [ ] 4.2 確認未新增任何 frontmatter 無 `paths:` key 的 rule 檔。行為：規範內容全數落在 rule 11（paths 觸發）。驗證：對照 1.2 baseline 的全量載入檔清單無新增檔。

## 5. 自我約束與收尾

- [ ] 5.1 實作並執行「本 change 自我約束——always-loaded 面淨增為零」的機械檢查。行為：全量載入 rule 檔總行數相對 1.2 baseline 淨增為 0，且數字被印給操作者。驗證：檢查腳本輸出淨增行數 = 0。
- [ ] 5.2 收尾閘門。行為：`make ci` 全綠且其後 `git diff --name-only` 為空（formatter hook 就地改檔）；`spectra validate` 與 `spectra analyze`（Critical + Warning 為 0）通過。驗證：貼出三者輸出摘要。
