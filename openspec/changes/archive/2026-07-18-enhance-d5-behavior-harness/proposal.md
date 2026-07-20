## Why

harness-eval D5（Testing & CI 整合）目前只衡量「測試是否存在」，無法判斷測試是否真正有效。Martin Fowler 的 Harness Engineering 文章指出，AI 生成的測試套件是行為層（behavior harness）最薄弱的環節——測試跑過不代表 agent 的改動被有效保護。

## Layer 1 — User Stories

### US-001：D5 評分能反映測試有效性，而非只測試存在性

**Persona**：使用 harness-eval 評估專案 agentic 就緒度的開發者；他知道測試檔案存在，但不確定 AI 生成的測試是否真的在保護程式碼
**Action**：執行 `harness-eval`，查看 D5 評分與語意說明
**Outcome**：從分數組合（如 2+0+0 vs 2+2+1）立刻判斷測試套件的弱點在哪，而不是只得到一個「有測試 → 5 分」的無資訊分數

**Acceptance Criteria**：
- AC-001-1：當測試只有 `assert result is not None` 類的存在性 assertion 時，D5 語意子項「meaningful assertions」得 0 分（GIVEN/WHEN/THEN 可驗證）
- AC-001-2：當測試有 `assert result.score == 7` 類值比對 assertion 時，「meaningful assertions」子項得 2 分
- AC-001-3：D5 語意總分可為 0、2、3、4、5 中的任意值（非僅 0/3/5）

---

### US-002：機械探針偵測 factory helper，提供語意評分具體線索

**Persona**：同上開發者；他的 repo 遵循 rule 09 的 `make_*` factory helper 慣例，希望 harness-eval 能自動識別
**Action**：執行 `harness-eval`，機械掃描在幾毫秒內完成
**Outcome**：`scan_testing()` 的 JSON 輸出包含 `factory_helper_files` 清單，語意評分 agent 讀取此清單後可直接給 factory helper 子項加分，不需要重新讀取每個測試檔案

**Acceptance Criteria**：
- AC-002-1：有 `def make_scan_profile()` 的 test 目錄，`extra["factory_helper_files"]` 為非空清單
- AC-002-2：無任何 `def make_` 的 test 目錄，`extra["factory_helper_files"]` 為空清單 `[]`
- AC-002-3：factory helper 偵測不影響 D5 機械分上限（仍為 7 分）

---

### US-003：D5 分數偏低時，優先 TODO 清單出現 mutmut 建議

**Persona**：同上開發者，D5 只拿到 3 分（只有測試存在，無 CI 無 hook-test link）；他不知道下一步該怎麼提升測試有效性
**Action**：查看 harness-eval 的「優先改善 TODO」清單
**Outcome**：看到 `[D5, medium-effort, high-impact]` 條目，附有三行可直接複製的 `uv` 指令，立刻知道 mutation testing 是可操作的下一步

**Acceptance Criteria**：
- AC-003-1：D5 總分（機械 + 語意）= 3 時，TODO 出現 mutmut 建議條目
- AC-003-2：D5 總分 = 4 時，TODO **不**出現 mutmut 建議條目
- AC-003-3：建議條目含有 `uv add --dev mutmut`、`uv run mutmut run --paths-to-mutate`、`uv run mutmut results` 三行指令

---

## What Changes

- **D5 語意 rubric 重構**：將現行 binary 評分（5/3/0）改為三個子項（max 5 分不變），從「有測試嗎」升級為「測試有效嗎」
  - 測試有意義的 assertion（不只是「跑完不 crash」）+ 2 分
  - 使用 factory helper / approved fixtures pattern + 2 分
  - 涵蓋邊界條件（EG-* test IDs 或多情境）+ 1 分
- **D5 TODO 建議補充**：當 D5 < 4 分時，在優先改善 TODO 中加入 mutmut mutation testing 建議作為深度分析指引
- **scan_testing() 機械探針補強**：新增 factory helper 偵測（掃描 test_*.py 內是否有 def make_ 開頭的 helper function），使機械分能提供更精確的 semantic_targets 線索給語意評分

## Non-Goals

- 不在 harness-eval 主流程內執行 mutation testing（執行成本過高，不適合 eval loop）
- 不新增 --deep-d5 CLI flag（避免 API 複雜化；mutation testing 建議以 TODO 文字呈現即可）
- 不修改其他維度（D1-D4, D6-D10）的評分邏輯

## Layer 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | test 檔案遵循 `test_*.py` 命名（rule 09 規範） | `def make_` 偵測的掃描範圍不準確；需修改 `_find_test_files()` |
| A2 | factory helper 一律以 `def make_` 開頭（module-level，縮排為 0） | 方法層 `def make_*` 被誤計入；需加縮排檢查 |
| A3 | harness-eval 的 D5 語意評分由 agent 依 SKILL.md rubric 執行，非程式碼邏輯 | 若移往 Python 實作，rubric 格式需轉為機械規則 |
| A4 | mutmut 在 Python 3.10+ 環境可用（`uv add --dev mutmut`） | 建議指令需依環境調整（如 pip、poetry） |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | `scan_testing()` 執行時間不可超過 100ms（現行機械掃描基準） | harness-eval 設計原則：機械分確定性且毫秒完成 |
| C2 | D5 機械分上限維持 7 分，語意分維持 5 分，總上限 12 分不變 | 維持跨維度比較基準，避免影響總分排名 |
| C3 | `extra["factory_helper_files"]` 的型別為 `list[str]`（符合 `MechanicalFinding.extra: dict[str, list[str]]` schema） | models.py 現有型別定義 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 自動執行 mutmut 並回報存活率 | 30-90 秒執行時間違反 C1，且需要安裝額外依賴 | 考慮加入 `harness-eval-focus D5 --deep` 子命令 |
| TypeScript / Go test 的 factory helper 偵測 | 各語言命名慣例不同，需分別實作 | 若使用者群體擴展到非 Python 再納入 |
| 語意評分一致性驗證（跨 agent 回放測試） | 需要 golden dataset 和重播機制，超出本次範圍 | 可作為 harness-eval-focus D5 的長期研究方向 |

## Layer 5 — 可測試性

### Done 定義

此功能視為「完成」的條件：
- [ ] `scan_testing()` 回傳的 `extra["factory_helper_files"]` 在有 / 無 `def make_` 的目錄各自正確
- [ ] `test_scanners.py` 新增 2 個 factory helper 相關測試，且 `uv run pytest tasks/harness_eval/tests/test_scanners.py` 全數通過
- [ ] `skills/harness-eval/SKILL.md` D5 語意 rubric 改為三子項，binary 描述完全移除
- [ ] `skills/harness-eval/SKILL.md` Step 4 含 mutmut TODO 觸發邏輯與三行 uv 指令
- [ ] `make ci` 通過（ruff + mypy + pytest）

### 冒煙測試情境

**ST-001：有 factory helper 的 repo 機械分不受影響**
- GIVEN repo 有 `tasks/harness_eval/tests/test_scanners.py`，其中有 `def make_scan_result()` 函數
- WHEN 執行 `uv run python -m tasks.harness_eval scan --target-dir <repo>`
- THEN D5 機械分不變（最高仍為 7 分），`extra["factory_helper_files"]` 非空

**ST-002：無 factory helper 的 repo 回傳空清單**
- GIVEN 測試目錄只有 `class TestFoo:` 和硬編碼測試資料，無 `def make_` 函數
- WHEN 執行 `scan_testing()`
- THEN `extra["factory_helper_files"] == []`

**ST-003：D5 低分時 TODO 出現 mutmut 建議**
- GIVEN harness-eval 執行後 D5 總分為 3（tests=3, CI=0, hook=0, semantic=0）
- WHEN agent 執行 Step 4 報告生成
- THEN TODO 清單包含含有 `mutmut` 關鍵字的條目

**ST-004：語意評分可給部分分（2+0+0）**
- GIVEN 測試檔案有值比對 assertion（`assert x == 7`）但無 factory helper 且只有 happy path
- WHEN agent 依三子項 rubric 評分
- THEN 語意分 = 2（非 0、3 或 5）

## Capabilities

### New Capabilities

- `d5-behavior-quality-rubric`: D5 語意評分的三子項結構，定義「測試有效性」的評量標準與 mutmut TODO 觸發條件

### Modified Capabilities

（無，openspec/specs/ 目前為空）

## Impact

- 受影響的規格：d5-behavior-quality-rubric（新建）
- 受影響的程式碼：
  - 修改：`skills/harness-eval/SKILL.md`（D5 語意 rubric + TODO 邏輯）
  - 修改：`tasks/harness_eval/scanners/testing.py`（factory helper 探針）
  - 修改：`tasks/harness_eval/tests/test_scanners.py`（對應 testing.py 的新探針測試）
