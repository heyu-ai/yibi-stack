# Proposal：add-task-demand-normalization

> 版本：v1.0 | 日期：2026-06-08 | 狀態：Draft
> 追蹤：GitHub issue #136 | 來源研究：`docs/research/2026-06-03-efc-feedback-compute-harness-eval-reference.md`（§4 A1）

## Why

`harness-eval` 的 D1–D11 為**絕對加總分數**。`docs/harness-eval-effectiveness-review.md` 已點名
核心偏差：**加總式 /123 獎勵「東西多」而非「剛好」**——repo 擁有越多 artifact（rule 檔、skill、
hook）就越容易累積高分，把 over-engineering 誤判為 better。具體案例：14 個 rule 檔讓 D7 拿 6/7
高分，卻對其 always-on token 成本零偵測。

換句話說，**目前分數混入了「repo 規模」這個 confound**：大型複雜 repo 與五檔小工具 repo 用同一把
絕對尺，分數不可比。

本提案借用論文 *Scaling Laws for Agent Harnesses via Effective Feedback Compute*
（arXiv 2605.29682v1）的 **task-demand 正規化** 概念。

> 論文 provenance caveat：該論文為未來日期（2026-05）且引用虛構模型，僅作**方法論參考**，
> 非實證權威。本提案只借用「以任務需求正規化掉規模 confound」的設計思路，不引用其數值結論。

論文以 `D_task = L · H_tool · S_state · (1+N_obs) · (1−V_oracle)` 正規化掉「任務難度」後，
cross-family 預測一致性顯著提升。對應到本 repo：用 repo 複雜度因子 `D_repo` 正規化掉「規模」，
讓分數反映「相對成熟度」而非「artifact 數量」。

## What Changes

在**聚合層**新增 `D_repo` 複雜度因子與 `size_adjusted_score`，**不動任何個別 scanner**：

| 項目 | 內容 |
|------|------|
| `D_repo` | 由 repo 複雜度訊號（source LOC、skill 數、hook 數、rule 數）算出的 ≥1 因子 |
| `size_adjusted_score` | `round(total_mechanical / D_repo, 1)`，抵銷「artifact 越多分越高」的膨脹 |
| 報告呈現 | 同時顯示 raw `total_mechanical / max` 與 `size_adjusted_score`，附 provisional 標示 |

**設計要點**：`D_repo` 是**未校準的啟發式因子**（provisional）。真正的校準需要 outcome 資料，
由 issue #143（R²/MAE 驗證協定）後續完成。本提案先讓「規模調整」這個維度存在且可被檢視，
明確標示其為待校準的近似值，避免使用者誤信為精準權重。

## Layer 1 — User Stories

### US-001：掃描輸出包含規模調整分數

**Persona**：用 `harness-eval scan` 同時評估多個大小不一 repo 的平台維護者
**Action**：執行 `harness-eval scan`，查看輸出的 `size_adjusted_score`
**Outcome**：得到一個抵銷規模膨脹的分數，可橫向比較不同規模 repo 的相對成熟度

**Acceptance Criteria**：
- AC-001-1：`ScanOutput` MUST 包含 `d_repo`（float ≥ 1.0）與 `size_adjusted_score`（float ≥ 0）
- AC-001-2：`size_adjusted_score == round(total_mechanical / d_repo, 1)`
- AC-001-3：輸出（json 與 text）MUST 標示 `size_adjusted_score` 為 provisional（未校準）

### US-002：D_repo 反映 repo 複雜度

**Persona**：同上維護者；想理解為何兩 repo raw 分數相同但 size_adjusted 不同
**Action**：查看 `extra` 中 `D_repo` 的組成
**Outcome**：看到 D_repo 由哪些複雜度訊號（LOC / skills / hooks / rules）構成

**Acceptance Criteria**：
- AC-002-1：複雜度訊號全為 0 的最小 repo，`d_repo == 1.0`（除以 1，不改變 raw 分數）
- AC-002-2：複雜度訊號越大，`d_repo` 單調遞增（never 遞減）
- AC-002-3：`extra` MUST 暴露 `d_repo_components`（list[str]，含各訊號原始值）

### US-003：規模調整讓跨 repo 比較公平

**Persona**：同上維護者
**Action**：對「成熟度相近但規模差 10 倍」的兩 repo 各跑一次 scan
**Outcome**：兩者 `size_adjusted_score` 差距小於 raw 分數差距（規模 confound 被縮小）

**Acceptance Criteria**：
- AC-003-1：給定兩 repo A（小）與 B（大），若 B 僅因 artifact 數量多而 raw 分較高，
  則 `size_adjusted_score` 差距 MUST 小於 `total_mechanical` 差距
- AC-003-2：`d_repo` 計算 MUST 是確定性的（相同輸入 → 相同輸出）

## Layer 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | `D_repo` 為 provisional 啟發式，真正權重由 #143 校準 | 在校準前，size_adjusted 僅供相對比較，不可當絕對門檻 |
| A2 | 複雜度訊號：source LOC（tasks/、scripts/）+ skill 數 + hook 數 + rule 數 | 若 repo 結構大不同（無 tasks/），LOC 訊號退化為 0，其他訊號仍有效 |
| A3 | 採 log 縮放讓 D_repo 平緩成長（避免大 repo 被過度懲罰） | 縮放係數偏差只影響強度，不影響單調性 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | `D_repo ≥ 1.0` 恆成立（避免除以 0 或放大分數） | 數值安全 |
| C2 | 不修改任何 `scanners/*.py`；只動 `service.py` 聚合與 `models.py` schema | 範圍隔離 |
| C3 | 所有 size_adjusted 輸出含 `provisional（未校準，見 #143）` 標示 | 避免誤信為精準 |
| C4 | `d_repo` 計算 ≤ 50ms（純檔案計數 + 字元數，無 subprocess） | 對齊 scanner 效能基準 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| D_repo 權重校準 | 需 outcome 資料 | issue #143（R²/MAE 驗證協定） |
| 改寫個別維度計分 | 本提案只做聚合層正規化 | 各維度 zero-gate 另見 #139 |
| 跨 repo benchmark 資料庫 | 需外部基準 | Phase 2 |

## Layer 5 — 完工標準

### Done 定義

- [ ] `tasks/harness_eval/service.py` 計算 `d_repo` 與 `size_adjusted_score` 並寫入 `ScanOutput`
- [ ] `tasks/harness_eval/models.py` `ScanOutput` 新增 `d_repo: float`、`size_adjusted_score: float`
- [ ] `tasks/harness_eval/cli.py` text 輸出顯示兩個分數 + provisional 標示
- [ ] `tasks/harness_eval/tests/test_scanners.py`（或新 test 檔）新增 TDN 測試
- [ ] `skills/harness-eval/SKILL.md` 報告格式段落說明 size_adjusted_score 與其 provisional 性質
- [ ] `make ci` 通過

### 冒煙測試情境

#### Scenario: smk-minimal-repo-drepo-one -- SMK-001 最小 repo 的 D_repo 為 1.0

**GIVEN** target-dir 無 tasks/、無 skills、無 hooks、無 rules
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 回傳 `d_repo == 1.0`
  AND `size_adjusted_score == total_mechanical`

#### Scenario: smk-large-repo-dampens -- SMK-002 大 repo 的膨脹被抵銷

**GIVEN** target-dir 含大量 rules + skills（artifact 多）
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 回傳 `d_repo > 1.0`
  AND `size_adjusted_score < total_mechanical`

#### Scenario: smk-provisional-marker -- SMK-003 輸出含 provisional 標示

**GIVEN** 任意 target-dir
**WHEN** 執行 `harness-eval scan`（text 或 json）
**THEN** 輸出 MUST 含 `provisional` 字串（標示 size_adjusted 未校準）

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `scan-output-has-adjusted-score` | TDN-DT-001 | `spec: task-demand-normalization#scan-output-has-adjusted-score` |
| US-001 | `adjusted-score-formula` | TDN-DT-002 | `spec: task-demand-normalization#adjusted-score-formula` |
| US-001 | `output-marks-provisional` | TDN-DT-003 | `spec: task-demand-normalization#output-marks-provisional` |
| US-002 | `minimal-repo-drepo-one` | TDN-DT-004 | `spec: task-demand-normalization#minimal-repo-drepo-one` |
| US-002 | `drepo-monotonic` | TDN-DT-005 | `spec: task-demand-normalization#drepo-monotonic` |
| US-002 | `drepo-components-exposed` | TDN-DT-006 | `spec: task-demand-normalization#drepo-components-exposed` |
| US-003 | `cross-repo-gap-narrows` | TDN-DT-007 | `spec: task-demand-normalization#cross-repo-gap-narrows` |
| US-003 | `drepo-deterministic` | TDN-DT-008 | `spec: task-demand-normalization#drepo-deterministic` |
| — | `smk-minimal-repo-drepo-one` | SMK-001 | `spec: task-demand-normalization#smk-minimal-repo-drepo-one` |
| — | `smk-large-repo-dampens` | SMK-002 | `spec: task-demand-normalization#smk-large-repo-dampens` |
| — | `smk-provisional-marker` | SMK-003 | `spec: task-demand-normalization#smk-provisional-marker` |
