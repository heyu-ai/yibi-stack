> [PRIORITY-REVIEW] 優先序自動推導：所有任務為 P2（中等複雜度，無阻斷性外部依賴）。
> Phase 1（機械探針）為 Phase 2（語意 rubric）與 Phase 3（TODO）的前置依賴；Phase 2/3 修改同一份
> SKILL.md，建議循序避免衝突。

## Phase 1：機械探針實作（Foundational — Phase 2/3 依賴此探針輸出）

### US-002：scan_context_economy quantifies always-on budget and disclosure ratio（P2）

- [ ] 1.1 實作 design.md「always-on 集合定義」與「budget-shaped 計分」決策：新增
      `tasks/harness_eval/scanners/context_economy.py` 的 `scan_context_economy(target_dir)`。
      always-on 集合 = root `CLAUDE.md` + 無 `glob:` frontmatter 的 `.claude/rules/*.md`；統計總字元
      數並依 design 分級表給 always-on budget 子項（0–3）。重用 `scanners/rules.py` 的
      `_has_glob_frontmatter`。回傳 `MechanicalFinding(dimension="D11", label="Context / Token
      Economy", max_score=5)`，數值摘要寫入 `findings`，檔案清單寫入 `extra["always_on_files"]`。
      驗證：always-on > 100,000 字元的目錄 → budget 子項 0；≤ 20,000 → 3。

- [ ] 1.2 實作「progressive-disclosure 比例」決策：計算 `ratio = (glob-scoped rules + scoped
      skills) / (total rules + total skills)`，依 design 分級表給子項（0–2），分母為 0 時給滿分 2。
      重用 `scanners/skills.py` 的 `_SCOPING_KEYS` 與既有 skill 目錄探測；scoped 檔案放入
      `extra["scoped_files"]`。`semantic_targets` 設為最大的前數個 always-on 檔案。
      驗證：含 `glob:` 的 rule 不在 `extra["always_on_files"]` 且計入分子；ratio 計算正確。

- [ ] 1.3 `scanners/__init__.py` export `scan_context_economy`；`service.py` 的 `run_scan()`
      dimensions 清單追加 `_safe_scan(scan_context_economy, target, "D11", "Context / Token
      Economy", 5)`。驗證：`run_scan()` 輸出含 D11，`ScanOutput.total_mechanical_max == 74`。

- [ ] 1.4 在 `tasks/harness_eval/tests/test_scanners.py` 新增 D11 測試，覆蓋
      「scan_context_economy quantifies always-on budget and disclosure ratio」Requirement 與
      spec.md 邊界表：(a) > 100,000 字元 → budget 0；(b) ≤ 20,000 → budget 3；(c) 含 `glob:` 的
      rule 被排除於 always-on 並計入 ratio 分子；(d) 分母為 0 → ratio 子項給滿分 2。
      驗證：`uv run pytest tasks/harness_eval/tests/test_scanners.py -k context_economy` 全數通過。

## Phase 2：語意 rubric 與報告整合

### US-001：D11 評分反映 context 預算（budget-shaped）（P2）

- [ ] 2.1 實作 design.md「Implementation Contract / SKILL.md」：修改 `skills/harness-eval/SKILL.md`
      Step 2（機械總滿分 69 → 74、加列 D11=5）與 Step 3（新增 D11 語意 rubric：right-sizing 2 分、
      effort 相稱性 1 分，各附可觀察指標）。滿足「D11 semantic rubric scores context right-sizing
      and effort relativity」Requirement。驗證：讀取 SKILL.md，確認 Step 2 機械總滿分為 74、
      Step 3 含 D11 兩子項與分值。

- [ ] 2.2 修改 SKILL.md Step 4 報告分數表新增 D11 列，總分由 `/115` 改為 `/123`，
      等級百分比說明維持不變（脫鉤絕對分）。驗證：報告表含 `D11 Context / Token Economy` 列，
      總分標示 `/123`。

## Phase 3：TODO 觸發邏輯

### US-003：context 過肥時 TODO 出現精簡建議（P2）

- [ ] 3.1 實作 design.md「TODO 觸發門檻為 D11 機械分 < 3」決策：修改 SKILL.md Step 4 TODO 邏輯，
      D11 機械分 < 3 時加入 `[D11, medium-effort, high-impact]` context 精簡條目，內容含「rule 改
      path-scoped（加 `glob:`）」與「大段內容移至 on-demand skill/doc」兩動作，並明確標示 token 為
      **近似估計**。滿足「D11 TODO includes context-pruning recommendation when mechanical score is
      below threshold」Requirement 的 boundary 表（機械=2 出現、機械=3 不出現）。
      驗證：讀取 SKILL.md Step 4，確認有 < 3 觸發條件、兩條具體動作、近似估計標示。

## Phase 4：文件同步

- [ ] 4.1 更新 `plugins/harness/README.md`，將 harness-eval 維度描述由「8 維度」更新為涵蓋
      D1–D11（同步既有 D1–D10 落差）。驗證：README 維度數與實作一致。

- [ ] 4.2 `make ci` 通過（ruff + mypy + pytest），`uv run pre-commit run markdownlint-cli2
      --files skills/harness-eval/SKILL.md` 通過。
