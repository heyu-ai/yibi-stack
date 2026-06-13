# Proposal：add-harness-eval-validation-protocol

> 版本：v1.0 | 日期：2026-06-08 | 狀態：Draft
> 追蹤：GitHub issue #143 | 來源研究：`docs/research/2026-06-03-efc-feedback-compute-harness-eval-reference.md`（§5 B4）
> 前置依賴：issue #140（trace/EFC 收集器）、issue #142（outcome proxy labels）

## Why

`harness-eval` 的 D1–D11 維度權重目前全是**專家直覺**，從未用真實 outcome 驗證過任一維度的
有效性。這意味著：我們無法回答「分數高的 repo 真的比較容易讓 agent 成功嗎？」這個最根本的問題。

本提案借用論文 *Scaling Laws for Agent Harnesses via Effective Feedback Compute*
（arXiv 2605.29682v1）的 **prospective holdout 驗證協定**，把 harness-eval 從「直覺評分」
升級成「可證偽的預測模型」。

> 論文 provenance caveat：該論文為未來日期（2026-05）且引用虛構模型，僅作**方法論參考**，
> 非實證權威。本提案借用其「先凍結協定、再於未見過 holdout 批次套用預先指定 metric」的反 post-hoc
> 紀律，不引用其數值結論。

論文做法：先凍結 NRS-EFC 定義、task-demand 因子、擬合指數與所有 baseline，再把預先指定的
R²/MAE 套用到全新、未見過的 held-out trace 批次，藉此防止事後挑參數。這正是 harness-eval
目前完全缺的「證偽機制」——也是 #136（D_repo 正規化）等改善能否被證明有效的「量尺地基」。

## What Changes

新增 `tasks/harness_eval/validation/` 模組，提供三件事：

| 元件 | 內容 |
|------|------|
| Protocol 凍結 | 把當前維度權重 / 正規化因子序列化成版本化快照，計 hash；評估前必須先凍結 |
| Metric 計算 | 對 `(harness-eval 分數, outcome)` 資料集計算 R² 與 MAE（選用 power-law 擬合） |
| Holdout 報告 | 依 batch 切 train/holdout；**holdout 批次禁止調參**，只在其上回報 metric |

**反 post-hoc guard**：若 protocol 未凍結（無 snapshot hash），metric 計算 MUST 拒絕執行並報錯。
這在機制上強制「先凍結、後評估」的順序，而非靠紀律自律。

**前置依賴處理**：真實資料集來自 #140（trace/EFC）與 #142（outcome labels）。在前置完成前，
本模組以**標準化 CSV/JSONL ingest 介面**運作，並用 fixture 資料集驗證 metric 與 guard 邏輯正確；
真實資料 wiring 待前置 issue 完成後再接。

## Layer 1 — User Stories

### US-001：評估前凍結協定快照

**Persona**：要驗證 harness-eval 預測力的方法論維護者
**Action**：執行 `harness-eval-validate freeze`
**Outcome**：當前權重 / 正規化因子被序列化成版本化快照並計 hash，後續 metric 以此 hash 標記

**Acceptance Criteria**：
- AC-001-1：`freeze` MUST 產生含 `protocol_hash`（內容雜湊）的 snapshot 檔
- AC-001-2：snapshot MUST 記錄維度權重表、`D_repo` 係數、metric 定義版本
- AC-001-3：相同設定 freeze 兩次 MUST 得到相同 `protocol_hash`（確定性）

### US-002：計算 R²/MAE

**Persona**：同上維護者；手上有 `(分數, outcome)` 資料集
**Action**：執行 `harness-eval-validate score --dataset <path>`
**Outcome**：得到 harness-eval 分數對 outcome 的 R² 與 MAE

**Acceptance Criteria**：
- AC-002-1：給定 N ≥ 2 筆 `(score, outcome)`，MUST 回傳 `r2`（float）與 `mae`（float ≥ 0）
- AC-002-2：完美線性關係的資料集 MUST 得 `r2 == 1.0`（容差 1e-6）且 `mae == 0.0`
- AC-002-3：metric 結果 MUST 標記所用 `protocol_hash`

### US-003：prospective holdout 報告

**Persona**：同上維護者
**Action**：執行 `harness-eval-validate holdout --dataset <path> --holdout-batch <id>`
**Outcome**：metric 只在指定 holdout 批次上計算，且該批次未參與任何調參

**Acceptance Criteria**：
- AC-003-1：資料集含 `batch` 欄位時，MUST 能只在 `holdout-batch` 的列上計算 metric
- AC-003-2：holdout 報告 MUST 標示 holdout batch id 與該批次樣本數
- AC-003-3：holdout 批次樣本數為 0 時 MUST 報錯（而非回傳空 metric）

### US-004：未凍結協定時拒絕評估（反 post-hoc）

**Persona**：同上維護者；忘了先 freeze 就跑 score
**Action**：在無 snapshot 的情況下執行 `score`
**Outcome**：系統拒絕並提示先 freeze，避免事後挑參數

**Acceptance Criteria**：
- AC-004-1：無有效 snapshot 時，`score` 與 `holdout` MUST 以非零 exit 拒絕執行
- AC-004-2：錯誤訊息 MUST 指示先執行 `freeze`

## Layer 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | 真實資料集來自 #140 / #142 | 前置未完成前以 fixture/CSV 驗證邏輯；apply 的「真實驗證」步驟需等前置 |
| A2 | outcome 為 [0,1] 的成功率 proxy（CI pass 率 / 1−prompt 比率等） | outcome 定義由 #142 決定；本模組只要求數值型 |
| A3 | 資料集 schema：`repo_id, score, outcome[, batch]`（CSV 或 JSONL） | schema 改變需同步 ingest 解析 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | 無 snapshot 時 metric 計算 MUST 拒絕（反 post-hoc，機制強制） | 論文 prospective holdout 紀律 |
| C2 | holdout 批次禁止參與任何權重調整 | 同上 |
| C3 | 不發 network 請求；純本地檔案讀寫 + 數值計算 | rule 03 / 安全性 |
| C4 | metric 計算純 stdlib / numpy 等輕量依賴，不啟動 subprocess | 效能 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 自動調整維度權重 | 本提案只「驗證」不「最佳化」 | 校準後可另開 tuning change |
| trace/EFC 計算本身 | 屬 #140 範圍 | 依賴其輸出 |
| outcome label 收集本身 | 屬 #142 範圍 | 依賴其輸出 |

## Layer 5 — 完工標準

### Done 定義

- [ ] `tasks/harness_eval/validation/{models,service,cli,__main__,__init__}.py` 建立（rule 04 結構）
- [ ] `freeze` / `score` / `holdout` 三子命令註冊於 CLI group（rule 08）
- [ ] snapshot 凍結 + hash + 反 post-hoc guard 實作
- [ ] R²/MAE 計算 + holdout 切分實作
- [ ] `tasks/harness_eval/validation/tests/` 以 fixture 資料集覆蓋 VAL 測試
- [ ] `skills/harness-eval/SKILL.md`（或新 skill 段落）說明驗證協定使用方式
- [ ] `make ci` 通過

### 冒煙測試情境

#### Scenario: smk-freeze-produces-hash -- SMK-001 freeze 產生確定性 hash

**GIVEN** 系統正常，當前 harness-eval 設定可讀
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

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `freeze-produces-hash` | VAL-DT-001 | `spec: harness-eval-validation-protocol#freeze-produces-hash` |
| US-001 | `snapshot-records-weights` | VAL-DT-002 | `spec: harness-eval-validation-protocol#snapshot-records-weights` |
| US-001 | `freeze-deterministic` | VAL-DT-003 | `spec: harness-eval-validation-protocol#freeze-deterministic` |
| US-002 | `r2-mae-computed` | VAL-DT-004 | `spec: harness-eval-validation-protocol#r2-mae-computed` |
| US-002 | `perfect-fit-r2-one` | VAL-DT-005 | `spec: harness-eval-validation-protocol#perfect-fit-r2-one` |
| US-002 | `metric-tagged-with-hash` | VAL-DT-006 | `spec: harness-eval-validation-protocol#metric-tagged-with-hash` |
| US-003 | `holdout-only-batch` | VAL-DT-007 | `spec: harness-eval-validation-protocol#holdout-only-batch` |
| US-003 | `holdout-reports-batch-id` | VAL-DT-008 | `spec: harness-eval-validation-protocol#holdout-reports-batch-id` |
| US-003 | `empty-holdout-errors` | VAL-EG-001 | `spec: harness-eval-validation-protocol#empty-holdout-errors` |
| US-004 | `score-rejected-without-freeze` | VAL-DT-009 | `spec: harness-eval-validation-protocol#score-rejected-without-freeze` |
| US-004 | `error-points-to-freeze` | VAL-DT-010 | `spec: harness-eval-validation-protocol#error-points-to-freeze` |
| — | `smk-freeze-produces-hash` | SMK-001 | `spec: harness-eval-validation-protocol#smk-freeze-produces-hash` |
| — | `smk-score-needs-freeze` | SMK-002 | `spec: harness-eval-validation-protocol#smk-score-needs-freeze` |
| — | `smk-perfect-fit` | SMK-003 | `spec: harness-eval-validation-protocol#smk-perfect-fit` |
