# Proposal：add-retro-evidence-gate

> 版本：v1.0 | 日期：2026-07-21 | 狀態：Draft
> 姊妹 change：`bound-review-loop-with-evidence-gate`（已於 2026-07-18 archived）— 本 change 為其 Non-Goals 明確 defer 的 `/pr-retro` 側續作

## Why

`/pr-retro`（`plugins/pr-flow/skills/pr-retrospective/SKILL.md`）在 Step 5 把 retro 教訓路由成「新增 rule / hook」的 action item，但**這條進料口沒有任何驗證關卡**。現有三道 gate——Promotion Gate（G1 能否自動化 / G2 新人是否會犯 / G3 現有 rule 是否已覆蓋）、Lesson Classifier（進哪個檔）、Patch-Surface Ladder（改動面多大）——**全部只回答「該不該寫、寫哪、寫多大」，沒有一道回答「這條教訓的技術宣稱是真的嗎」**。信心度差異化（Step 4b）靠 `--source`（user-stated 8-9 / cross-model 8 / inferred 5-6）打分，這是「來源信任度」而非「實測驗證」。

後果是 reviewer 收到一條「建議加 rule」時無法區分三種東西：(1) 有實測支撐（如 CLAUDE.md 記載 `paths:` key 行為是「PR #250 實測，`claude -p` 探針」）、(2) 合理但沒驗證的主觀判斷、(3) 一次性、換 context 就不成立、只會讓 always-loaded token 變肥的內容。第 (2)(3) 類每次 retro 都可能長出一條 rule，形成 harness 的「規則通膨」。

**為何是現在**：姊妹 change `bound-review-loop-with-evidence-gate` 已於 2026-07-18 上線，它在 `/pr-cycle-deep` review 迴圈導入證據閘門。該 change 的 Non-Goals 明確寫道：「不做 rules corpus 的治理（`/pr-retro` 路由表的刪除出口、rules hot/cold tier）。不同子系統，回饋源是 `/pr-retro` 而非 review 迴圈。刻意延後：本 change 上線後會直接減少該子系統的流入量，先做這個可能讓後者變小。」本 change 正是那個被延後、且維護者判斷「現在會比較小」的續作。

**兩個閘門互補而非重複**：review-loop gate 作用於 PR review 階段，把「精確度／可能誤導／建議補充」類 finding **恆降級為非 blocking**（其證據形式封閉列舉的最後一列）。這代表 reviewer **結構上擋不住「看似合理但沒驗證」的新 rule**——那正好落在它恆降級的類別裡。該缺口只能靠 write-time（retro Step 5）與 commit-time（lint）對 rule **自身的證據 tier** 分級來補。

## What Changes

1. **新 capability `retro-evidence-gate`**：定義 retro 產出「加 rule / hook」action item 時，寫入 always-loaded 面（`.claude/rules/*`、`CLAUDE.md`）或註冊 hook 前，必須通過的三層證據分級契約。複用姊妹 change 已驗證的四個模式：證據形式**封閉列舉、無 catch-all**；三種執行結果（重現／未重現／**無效**）與「無效 ≠ 不成立、降級不丟棄」；驗證成本分層（零成本結構檢查擋掉多數）；純函式檢查器讓負向測試可行。

2. **`/pr-retro` SKILL.md 新增 Step 5.0 Evidence Gate**：置於既有 Promotion Gate 上游。對每個「加 rule / hook」action item：抽出可證偽宣稱 → 分 tier → Tier 1（可機械實測）便宜的當場跑 probe、昂貴的（`claude -p` 拋棄式 repo）派 subagent 或降級 Tier 2、Tier 2（事件佐證）要求 PR/issue 連結 + 貼原文 quote、Tier 3（主觀／單次）**park，流程對此項終止**。只有帶證據的 Tier 1/2 才往下進入既有三道 gate。probe 方法引用既有 `verification-recipes` 配方 9/10。

3. **`scripts/lint_rule_evidence.py` + pre-commit hook**：機械層，仿既有 `scripts/lint_rule_frontmatter.py`。純函式 `check_rule_evidence(diff_text) -> list[str]` 暴露以支援負向測試。分層：**新 `.claude/rules/NN-*.md` 檔** 或 **settings.json 新註冊的 hook + 其 script** 缺證據標記 → 擋 commit（error）；**既有 rule 檔新增 section** 缺標記 → 初期 warn-only（`verbose: true`），避免龐大歷史 corpus 一上線就爆紅。

4. **Tier 3 park 複用既有 mycelium typed-lessons store**：以 `confidence ≤ 4` + `parked` 狀態存，不新增檔案面。recurrence 升級契約：同類 friction 再現 → recurrence +1；recurrence ≥ 2 才「解除 park」重進 Evidence Gate，**但仍須通過 Tier 1/2 證據才真的寫入**（recurrence 證明「問題真且重現」，不證明「此修法有效」）。

5. **自我約束（示範自己的主張）**：本 change 完成後，`.claude/rules/` 的**淨新增 always-loaded 行數必須為 0**（本 change 的規範內容寫進 rule 11 既有檔的既有段落脈絡，或新 section 但自帶 Tier 1 證據標記）。以機械檢查強制——治臃腫的 change 不得自己讓 always-loaded 面變肥。

**非 BREAKING**：新增一道上游 gate 與一個 lint，不改任何既有 rule 內容、不改既有三道 gate 的行為、不改 typed-lessons schema（只多用 `parked` 狀態值）。

## Step 1 — User Stories

> 五尺度自我檢查結果：三個 US 各為中尺度（3-5 天）、各單一 Actor 群與單一 Goal、AC 皆 ≤ 7 條。「本 change 自我約束」不獨立成 US（它是 DoD，歸 Step 5），併入 US-003 的 AC-003-4。

### US-001：retro 產出的 rule/hook 建議在寫入前被分級與驗證

**Persona**：跑 `/pr-retro` 的 retro agent 與其後校準的維護者。現況 agent 產出「加 rule/hook」建議時，reviewer 無法區分「有實測支撐」「合理但沒驗證」「一次性偶發」三者。
**Action**：對每個「加 rule/hook」action item 抽出可證偽宣稱、分 tier、依 tier 取得證據。
**Outcome**：進入既有 Promotion Gate 的 action item 都已帶「此宣稱為真」的證據，或已被判定為主觀而不再前進。

**Acceptance Criteria**：

- AC-001-1：每個「加 rule/hook」action item MUST 在既有 Promotion Gate 之上游被歸入且僅歸入 Tier 1/2/3；未分級者 MUST NOT 進入 Promotion Gate。
- AC-001-2：分級依「有無可接受證據形式」的封閉列舉表判定（無 catch-all），主觀／可能誤導／建議補充類 MUST 恆歸 Tier 3；`--source` 分數 MUST NOT 單獨作為升級 Tier 1/2 的理由。
- AC-001-3：Tier 1 probe 的執行結果 MUST 為重現／未重現／無效之一；「無效」MUST 先修一次，修不好 MUST 降 Tier 3 park，MUST NOT drop、MUST NOT 記為「未重現」。
- AC-001-4：驗證成本分層——結構檢查零指令即判定、秒級 probe 當場跑、昂貴 probe 派 subagent 或降 Tier 2；互動式 retro MUST NOT 被單一昂貴 probe 阻塞。

### US-002：無法驗證的主觀教訓 park 而不進 always-loaded 面，重現才重評

**Persona**：擔心 harness 規則通膨的維護者。擔心「降級」實質等於「遺失」，也擔心用「重現三次」跳過對修法的驗證。
**Action**：retro 結束後檢視 Tier 3 候選的去向與升級條件。
**Outcome**：主觀／單次教訓不污染 always-loaded 面，但仍被追蹤；真且重現者可被重新評估，不因重現而跳過證據。

**Acceptance Criteria**：

- AC-002-1：Tier 3 action item MUST NOT 寫入 `.claude/rules/*` / `CLAUDE.md` 或註冊為 hook；MUST park 到既有 mycelium typed-lessons（confidence ≤ 4、狀態 parked），MUST NOT 新增獨立檔案面。
- AC-002-2：同類 friction 再現時 recurrence +1；recurrence ≥ 2 MUST 只「解除 park」重新受評，MUST 仍要求通過 Tier 1/2 證據才寫入；recurrence MUST NOT 單獨構成寫入理由。
- AC-002-3：park 的原標題與描述 MUST 逐字保留，MUST NOT 靜默丟棄。

### US-003：commit-time lint 機械擋未帶證據的新 rule/hook

**Persona**：維護者與 CI。擔心 agent 略過 Step 5.0 直接 Edit 寫 rule 檔，或 doc gate 被下一次 retro 靜默略過。
**Action**：commit 含新 rule/hook 或既有 rule 檔新 section 時，pre-commit lint 檢查證據標記。
**Outcome**：最高風險的整批新增（新檔/新 hook）缺證據時硬擋；既有檔新 section 缺證據時可見警示；lint 自身可被負向測試證明會對壞輸入變紅。

**Acceptance Criteria**：

- AC-003-1：新增 `.claude/rules/NN-*.md` 檔，或 settings.json 新註冊 hook 及其 script，缺證據標記 → lint MUST 以非零 exit 擋 commit。
- AC-003-2：既有 rule 檔新增 section 缺標記 → lint MUST warn-only（`verbose: true` 使警示可見），MUST NOT 擋 commit。
- AC-003-3：檢查邏輯 MUST 以純函式 `check_rule_evidence(diff_text) -> list[str]` 暴露；對空輸入與錨點缺失 MUST 回傳非空失敗清單（MUST NOT 空洞通過）；錨點缺失 MUST `[FAIL]` 而非略過。
- AC-003-4：本 change 完成後，`.claude/rules/` 中每 session 全量載入（frontmatter 無 `paths:` key）的檔案總行數相對本 change 前淨增 MUST 為 0，且該數字 MUST 被機械檢查印出。

## Non-Goals（詳見 design.md）

範圍排除與否決方案記於 `design.md` 的 Goals/Non-Goals 段。摘要：不做 rules hot/cold tier 自動汰除、不改 review-loop gate、不建 golden-transcript eval harness、不修 harness-eval D7 scanner 計分 bug（issue #252）、不修 skill-trigger-eval baseline 未進版控（issue #220）。

## Capabilities

### New Capabilities

- `retro-evidence-gate`：`/pr-retro` 產出「加 rule / hook」action item 的寫入前證據契約——三層分級（Probed / Incident-cited / Subjective）、證據形式封閉列舉、三種 probe 執行結果與降級規則、Tier 3 park 出口與 recurrence 升級契約、寫入前 gate 與 commit-time lint 的分層強制、以及契約自身的純函式機械驗證。

（無 Modified Capabilities——本 change 不修改任何既有 capability 的 requirements。已上線的 review-loop 證據閘門與本 change 共用證據模式但作用於不相交的子系統，其關係記於 design.md 的 Context / Decisions，非本 change 的變更對象。本 repo 現有 specs 均與 retro 寫入路徑無 requirement 交集。）

## Step 4 — 假設與約束

### 假設

> 單一來源：下表衍生自 `problem-frame.md` 的 W（領域假設），編號沿用 W 編號，不另行重編。修改假設請改 `problem-frame.md`，此處同步。

| # | 假設內容（引自 problem-frame.md W） | 若不成立的影響 |
|---|-----------------------------------|----------------|
| W1 | retro agent 誠實執行分級與 probe（lint 只驗「有無標記」，不驗「標記是否誠實」） | 最大假設風險：假證據標記可繞過 gate。減災：封閉列舉、mob review 抽查、三分法；殘餘由 golden-transcript harness 收斂（OOS） |
| W2 | typed-lessons store 可寫入且 `parked` 被既有回顧流程消費 | park 成墳場。減災：recurrence 機制 + 複用既有 mycelium 流程 |
| W3 | pre-commit hook 實際被執行（未被 `--no-verify` / CI 略過） | S6 機械層失效，只剩 doc gate。減災：CI `--all-files` 重跑 |
| W4 | 「always-loaded」判定穩定且 lint 能辨識新檔 vs 既有檔新 section | 自我約束與分層強制誤判。減災：diff hunk 新 heading 錨點 + 合成 fixture |
| W5 | `claude -p` 拋棄式 repo 探針在維護者環境可用 | 昂貴 probe 無法執行。減災：允許降 Tier 2 要 PR 階段證據 |
| W6 | 姊妹 review-loop gate 已上線且運作，減少低品質 rule 流入 | retro gate 承擔更大流量，但不影響正確性——把關與 review-loop 是否運作無關 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | Evidence Gate 規範內容 MUST 寫入 rule 11（`paths: skills/**` 觸發），MUST NOT 新開全量載入 rule 檔 | 本 change 自我約束（AC-003-4）+ token economy |
| C2 | lint 檢查邏輯 MUST 為純函式，可用合成 fixture 呼叫 | 負向測試可行性（姊妹 change 已證明的模式） |
| C3 | 錨點比對 MUST 以 UTF-8 讀原始位元組，缺失 MUST `[FAIL]` 而非略過 | host rule 13：ASCII 替代靜默不匹配 |
| C4 | Tier 3 park MUST 複用既有 typed-lessons schema，加欄 MUST 向後相容 | rule 02 type guard；不新增檔案面 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| rules hot/cold tier 自動汰除 | 本 change 只管「新內容寫入前」把關，不回頭治理既有 corpus | 寫入端上線後仍見面失控再開 change |
| 改 review-loop gate（`pr-review-convergence`） | 不相交子系統，各自獨立 SKILL.md；本 change 複用其模式但不修改其 requirements | 不考慮 |
| golden-transcript eval harness | Tier 分級與 probe 是否誠實執行屬 LLM 執行期行為，pytest 不可驗（同姊妹 change） | 收斂 W1 殘餘的唯一途徑，另開 |
| harness-eval D7 scanner 計分 bug（issue #252）/ skill-trigger-eval baseline（issue #220） | 既有獨立缺陷，與本閘門正交 | 各自 issue 追蹤 |

## Step 5 — 完工標準

### Done 定義

- [ ] US-001~003 全部 AC 均已實作（AC-001-1~4、AC-002-1~3、AC-003-1~4）
- [ ] `testplan.md` 所有 `[mech]` 類 TC 均有對應測試且通過（`check_spec_coverage.py` 驗證）
- [ ] 所有 `[doc]` 類 TC 均有對應斷言（對真實 SKILL.md / rule 11）
- [ ] 冒煙測試 SMK-001~003 全數通過
- [ ] 自我約束檢查：全量載入 rule 檔總行數淨增 = 0，且數字已印出
- [ ] `make ci` 全綠，且其後 `git diff --name-only` 為空
- [ ] `spectra validate` 與 `spectra analyze`（Critical + Warning 為 0）通過
- [ ] 程式碼已 code review 並合併

### 冒煙測試情境

#### Scenario: smk-tier1-probe-reproduces-written -- SMK-001 Tier 1 probe 重現則寫入

**GIVEN** 系統正常，一個「新增 hook」action item 附正/負樣本證據
**WHEN** 執行 Step 5.0 Evidence Gate 且 probe 當場跑並顯示攔/放行如預期
**THEN** 系統 MUST 允許該 hook 進入既有 Promotion Gate

#### Scenario: smk-subjective-parked -- SMK-002 主觀教訓被 park

**GIVEN** 系統正常，一個「這規則措辭可更精確」的主觀 action item
**WHEN** 執行 Step 5.0 Evidence Gate
**THEN** 系統 MUST 將其歸 Tier 3 並 park 到 typed-lessons
  AND 系統 MUST NOT 寫入 `.claude/rules/*` 或 `CLAUDE.md`

#### Scenario: smk-new-rule-missing-evidence-blocked -- SMK-003 新 rule 檔缺證據擋 commit

**GIVEN** git-staged diff 含新增 `.claude/rules/17-foo.md` 且無任何證據標記
**WHEN** 執行 pre-commit lint
**THEN** 系統 MUST 以非零 exit 擋下 commit 且訊息含修復指示

### Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `unclassified-blocked-from-promotion` | REG-DT-001 | `spec: retro-evidence-gate#unclassified-blocked-from-promotion` |
| US-001 | `source-score-not-verification` | REG-DT-002 | `spec: retro-evidence-gate#source-score-not-verification` |
| US-001 | `subjective-no-evidence-form` | REG-DT-003 | `spec: retro-evidence-gate#subjective-no-evidence-form` |
| US-001 | `probe-invalid-demoted-not-dropped` | REG-DT-004 | `spec: retro-evidence-gate#probe-invalid-demoted-not-dropped` |
| US-001 | `probe-refutes-not-written` | REG-DT-005 | `spec: retro-evidence-gate#probe-refutes-not-written` |
| US-001 | `expensive-probe-not-blocking` | REG-DT-006 | `spec: retro-evidence-gate#expensive-probe-not-blocking` |
| US-002 | `tier3-parked-not-always-loaded` | REG-DT-007 | `spec: retro-evidence-gate#tier3-parked-not-always-loaded` |
| US-002 | `recurrence-unparks-still-needs-evidence` | REG-DT-008 | `spec: retro-evidence-gate#recurrence-unparks-still-needs-evidence` |
| US-003 | `new-rule-file-missing-evidence-blocks` | REG-EG-001a | `spec: retro-evidence-gate#new-rule-file-missing-evidence-blocks` |
| US-003 | `existing-section-missing-evidence-warns` | REG-EG-001b | `spec: retro-evidence-gate#existing-section-missing-evidence-warns` |
| US-003 | `checker-empty-input-not-vacuous-pass` | REG-VL-001 | `spec: retro-evidence-gate#checker-empty-input-not-vacuous-pass` |
| US-003 | `net-zero-always-loaded-growth` | REG-DT-009 | `spec: retro-evidence-gate#net-zero-always-loaded-growth` |
| — | `smk-tier1-probe-reproduces-written` | SMK-001 | `spec: retro-evidence-gate#smk-tier1-probe-reproduces-written` |
| — | `smk-subjective-parked` | SMK-002 | `spec: retro-evidence-gate#smk-subjective-parked` |
| — | `smk-new-rule-missing-evidence-blocked` | SMK-003 | `spec: retro-evidence-gate#smk-new-rule-missing-evidence-blocked` |

## Impact

- Affected specs：新增 `retro-evidence-gate`
- Affected code：
  - Modified：`plugins/pr-flow/skills/pr-retrospective/SKILL.md`（Step 5.0 Evidence Gate 段、Step 5 Q5→action 映射表加證據前置條件、Lesson Classifier 前置說明指向 Evidence Gate）
  - Modified：`.claude/rules/11-skill-authoring.md`（新增「Retro-authored rule/hook 的三層證據標準」段，複用既有 verify-before-authoring / Cross-doc Cite 脈絡，不淨增 always-loaded 行數見 What Changes #5）
  - New：`scripts/lint_rule_evidence.py` + `scripts/tests/test_lint_rule_evidence.py`（純函式檢查器 + 合成 fixture 負向測試）
  - Modified：`.pre-commit-config.yaml`（註冊新 hook，warn-only 段 `verbose: true`）
- 不影響 `/pr-cycle-deep` 的 review-loop gate（各自獨立子系統）；不影響 typed-lessons 既有讀寫（新增狀態值向後相容）
- 自我約束（可機械檢查）：本 change 對 `.claude/rules/` 的淨新增 always-loaded 行數 = 0
