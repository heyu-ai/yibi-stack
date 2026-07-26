# Tasks：add-retro-evidence-gate

## 1. 前置確認

- [x] 1.1 讀 `tasks/mycelium` 的 typed-lessons models，確認是否已有 `parked` 狀態值與 recurrence 計數欄位。行為：產出「park 是加欄或沿用既有欄位」的明確結論並記於本檔；若需加欄，確認為向後相容擴充（rule 02 type guard）。驗證：貼出 schema 相關程式碼片段與結論一句話。

  **結論（1.1）：沿用既有欄位，零 schema / DB migration。** `LessonRecord`（`tasks/mycelium/models.py:72-96`）有 `confidence: int = Field(ge=1, le=10)` 與 `tags: list[str] = Field(default_factory=list)`，但**無**專屬 `parked` 狀態欄位、**無**每筆 lesson 的 recurrence 計數欄位（`recurrence_pr_count` 在另一彙總 model）。`db.py` 確認 `lessons.tags` 為 `TEXT NOT NULL DEFAULT '[]'`（JSON 持久化，`db.py:158/359/649/1124`），且支援 `exclude_tags` LIKE 過濾（`db.py:510-521`）。
  - park = `confidence ≤ 4` + `tags` 含 `"parked"`；recurrence = `tags` 含 `"recurrence-<n>"`（同 `key` 再現時 bump）。
  - 向後相容（rule 02 type guard）：既有讀取者見到多的 tag 不崩；正常 recall 可用 `exclude_tags=["parked"]` 濾除 parked lesson。
  - 影響 task 3.6：runbook 以 `tags` 編碼 park/recurrence，**不需**改 mycelium 程式碼或 DB。
- [x] 1.2 量測本 change 前 `.claude/rules/` 中 frontmatter 無 `paths:` key（每 session 全量載入）的檔案總行數，作為「本 change 自我約束——always-loaded 面淨增為零」的 baseline。行為：baseline 數字被記錄。驗證：印出數字並寫入本檔。

  **Baseline（1.2）：6 個 always-loaded 檔、共 3012 行**（`python3 scripts/check_always_loaded_growth.py`）：01=81、02=339、03=156、13=1391、15=752、16=293。5.1 的檢查以 `--base origin/main` 算這些檔的淨增行數，須為 0。

## 2. commit-time lint（純函式檢查器）

- [x] 2.1 實作 `scripts/lint_rule_evidence.py` 的純函式 `check_rule_evidence(diff_text) -> list[str]`，滿足需求「commit-time lint 分層強制且以純函式暴露」與設計決策「lint 分層強制 + 純函式檢查器」。行為：對 git-staged diff 判定證據標記存在性，接受結構化（`<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`）與 prose（`Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`）擇一；回傳失敗訊息清單。驗證：`uv run pytest scripts/tests/test_lint_rule_evidence.py -q`。
- [x] 2.2 實作分層強制：新增 `.claude/rules/NN-*.md` 檔或 settings.json 新註冊 hook 及其 script 缺標記 → 非零 exit 擋 commit；既有 rule 檔新增 section 缺標記 → warn-only。行為：兩類輸入產生 error vs `[WARN]` 兩種可觀察結果。驗證：test 對兩類合成 diff 分別斷言 exit code 與訊息。
- [x] 2.3 實作 new-section 偵測 heuristic（以 diff hunk 新增行中的 `^#{2,3} ` heading 為錨點）與錨點 fail-loud + UTF-8 讀取。行為：編輯既有 section 的行內變更不誤觸發 warn。驗證：fixture「編輯既有 section」不產生 `[WARN]`；錨點字串缺失時 `[FAIL]` 而非略過。
- [x] 2.4 合成 fixture 負向測試（滿足「commit-time lint 分層強制且以純函式暴露」的可測性）。行為：`check_rule_evidence` 對「有新增內容但缺證據標記（錨點缺失）」回傳非空清單，不空洞通過；對真正空的輸入（無 diff 內容可檢查）回傳空清單。驗證：`test_anchor_missing_is_not_vacuous_pass` 斷言前者非空、`test_empty_diff_returns_empty` 斷言後者為空。**修訂記錄（2026-07-25，PR #339 mob review）**：本行原寫「pytest 對兩案例斷言回傳非空」，與 `test_empty_diff_returns_empty` 實際斷言（真空 diff 回傳空清單）矛盾——這是把 proposal.md AC-003-3 的字面文字直接抄進 tasks.md，未對齊本檔 testplan.md REG-VL-001 早已定義的較窄範圍。Review Contract 的 AC-8 已同步修正措辭；此行同步改寫以符合實際測試行為。
- [x] 2.5 於 `.pre-commit-config.yaml` 註冊 hook，warn-only 段設 `verbose: true` 使警告可見。行為：`make ci` 執行該 hook 且警告不被靜默。驗證：`pre-commit run lint-rule-evidence --all-files` 顯示輸出。

## 3. `/pr-retro` Evidence Gate runbook

- [x] 3.1 於 `plugins/dev-cycle/skills/pr-retrospective/SKILL.md` 新增 Step 5.0 Evidence Gate，滿足需求「每個「加 rule/hook」action item 寫入前必須分級」與設計決策「Evidence Gate 置於既有三道 gate 之上游」。行為：Step 5 在 Q5→action 映射前先分級，未分級者不進 Promotion Gate；分級依「有無可接受證據形式」而非 `--source` 分數。驗證：字串錨點測試確認 Step 5.0 段存在且位於 Promotion Gate 敘述之前。
- [x] 3.2 於 Step 5.0 加入證據形式表，滿足需求「證據形式依 lesson 類型封閉列舉且無 catch-all」與設計決策「證據形式表以 lesson 類型封閉列舉（見 spec SBE Example）」「複用姊妹 change 的證據模式，不重新發明」。行為：表為封閉列舉、最後一列標「無可接受形式，恆 park」、無 `other`/`etc.` catch-all 列。驗證：錨點測試確認最後一列存在且全文無 catch-all 列字樣。
- [x] 3.3 於 Step 5.0 加入三種執行結果規則，滿足需求「Tier 1 probe 必有三種執行結果且無效不等於不成立」。行為：文件明載重現／未重現／無效三分法、「無效先修一次、修不好降 Tier 3 park、不記為未重現、不 drop」。驗證：錨點測試確認「無效」「repair once」「不記為未重現」三個錨點皆存在。
- [x] 3.4 於 Step 5.0 加入成本分層規則，滿足需求「驗證成本分層」與設計決策「成本分層：便宜當場跑、昂貴派 subagent 或降級」。行為：文件明載結構檢查零成本、秒級 probe 當場跑、昂貴 probe 派 subagent 或降 Tier 2，並指向 rule 11 既有的 probe 紀律段落（不再指向不存在的 `verification-recipes` 配方 9/10——PR #339 mob review 指出該文件在本 repo 從未存在，已改連結真實段落）。驗證：`scripts/tests/test_pr_retrospective_evidence_gate_anchors.py::test_cost_tiering_anchors` 對真實 SKILL.md 斷言「派 subagent」與「降級 Tier 2」措辭存在。
- [x] 3.5 於 Step 5 的 Q5→action 映射表加入證據前置條件。行為：`寫入規則文件` 與 `新增 hook` 兩列各標「須先通過 Evidence Gate（Tier 1/2 帶證據）」。驗證：錨點測試確認兩列含該前置條件字串。
- [x] 3.6 於 Step 5.0 加入 Tier 3 park 與升級規則，滿足需求「Tier 3 park 與 recurrence 升級契約」與設計決策「Tier 3 park 複用 typed-lessons，recurrence 升級但不繞過證據」。行為：Tier 3 park 到 typed-lessons（confidence ≤ 4、parked），recurrence ≥ 2 解除 park 重新受評但仍須通過 Tier 1/2 證據。驗證：錨點測試確認「recurrence ≥ 2」「解除 park」「仍須通過 Tier 1 或 Tier 2」錨點存在。

## 4. rule 11 作者面規範

- [x] 4.1 於 `.claude/rules/11-skill-authoring.md` 新增「Retro-authored rule/hook 的三層證據標準」段，滿足設計決策「規範內容寫入 rule 11 而非新增 always-loaded rule 檔」，複用既有 verify-before-authoring / Cross-doc Cite 脈絡。行為：規範只在編輯 `skills/**` 時載入，非全量。驗證：錨點測試確認該段存在於 rule 11。
- [x] 4.2 確認未新增任何 frontmatter 無 `paths:` key 的 rule 檔。行為：規範內容全數落在 rule 11（paths 觸發）。驗證：對照 1.2 baseline 的全量載入檔清單無新增檔。

## 5. 自我約束與收尾

- [x] 5.1 實作並執行「本 change 自我約束——always-loaded 面淨增為零」的機械檢查。行為：全量載入 rule 檔總行數相對 1.2 baseline 淨增為 0，且數字被印給操作者。驗證：檢查腳本輸出淨增行數 = 0。
- [x] 5.2 收尾閘門。行為：`make ci` 全綠且其後 `git diff --name-only` 為空（formatter hook 就地改檔）；`spectra validate` 與 `spectra analyze`（Critical + Warning 為 0）通過。驗證：貼出三者輸出摘要。
