## Context

harness-eval D5（Testing & CI 整合）由兩個部分組成：

1. **機械掃描**（`tasks/harness_eval/scanners/testing.py`，7 分）：確定性地檢查測試檔案存在、CI 設定、hook 連結
2. **語意評分**（`skills/harness-eval/SKILL.md`，5 分）：agent 根據 rubric 判斷驗證閉環品質

目前 D5 語意 rubric 是 binary：「有測試有 hook → 5 分、有測試無 hook → 3 分、無 → 0」。這使得 D5 只能回答「有無」而非「好壞」，無法偵測 AI 生成測試套件的常見問題——測試存在但只做 happy path、沒有 factory helper、assertion 不實質。

## Goals / Non-Goals

**Goals:**

- D5 語意 rubric 改為三個子項（max 5 分不變），能衡量測試有效性
- `scan_testing()` 新增 factory helper 偵測，提供 `semantic_targets` 線索
- D5 分數低於門檻時，優先 TODO 清單自動加入 mutmut 建議

**Non-Goals:**

- 不在 harness-eval 主流程執行 mutation testing（太昂貴）
- 不新增 `--deep-d5` CLI flag
- 不修改 D5 機械分（7 分）的結構或其他維度

## Layer 3 — 資料模型（Brownfield）

> **Brownfield 判斷依據**：`MechanicalFinding` 已存在於 `tasks/harness_eval/models.py`，`extra: dict[str, list[str]]` 欄位已預留擴充位，無需修改 model。逆向工程確認如下。

### Entity：MechanicalFinding（既有，verify intent）

來源：`tasks/harness_eval/models.py`

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `dimension` | `str` | NOT NULL | 維度代號（如 "D5"） |
| `label` | `str` | NOT NULL | 維度標籤（如 "Testing & CI 整合"） |
| `score` | `int` | >= 0（validator 確保） | 本維度機械分 |
| `max_score` | `int` | 隱含 > 0 | 本維度機械分上限 |
| `findings` | `list[str]` | default `[]` | 可讀發現清單（PASS / WARN 描述） |
| `semantic_targets` | `list[str]` | default `[]` | 語意評分 agent 應讀取的檔案路徑清單 |
| `extra` | `dict[str, list[str]]` | default `{}` | 擴充欄位：本次新增 key `factory_helper_files` |

### `extra["factory_helper_files"]` 語意（新增）

| 屬性 | 值 |
|------|-----|
| Key | `"factory_helper_files"` |
| 型別 | `list[str]` |
| 值域 | 相對於 `target_dir` 的 test 檔案路徑；無 factory helper 時為 `[]` |
| 不變量 | 所有路徑均可在 `_find_test_files()` 回傳的清單中找到（不含 target_dir 外的路徑） |
| 副作用 | 不影響 `score` 計算；僅作為語意評分線索 |

### 衝突偵測結果

**baseline，無需衝突檢查**——`openspec/specs/` 目前為空，本次為首份規格，無既有 entity / endpoint / event schema 需比對。

`factory_helper_files` 使用既有 `extra: dict[str, list[str]]` 欄位，**不新增欄位、不修改型別簽名**，無向後不相容風險。

## Decisions

### D5 語意三子項與分值分配（2+2+1）

採用 2+2+1 分配而非 1+2+2：

| 子項 | 分值 | 理由 |
|------|------|------|
| 有意義的 assertion（不只是跑完不 crash） | 2 | 最根本的品質指標；assertion 缺失等於測試無效 |
| factory helper / approved fixtures pattern | 2 | rule 09 強制規範；存在即表示測試資料可控且可審計 |
| 邊界條件覆蓋（EG-* IDs 或多情境） | 1 | 加分項；有則更好，無則不致命 |

**替代方案考量**：等分（1+2+2）讓 factory helper 比 assertion 更重要，邏輯顛倒（工具比目的更重要）。

### factory helper 機械偵測用 def make_ prefix heuristic

rule 09 規定 factory function 命名以 `make_` 開頭（如 `make_scan_profile`）。用前綴偵測可靠度高，false positive 僅在縮排 `def make_`（方法）被誤判時發生——透過「僅偵測行首 `def make_`（column 0）」可消除此 case。

**替代方案考量**：偵測 `pytest.fixture` — 被 rule 09 明確排除（不建立 conftest.py），與本 repo 慣例不符。

結果以 `extra["factory_helper_files"]` 回傳（`list[str]`），供語意評分 agent 閱讀。

**語意 rubric 語言覆蓋範圍**：機械探針僅覆蓋 Python（`def make_`）；語意評分 agent
對其他語言直接從 test 檔案內容判斷：TypeScript/JavaScript 使用
`create*()`/`build*()`/`make*()` module-level 函數；Dart/Flutter 使用
`setUp()` callback 或命名工廠建構子；Go 使用 package-level table-driven
`cases` / `tests` 變數。`extra["factory_helper_files"]` 非空是 Python
的快速判定捷徑，不影響其他語言的評分邏輯。

### mutmut TODO 觸發門檻為 D5 < 4（總分 12）

D5 < 4 表示三個機械項目全部失分或接近全失——代表測試套件結構性不足，此時 mutation testing 建議有實質意義。

D5 >= 4 時加入 mutmut 建議意義不大（使用者已有基本測試基礎設施）。

邊界值（boundary value analysis）：
- D5 = 3（最高觸發值）→ 顯示建議
- D5 = 4（最低非觸發值）→ 不顯示

## Implementation Contract

**scan_testing() 輸出變化：**

`MechanicalFinding.extra` 新增一個 key：
- `factory_helper_files: list[str]`：找到 `def make_` pattern（行首，column 0）的 test 檔案路徑（相對 target_dir）

此欄位不影響機械分（7 分結構不變），作為語意評分 agent 的上下文線索。

**D5 語意 rubric（SKILL.md）：**

舊：
```
- 有明確自我驗證方式（tests / lint / screenshot hook / stop-hook 自檢）-> 5 分；有測試無 hook 整合 -> 3 分；無 -> 0
```

新（三子項，總計 max 5）：
```
- 測試有意義的 assertion（不只是「跑完不 crash」，有值比對/型態比對/狀態比對）-> 2 分；僅存在無實質 assertion -> 0
- 使用 factory helper（語言相依：Python = `def make_*` module-level function；TypeScript/JS = `create*()`/`build*()`/`make*()` module-level；Dart/Flutter = `setUp()` callback 或命名工廠建構子；Go = package-level table-driven `cases`/`tests` 變數）-> 2 分；所有測試直接硬編碼測試資料 -> 0
- 涵蓋邊界條件：含 EG-* 類 test ID 或至少 3 種不同情境（success / missing field / edge case）-> 1 分；僅 happy path -> 0
```

**D5 TODO 規則（SKILL.md Step 4）：**

當 D5 總分（機械 + 語意）< 4 時，在「優先改善 TODO」清單加入：
```
[D5, medium-effort, high-impact] 測試套件有效性不足：考慮執行 mutation testing
  uv add --dev mutmut
  uv run mutmut run --paths-to-mutate tasks/<module>/
  uv run mutmut results
```

**Acceptance criteria：**

- `test_scanners.py` 中有至少 2 個新測試：一個驗證有 `def make_` 的目錄回傳非空 `factory_helper_files`，一個驗證無 `def make_` 的目錄回傳空清單
- SKILL.md D5 語意 rubric 可在三個子項各自得分（agent 評分時可給 2+0+0、2+2+1 等組合，而非只有 5/3/0）
- 當 D5 總分 = 2（只有測試存在 + 有 CI，無 hook，無語意分）時，Step 4 TODO 出現 mutmut 建議

## Risks / Trade-offs

- **[Risk] `def make_` heuristic 在非 Python repo 無效** -> 接受；harness-eval 主要評估 Python codebase，TypeScript 使用者若無 factory helper 機械分不受影響（語意 agent 仍可獨立判斷）
- **[Risk] 語意評分一致性下降**（三個子項比 binary 更難讓 agent 穩定判斷）-> 緩解：每個子項的描述加入具體的可觀察指標（值比對、型態比對、EG-* ID），減少模糊空間
- **[Risk] mutmut TODO 出現在所有低分 repo 但使用者不一定用 Python** -> 接受；TODO 是建議非強制，且觸發條件已限制在 D5 < 4 的嚴重案例
- **[Risk] 縮排 `def make_` 誤判（方法當 factory）** -> 緩解：實作限制偵測「行首（column 0）`def make_`」，消除縮排 case
