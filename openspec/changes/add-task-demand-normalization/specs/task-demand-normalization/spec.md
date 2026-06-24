# Specs：add-task-demand-normalization

> Capability: `task-demand-normalization`

---

## US-001：掃描輸出包含規模調整分數

### AC-001-1 / AC-001-2：輸出含 size_adjusted_score 且符合公式

#### Scenario: scan-output-has-adjusted-score -- ScanOutput 帶 d_repo 與 size_adjusted_score

**GIVEN** 任意 target-dir
**WHEN** `run_scan(target_dir)` 被呼叫
**THEN** 回傳的 `ScanOutput` MUST 含 `d_repo`（float ≥ 1.0）
  AND MUST 含 `size_adjusted_score`（float ≥ 0）

#### Scenario: adjusted-score-formula -- size_adjusted 等於 total 除以 d_repo

**GIVEN** 任意 target-dir，其 `total_mechanical = T`、`d_repo = D`
**WHEN** `run_scan(target_dir)` 被呼叫
**THEN** 系統 MUST 讓 `size_adjusted_score == round(T / D, 1)`

### AC-001-3：輸出標示 provisional

#### Scenario: output-marks-provisional -- 輸出明確標示未校準

**GIVEN** 任意 target-dir
**WHEN** 產生 text 或 json 輸出
**THEN** 輸出 MUST 包含 `provisional` 字串（標示 size_adjusted 未校準）

---

## US-002：D_repo 反映 repo 複雜度

### AC-002-1：最小 repo 的 D_repo 為 1.0

#### Scenario: minimal-repo-drepo-one -- 無 artifact 的 repo D_repo=1.0

**GIVEN** target-dir 無 tasks/ source、無 skills、無 hooks、無 rules（複雜度訊號全為 0）
**WHEN** `run_scan(target_dir)` 被呼叫
**THEN** 系統 MUST 回傳 `d_repo == 1.0`
  AND `size_adjusted_score == total_mechanical`（除以 1 不改變分數）

### AC-002-2：D_repo 單調遞增

#### Scenario: drepo-monotonic -- 複雜度越大 D_repo 越大

**GIVEN** 兩個 target-dir：A 的複雜度訊號嚴格小於 B（其餘相同）
**WHEN** 各別呼叫 `run_scan()`
**THEN** 系統 MUST 讓 `d_repo(A) <= d_repo(B)`
  AND 當 B 的訊號嚴格較大時 `d_repo(A) < d_repo(B)`

### AC-002-3：暴露 D_repo 組成

#### Scenario: drepo-components-exposed -- 輸出含 D_repo 各訊號原始值

**GIVEN** target-dir 含若干 skills / rules
**WHEN** `run_scan(target_dir)` 被呼叫
**THEN** 系統 MUST 在輸出中暴露 `d_repo_components`（list[str]）
  AND 該清單 MUST 含 `loc=`、`skills=`、`hooks=`、`rules=` 四項原始計數

---

## US-003：規模調整讓跨 repo 比較公平

### AC-003-1：規模膨脹被抵銷

#### Scenario: cross-repo-gap-narrows -- size_adjusted 差距小於 raw 差距

**GIVEN** 兩 repo A（小）與 B（大），B 僅因 artifact 數量多而 `total_mechanical` 較高
**WHEN** 各別呼叫 `run_scan()`
**THEN** `abs(size_adjusted_score(A) - size_adjusted_score(B))`
  MUST 小於 `abs(total_mechanical(A) - total_mechanical(B))`

### AC-003-2：D_repo 計算確定性

#### Scenario: drepo-deterministic -- 相同輸入相同 D_repo

**GIVEN** 同一 target-dir
**WHEN** 連續呼叫 `run_scan()` 兩次
**THEN** 兩次 `d_repo` MUST 完全相等

---

## 冒煙測試（SMK）

#### Scenario: smk-minimal-repo-drepo-one -- SMK-001 最小 repo D_repo=1.0

**GIVEN** 系統正常，target-dir 無任何複雜度 artifact
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 回傳 `d_repo == 1.0` 且 `size_adjusted_score == total_mechanical`

#### Scenario: smk-large-repo-dampens -- SMK-002 大 repo 膨脹被抵銷

**GIVEN** 系統正常，target-dir 含大量 rules + skills
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 回傳 `d_repo > 1.0` 且 `size_adjusted_score < total_mechanical`

#### Scenario: smk-provisional-marker -- SMK-003 輸出含 provisional 標示

**GIVEN** 系統正常，任意 target-dir
**WHEN** 執行 `harness-eval scan`（text 或 json）
**THEN** 輸出 MUST 含 `provisional` 字串
