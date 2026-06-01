# Proposal：add-token-economy-harness

> 版本：v1.0 | 日期：2026-06-01 | 狀態：Draft

## Why

`harness-eval` 目前能有效評估 harness **結構設置程度**（D1–D10），但完全缺少
「context / token economy」維度。具體缺口：

- D1 只檢查 `CLAUDE.md ≤ 200 行`，對 glob 自動載入的 ~2800 行 rules **零偵測**
- D7 把 14 個 rule 檔評為高品質加分，對其每回合 always-on token 成本視而不見
- 加總式 /115 計分獎勵「東西多」而非「剛好」，造成 over-engineering 誤判為 better

實證：`yibi-stack` always-on context ≈ **3007 行**（CLAUDE.md 216 + 14 rules），
`harness-eval` 給 D7=6/7 高分且零 token 警告——這是「工具無法評估 token 平衡」的
具體可重現反例（詳見 `docs/harness-eval-effectiveness-review.md` Part A-3）。

## What Changes

新增 D11「Context / Token Economy」維度，採 static proxy 近似指標（非 runtime 計量）：

| 指標 | 量法（proxy）| 訊號 |
|------|------------|------|
| always-loaded token 估計 | CLAUDE.md + glob 命中 rules + memory 檔字元數 × 係數 | 過高 → 警告 context budget 壓力 |
| progressive-disclosure 比例 | on-demand 載入（skill body 按需）vs always-on 占比 | 比例過低 → 過度前載 |
| CLAUDE.md ↔ rules 冗餘 | 兩者重疊內容偵測 | 冗餘 → 雙重維護 + token 浪費 |
| effort 相稱性 | 重型 skill 的 `effort:` 等級 vs body 長度 | 不相稱 → 缺少 effort 回饋閉環 |

設計要點：此維度採**邊際遞減懲罰**——always-on token 超過閾值不加分，反而扣分，
修正現行 additive 計分的「越多越高」偏差。

## Layer 1 — User Stories

### US-001：always-loaded context 超標時收到量化警告

**Persona**：使用 `harness-eval scan` 評估 repo 就緒度的開發者；他的 repo 已累積數十個
rule 檔，but 不確定這些 always-on context 對 agentic 效能的影響
**Action**：執行 `harness-eval scan`，查看 D11 分數與 findings
**Outcome**：得到 always-on token proxy（字元數估計）與閾值比對結果，
立刻知道 context 預算壓力程度，而非只看「rule 越多越好」的舊評分

**Acceptance Criteria**：
- AC-001-1：always-on token proxy（字元數）> 上閾值時，D11 findings 含 `WARN always-on context`
  並附上估計字元數
- AC-001-2：always-on token proxy ≤ 下閾值時，D11 findings 含 `OK always-on context`
- AC-001-3：D11 `score` 隨 always-on token proxy 增加而遞減（非線性，但超過上閾值後不得高於 4 分）
- AC-001-4：findings 明確標示「字元估計（非精準 token 計量）」

### US-002：progressive-disclosure 比例過低時觸發警告

**Persona**：同上開發者；他的 repo 所有重要內容都是 glob always-load，沒有 on-demand 的
skill descriptions 或按需載入文件
**Action**：查看 D11 找 progressive-disclosure 比例子指標
**Outcome**：知道 always-on 占比過高，可採取具體行動（移到 skill body、調整 glob 範圍）

**Acceptance Criteria**：
- AC-002-1：`on_demand_chars / total_chars < 0.3` 時，findings 含 `WARN progressive-disclosure 比例過低`
- AC-002-2：`on_demand_chars / total_chars ≥ 0.5` 時，findings 含 `OK progressive-disclosure 比例`
- AC-002-3：on-demand chars 計算涵蓋 skill descriptions（非 always-on 的 body 部分）

### US-003：CLAUDE.md 與 rules 冗餘偵測

**Persona**：同上開發者；他在 CLAUDE.md 和 rules 檔裡都記了類似的 git 命令慣例，
不確定哪裡有重複
**Action**：查看 D11 的冗餘偵測 finding
**Outcome**：得到「CLAUDE.md 與 rules 重疊關鍵詞清單」，可以決定哪邊要保留

**Acceptance Criteria**：
- AC-003-1：CLAUDE.md 與任意 rule 檔有 ≥ 3 個共同高頻詞（排除停用詞）時，findings 含
  `WARN CLAUDE.md↔rules 重疊`
- AC-003-2：無顯著重疊時，findings 含 `OK no CLAUDE.md↔rules redundancy detected`
- AC-003-3：重疊 finding 含具體的重疊詞清單（不超過 5 個詞）

### US-004：effort 相稱性偵測

**Persona**：同上開發者；他的 repo 有若干很長的 skill（body 數千字），
但 frontmatter 沒有設 `effort:`
**Action**：查看 D11 findings
**Outcome**：得到哪些 skill 的 body 長度與 effort 設定不相稱的清單

**Acceptance Criteria**：
- AC-004-1：skill body > 2000 字元且 frontmatter 無 `effort:` 時，findings 含 `WARN effort 未設定` + skill 名稱
- AC-004-2：skill body ≤ 2000 字元或已設定 `effort:` 時，不產生 WARN
- AC-004-3：effort 相稱性掃描不影響 D4 scores

## Layer 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | token proxy 以「字元數 ÷ 4」作為 token 粗估係數（約符合英文/混中文 tokenizer 慣例） | 係數偏差導致閾值誤判；spec 明確標示為 rough estimate |
| A2 | always-on 內容定義：CLAUDE.md + settings.json glob 命中的 rules + `.claude/memory/` 下所有 .md | 若 glob 範圍擴大，掃描需調整 |
| A3 | on-demand 內容定義：skills/ 下 SKILL.md body（skill 的 frontmatter description 一律視為 always-on）| skill body 結構若改變，需重新校準 |
| A4 | CLAUDE.md ↔ rules 冗餘偵測採 word frequency overlap（TF-only，無 IDF）| 短文件可能 false-positive；接受此限制 |
| A5 | skill frontmatter 解析沿用現有 `scan_skills()` 的讀取方式 | 若 skill discovery 路徑改變，token_economy.py 需同步更新 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | `scan_token_economy()` 執行時間 ≤ 100ms（靜態讀 + 字元計數，不啟動 subprocess） | 對齊現有 scanner 效能基準 |
| C2 | D11 max_score = 8（與 D1 CLAUDE.md 同等級，反映 token budget 重要性） | 維持跨維度比較基準 |
| C3 | 分數計算採邊際遞減：always-on 超過上閾值每多 500 字元扣 1 分（最多扣 3 分）| 修正 additive 計分偏差 |
| C4 | 所有 findings 包含「字元估計（非精準 token 計量）」標示 | 避免使用者誤信為精準成本數字 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| Runtime token 計量（實際 API usage）| 需要 API 呼叫、不可靜態化 | 若 Anthropic 提供 token usage callback，可作為 D11 選用補充 |
| 自動優化建議（自動刪除 rule 行）| 破壞性操作，不適合 eval 工具 | 可作為 `/prune-context` 獨立 skill |
| 跨 repo 基準比較 | 需要外部 benchmark 資料庫 | Phase 2 研究方向 |
| 非 Claude Code 工具鏈的 token 估計 | 各工具 tokenizer 不同，無法統一係數 | 明確 scope = Claude Code harness |

## Layer 5 — 完工標準

### Done 定義

此功能視為「完成」的條件：
- [ ] `tasks/harness_eval/scanners/token_economy.py` 實作並通過 mypy
- [ ] `tasks/harness_eval/service.py` 加入 D11 `_safe_scan(scan_token_economy, ...)` 呼叫
- [ ] `tasks/harness_eval/tests/test_scanners.py` 新增 D11 相關測試（對應 testplan.md TC）
- [ ] `skills/harness-eval/SKILL.md` Step 3 rubric 新增 D11 語意評分子項
- [ ] 對 yibi-stack 自身執行 `harness-eval scan` 時，D11 findings 出現 always-on token 警告（3007 行的鐵證得到反映）
- [ ] `make ci` 通過（ruff + mypy + pytest + pre-commit）

### 冒煙測試情境

#### Scenario: smk-high-always-on -- SMK-001 高 always-on repo 觸發 WARN

**GIVEN** target-dir 的 CLAUDE.md + rules 合計 > 20000 字元
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 在 D11 findings 回傳含 `WARN always-on context` 的字串
  AND 系統 MUST NOT 給 D11 滿分（score < max_score）

#### Scenario: smk-low-always-on -- SMK-002 低 always-on repo 不觸發 WARN

**GIVEN** target-dir 的 CLAUDE.md + rules 合計 ≤ 5000 字元，且有 ≥ 30% on-demand content
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 在 D11 findings 回傳含 `OK always-on context` 的字串

#### Scenario: smk-scan-speed -- SMK-003 掃描速度不超標

**GIVEN** 任意 target-dir（包含 yibi-stack 自身的 14 個 rule 檔）
**WHEN** 執行 `scan_token_economy(target_dir)`
**THEN** 函數 MUST 在 100ms 內回傳

#### Scenario: smk-no-effort-skill -- SMK-004 長 skill 無 effort 觸發 WARN

**GIVEN** target-dir 含 ≥ 1 個 skill，其 body 字元數 > 2000 且 frontmatter 無 `effort:` 欄位
**WHEN** 執行 `scan_token_economy(target_dir)`
**THEN** 系統 MUST 在 findings 回傳含 `WARN effort 未設定` 的字串，附 skill 名稱

#### Scenario: smk-disclaimer -- SMK-005 findings 含近似值標示

**GIVEN** 任意 target-dir
**WHEN** 執行 `scan_token_economy(target_dir)` 且 findings 非空
**THEN** 至少一條 finding MUST 含「字元估計（非精準 token 計量）」

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `high-always-on-warn` | TE-DT-001 | `spec: token-economy-scanner#high-always-on-warn` |
| US-001 | `low-always-on-ok` | TE-DT-002 | `spec: token-economy-scanner#low-always-on-ok` |
| US-001 | `score-decreases-with-token-growth` | TE-DT-003 | `spec: token-economy-scanner#score-decreases-with-token-growth` |
| US-001 | `findings-include-disclaimer` | TE-DT-004 | `spec: token-economy-scanner#findings-include-disclaimer` |
| US-002 | `low-progressive-disclosure-warn` | TE-DT-005 | `spec: token-economy-scanner#low-progressive-disclosure-warn` |
| US-002 | `adequate-progressive-disclosure-ok` | TE-DT-006 | `spec: token-economy-scanner#adequate-progressive-disclosure-ok` |
| US-003 | `claude-md-rules-overlap-warn` | TE-DT-007 | `spec: token-economy-scanner#claude-md-rules-overlap-warn` |
| US-003 | `no-overlap-ok` | TE-DT-008 | `spec: token-economy-scanner#no-overlap-ok` |
| US-004 | `long-skill-no-effort-warn` | TE-DT-009 | `spec: token-economy-scanner#long-skill-no-effort-warn` |
| US-004 | `short-skill-no-effort-ok` | TE-DT-010 | `spec: token-economy-scanner#short-skill-no-effort-ok` |
| — | `smk-high-always-on` | SMK-001 | `spec: token-economy-scanner#smk-high-always-on` |
| — | `smk-low-always-on` | SMK-002 | `spec: token-economy-scanner#smk-low-always-on` |
| — | `smk-scan-speed` | SMK-003 | `spec: token-economy-scanner#smk-scan-speed` |
| — | `smk-no-effort-skill` | SMK-004 | `spec: token-economy-scanner#smk-no-effort-skill` |
| — | `smk-disclaimer` | SMK-005 | `spec: token-economy-scanner#smk-disclaimer` |
