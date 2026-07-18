# Specs：add-token-economy-harness

> Capability: `token-economy-scanner`

---

## US-001：always-loaded context 超標時收到量化警告

### AC-001-1：超過上閾值觸發 WARN

#### Scenario: high-always-on-warn -- always-on proxy 超標觸發 WARN

**GIVEN** target-dir 的 CLAUDE.md 字元數 + glob 命中 rules 字元數 + memory 字元數 > 20000
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 列表中包含含有 `WARN always-on context` 的字串
  AND 系統 MUST 在同一 finding 中包含實際估計字元數（整數）
  AND 系統 MUST NOT 讓 `score == max_score`

**邊界值**：
- always-on chars = 19999 → findings 不含 WARN
- always-on chars = 20000 → findings 含 WARN
- always-on chars = 20001 → findings 含 WARN

---

### AC-001-2：低於下閾值顯示 OK

#### Scenario: low-always-on-ok -- always-on proxy 正常範圍顯示 OK

**GIVEN** target-dir 的 always-on 總字元數 ≤ 5000
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含含有 `OK always-on context` 的字串
  AND 系統 MUST 給出 `score ≥ max_score - 1`（不超標不扣分）

---

### AC-001-3：分數隨 token proxy 增加遞減

#### Scenario: score-decreases-with-token-growth -- 分數隨 always-on 增加而遞減

**GIVEN** 有兩個 target-dir：A 的 always-on chars = 5000，B 的 always-on chars = 30000
**WHEN** 各別呼叫 `scan_token_economy()`
**THEN** 系統 MUST 讓 `score(A) > score(B)`
  AND 當 B 的 always-on chars > 20000 時，`score(B) ≤ max_score - 3`

---

### AC-001-4：findings 含近似值標示

#### Scenario: findings-include-disclaimer -- 任何非空 finding 包含近似值聲明

**GIVEN** target-dir 有任意 CLAUDE.md 或 rules
**WHEN** `scan_token_economy(target_dir)` 回傳 findings 非空
**THEN** 系統 MUST 在至少一條 finding 中包含「字元估計（非精準 token 計量）」字串

---

## US-002：progressive-disclosure 比例過低時觸發警告

### AC-002-1：on-demand 比例 < 30% 觸發 WARN

#### Scenario: low-progressive-disclosure-warn -- 按需比例過低觸發警告

**GIVEN** target-dir 的 `on_demand_chars / total_chars < 0.3`（skill body 為 on-demand）
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含 `WARN progressive-disclosure 比例過低` 字串
  AND findings 中 MUST 包含實際比例數值（百分比格式）

**邊界值**：
- ratio = 0.299 → WARN 觸發
- ratio = 0.300 → 不觸發 WARN
- ratio = 0.500 → 顯示 OK

---

### AC-002-2：on-demand 比例 ≥ 50% 顯示 OK

#### Scenario: adequate-progressive-disclosure-ok -- 按需比例充足顯示 OK

**GIVEN** target-dir 的 `on_demand_chars / total_chars ≥ 0.5`
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含 `OK progressive-disclosure` 字串

---

### AC-002-3：on-demand chars 計算涵蓋 skill body

#### Scenario: skill-body-counted-as-on-demand -- skill body 計入按需比例

**GIVEN** target-dir 含 `skills/` 目錄，其中有 ≥ 1 個 SKILL.md 檔案（body > 0 字元）
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 將 SKILL.md body 字元數計入 `on_demand_chars`（不計入 `always_on_chars`）
  AND 總字元數 `total_chars = always_on_chars + on_demand_chars`

---

## US-003：CLAUDE.md 與 rules 冗餘偵測

### AC-003-1：≥ 3 個共同高頻詞觸發 WARN

#### Scenario: claude-md-rules-overlap-warn -- 高詞頻重疊觸發冗餘警告

**GIVEN** CLAUDE.md 與至少一個 rule 檔共有 ≥ 3 個高頻詞（排除停用詞）
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含 `WARN CLAUDE.md↔rules 重疊` 字串
  AND findings MUST 包含至多 5 個重疊詞的清單

---

### AC-003-2：無顯著重疊顯示 OK

#### Scenario: no-overlap-ok -- 無高詞頻重疊顯示 OK

**GIVEN** CLAUDE.md 與所有 rule 檔高頻詞重疊數 < 3
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含 `OK no CLAUDE.md↔rules redundancy detected` 字串

---

## US-004：effort 相稱性偵測

### AC-004-1：長 skill 無 effort 觸發 WARN

#### Scenario: long-skill-no-effort-warn -- 長 skill 缺 effort frontmatter 觸發警告

**GIVEN** target-dir 含 ≥ 1 個 SKILL.md，其 body 字元數 > 2000
  AND 該 SKILL.md frontmatter 中無 `effort:` 欄位
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST 在 `findings` 中包含 `WARN effort 未設定` 字串
  AND findings MUST 包含該 skill 的名稱（kebab-case slug）

**邊界值**：
- body = 1999 字元，無 effort → 不觸發 WARN
- body = 2000 字元，無 effort → 不觸發 WARN
- body = 2001 字元，無 effort → 觸發 WARN
- body = 3000 字元，有 `effort: medium` → 不觸發 WARN

---

### AC-004-2：短 skill 無 effort 不觸發 WARN

#### Scenario: short-skill-no-effort-ok -- 短 skill 無 effort 不觸發

**GIVEN** target-dir 含 ≥ 1 個 SKILL.md，body 字元數 ≤ 2000（無論有無 effort:）
**WHEN** `scan_token_economy(target_dir)` 被呼叫
**THEN** 系統 MUST NOT 在 findings 中包含 `WARN effort 未設定` 字串

---

### AC-004-3：effort 相稱性不影響 D4 scores

#### Scenario: effort-check-isolated-to-d11 -- D11 effort 偵測不干擾 D4

**GIVEN** target-dir 有 skill 觸發 effort WARN（long skill 無 effort:）
**WHEN** `run_scan(target_dir)` 執行完整掃描（D1–D11）
**THEN** D4 `score` MUST 與無 D11 时相同
  AND 只有 D11 findings 中出現 effort WARN，D4 findings 中 MUST NOT 出現

---

## 冒煙測試（SMK）

#### Scenario: smk-high-always-on -- SMK-001 高 always-on repo 觸發 WARN

**GIVEN** 系統處於正常狀態，且 target-dir 含 CLAUDE.md + 10+ rules，合計 > 20000 字元
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 在 D11 findings 回傳含 `WARN always-on context` 的字串
  AND 系統 MUST NOT 給 D11 滿分

#### Scenario: smk-low-always-on -- SMK-002 低 always-on repo 不觸發 WARN

**GIVEN** 系統處於正常狀態，且 target-dir 的 always-on 合計 ≤ 5000 字元，且有充足 on-demand
**WHEN** 執行 `harness-eval scan --target-dir <dir>`
**THEN** 系統 MUST 在 D11 findings 回傳含 `OK always-on context` 的字串

#### Scenario: smk-scan-speed -- SMK-003 掃描速度不超標

**GIVEN** 系統處於正常狀態，target-dir 含 yibi-stack 規模的 14 個 rule 檔
**WHEN** 呼叫 `scan_token_economy(target_dir)`
**THEN** 系統 MUST 在 100ms 內回傳 MechanicalFinding

#### Scenario: smk-no-effort-skill -- SMK-004 長 skill 無 effort 觸發 WARN

**GIVEN** 系統處於正常狀態，target-dir 含 ≥ 1 個 body > 2000 字元且無 `effort:` 的 SKILL.md
**WHEN** 執行 `scan_token_economy(target_dir)`
**THEN** 系統 MUST 在 findings 回傳含 `WARN effort 未設定` 的字串，附 skill 名稱

#### Scenario: smk-disclaimer -- SMK-005 findings 含近似值標示

**GIVEN** 系統處於正常狀態，任意 target-dir（含 CLAUDE.md 或 rules）
**WHEN** 執行 `scan_token_economy(target_dir)` 且 findings 非空
**THEN** 至少一條 finding MUST 包含「字元估計（非精準 token 計量）」
