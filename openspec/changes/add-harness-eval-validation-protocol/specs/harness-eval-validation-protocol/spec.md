# Specs：add-harness-eval-validation-protocol

> Capability: `harness-eval-validation-protocol`

---

## US-001：評估前凍結協定快照

### AC-001-1 / AC-001-2：freeze 產生含權重的 snapshot

#### Scenario: freeze-produces-hash -- freeze 產生含 protocol_hash 的快照

**GIVEN** 當前 harness-eval 設定可讀
**WHEN** 執行 `freeze`
**THEN** 系統 MUST 寫出含 `protocol_hash` 的 snapshot 檔

#### Scenario: snapshot-records-weights -- 快照記錄權重與係數

**GIVEN** 當前 harness-eval 設定可讀
**WHEN** 執行 `freeze`
**THEN** snapshot MUST 含 `dimension_weights`、`d_repo_scale`、`metric_definition`

### AC-001-3：freeze 確定性

#### Scenario: freeze-deterministic -- 相同設定得相同 hash

**GIVEN** harness-eval 設定未改變
**WHEN** 連續執行 `freeze` 兩次
**THEN** 兩次 `protocol_hash` MUST 完全相等

---

## US-002：計算 R²/MAE

### AC-002-1：回傳 R² 與 MAE

#### Scenario: r2-mae-computed -- 對資料集回傳 r2 與 mae

**GIVEN** 已 freeze，且資料集含 N ≥ 2 筆 `(score, outcome)`
**WHEN** 執行 `score --dataset <path>`
**THEN** 系統 MUST 回傳 `r2`（float）與 `mae`（float ≥ 0）與 `n == N`

### AC-002-2：完美線性得 R²=1

#### Scenario: perfect-fit-r2-one -- 完美線性資料 R²=1、MAE=0

**GIVEN** 已 freeze，資料集 `(score, outcome)` 為完美線性關係
**WHEN** 執行 `score --dataset <path>`
**THEN** 系統 MUST 回傳 `r2 == 1.0`（容差 1e-6）
  AND `mae == 0.0`

### AC-002-3：metric 標記 protocol_hash

#### Scenario: metric-tagged-with-hash -- metric 結果帶協定 hash

**GIVEN** 已 freeze 且資料集有效
**WHEN** 執行 `score --dataset <path>`
**THEN** `MetricResult.protocol_hash` MUST 等於當前 snapshot 的 `protocol_hash`

---

## US-003：prospective holdout 報告

### AC-003-1：只在 holdout 批次計算

#### Scenario: holdout-only-batch -- metric 只用 holdout 批次的列

**GIVEN** 已 freeze，資料集含 `batch` 欄位，且有多個 batch
**WHEN** 執行 `holdout --dataset <path> --holdout-batch B`
**THEN** 系統 MUST 只用 `batch == B` 的列計算 metric
  AND `MetricResult.n` MUST 等於 batch B 的樣本數

### AC-003-2：報告標示 batch id 與樣本數

#### Scenario: holdout-reports-batch-id -- 報告含 holdout 批次資訊

**GIVEN** 同上
**WHEN** 執行 `holdout --holdout-batch B`
**THEN** 輸出 MUST 含 `holdout_batch == B` 與該批次樣本數

### AC-003-3：空 holdout 批次報錯

#### Scenario: empty-holdout-errors -- 空批次拒絕並報錯

**GIVEN** 已 freeze，資料集中無任何列的 `batch` 等於指定值
**WHEN** 執行 `holdout --holdout-batch UNKNOWN`
**THEN** 系統 MUST 報錯（而非回傳空 metric）

---

## US-004：未凍結協定時拒絕評估（反 post-hoc）

### AC-004-1：無 snapshot 時拒絕

#### Scenario: score-rejected-without-freeze -- 未 freeze 時 score 被拒

**GIVEN** 無任何有效 snapshot
**WHEN** 執行 `score --dataset <path>`
**THEN** 系統 MUST 以非零 exit 拒絕執行（不計算任何 metric）

### AC-004-2：錯誤訊息指向 freeze

#### Scenario: error-points-to-freeze -- 錯誤訊息提示先 freeze

**GIVEN** 無任何有效 snapshot
**WHEN** 執行 `score --dataset <path>`
**THEN** 錯誤訊息 MUST 指示先執行 `freeze`

---

## 冒煙測試（SMK）

#### Scenario: smk-freeze-produces-hash -- SMK-001 freeze 產生 hash

**GIVEN** 系統正常，harness-eval 設定可讀
**WHEN** 執行 `harness-eval-validate freeze`
**THEN** 系統 MUST 產生含 `protocol_hash` 的 snapshot 檔

#### Scenario: smk-score-needs-freeze -- SMK-002 未凍結時 score 被拒

**GIVEN** 系統正常，無任何 snapshot
**WHEN** 執行 `harness-eval-validate score --dataset <fixture>`
**THEN** 系統 MUST 以非零 exit 拒絕並提示先 freeze

#### Scenario: smk-perfect-fit -- SMK-003 完美線性資料得 R²=1

**GIVEN** 系統正常，已 freeze，fixture 資料集為完美線性 `(score, outcome)`
**WHEN** 執行 `harness-eval-validate score --dataset <fixture>`
**THEN** 系統 MUST 回傳 `r2 == 1.0`（容差 1e-6）且 `mae == 0.0`
