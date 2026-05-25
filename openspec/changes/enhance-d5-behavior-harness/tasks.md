> [PRIORITY-REVIEW] 優先序自動推導：所有任務為 P2（中等複雜度，無阻斷性外部依賴）。Task 1.1 → 1.2 有依賴；Task 2.1 → 2.2 有依賴；Phase 3 可與 Phase 1/2 平行但 parallel_tasks 未啟用。

## Phase 1：機械探針實作（Foundational — Phase 2 的語意 rubric 依賴此探針輸出）

### US-002：scan_testing detects factory helper functions（P2）

- [x] 1.1 實作 design.md「factory helper 機械偵測用 def make_ prefix heuristic」決策，依 design.md「Entity：MechanicalFinding（既有，verify intent）」確認的 `extra["factory_helper_files"]` 語意（新增）與 design.md 衝突偵測結果（baseline，無需 schema 變更）：在 `tasks/harness_eval/scanners/testing.py` 的 `scan_testing()` 中，掃描每個 test 檔案是否有 column 0 的 `def make_` 行（縮排行不計），符合者路徑存入 `MechanicalFinding.extra["factory_helper_files"]`（型別 `list[str]`，相對 target_dir）。機械分（7 分）維持不變。驗證：`test_scanners.py` 中，有 `def make_scan_profile()` 的目錄回傳 `extra["factory_helper_files"]` 非空；縮排 `    def make_foo(self):` 不被計入。

- [x] 1.2 在 `tasks/harness_eval/tests/test_scanners.py` 新增測試，覆蓋「D5 semantic rubric evaluates test effectiveness via three sub-items」和「scan_testing detects factory helper functions」Requirement，並驗證 spec.md boundary 表格四種模式（column-0 函數 / 縮排方法 / 注釋行 / 呼叫表達式）：(a) 含 `def make_` 的 test 目錄 -> `factory_helper_files` 非空；(b) 不含 `def make_` 的 test 目錄 -> `factory_helper_files` 為空清單；(c) 縮排 `def make_` -> 不計入。驗證：`uv run pytest tasks/harness_eval/tests/test_scanners.py -k factory_helper` 全數通過。

## Phase 2：語意 rubric 重構

### US-001：D5 評分能反映測試有效性（P2）

- [x] 2.1 實作 design.md「D5 語意三子項與分值分配（2+2+1）」決策：修改 `skills/harness-eval/SKILL.md` D5 語意評分區塊，將 binary 評分（5/3/0）改為三子項（meaningful assertions 2 分、factory helper pattern 2 分、edge case coverage 1 分），總分上限不變（5 分）。factory helper 子項說明必須覆蓋四種語言的語言相依 pattern（Python: `def make_*` module-level；TypeScript/JS: `create*()`/`build*()`/`make*()`；Dart/Flutter: `setUp()` callback 或命名工廠建構子；Go: table-driven `cases`/`tests` 變數），並說明 `extra["factory_helper_files"]` 非空時可直接判定 Python 項目得分。每個子項附可觀察指標，滿足「D5 semantic rubric evaluates test effectiveness via three sub-items」Requirement 的 scoring combinations 表格（等價類別全覆蓋，partial credit 2+0+0 可達成）。驗證：讀取修改後的 SKILL.md，確認三個子項分別列有分值與判斷標準（含四語言 factory helper 描述），且 binary「有測試無 hook -> 3 分」描述已完全移除。

- [x] 2.2 確認 SKILL.md 的語意 rubric 段落明確說明 `extra["factory_helper_files"]` 非空時可直接給 factory helper 子項加分，讓機械探針與語意評分形成閉環。驗證：SKILL.md 語意 D5 說明中含有 `factory_helper_files` 欄位引用。

## Phase 3：TODO 觸發邏輯

### US-003：D5 低分時出現 mutmut 建議（P2）

- [x] 3.1 實作 design.md「mutmut TODO 觸發門檻為 D5 < 4（總分 12）」決策：修改 `skills/harness-eval/SKILL.md` Step 4 的 TODO 邏輯，當 D5 總分（機械 + 語意）< 4 時加入 mutmut 建議條目，格式含三行 uv 指令（`uv add --dev mutmut`、`uv run mutmut run --paths-to-mutate tasks/<module>/`、`uv run mutmut results`），滿足「D5 TODO includes mutmut recommendation when score is below threshold」Requirement 的 threshold boundary 表格邊界條件（D5=3 出現、D5=4 不出現）。驗證：讀取修改後的 SKILL.md Step 4，確認有觸發條件說明（< 4 門檻）與完整三行指令範例。
