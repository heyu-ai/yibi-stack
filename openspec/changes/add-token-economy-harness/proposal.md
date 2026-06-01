## Why

harness-eval 目前 10 維度（D1–D10）只衡量 harness 的**結構齊備度**，完全沒有任何維度衡量
**context / token 經濟性**——也就是 agent 每回合「還沒開始工作就先吃掉多少 context 預算」。
這是 agentic 效能最關鍵的變數之一，卻是現行工具的盲點。

實證（見 `docs/harness-eval-effectiveness-review.md`，PR #127）：對 yibi-stack 自身掃描時，
always-loaded context 約 **115,278 字元（~30k tokens、3,007 行）**，且 14 個 `.claude/rules/*.md`
**全部非 path-scoped**（progressive-disclosure ratio = 0）。harness-eval 把這批 rules 在 D7
評為 **6/7 高品質**，對其 token 成本**零警告**；D1 只檢查 CLAUDE.md 的 216 行。換言之，工具把本
repo 最該被檢討的 token-economy 特徵，當成了品質加分。

更深層問題：現行 /115 是 **additive**——靠「多加 hook / rule / skill」就能堆高分，沒有
over-engineering 懲罰。本變更引入第一個 **budget-shaped（懲罰型）維度**：always-on context
越多、分數越低，直接修正「additive 獎勵『多』而非『剛好』」的計分偏差。

## Layer 1 — User Stories

### US-001：評估能反映 always-on context 預算，而非只看結構齊不齊

**Persona**：用 harness-eval 評估專案 agentic 就緒度的開發者；他的 repo 結構很齊（hook、rule、
skill 都有），但他懷疑 always-on context 過肥拖慢 / 稀釋 agent。
**Action**：執行 `harness-eval`，查看 D11 分數與 findings。
**Outcome**：看到 always-on context 的字元數估計與分級（lean / moderate / heavy / excessive），
立刻知道「結構齊」與「context 精實」是兩回事，且本維度的分數會因 context 過肥而**下降**。

**Acceptance Criteria**：

- AC-001-1：當 always-on 字元數 > 100,000 時，D11 always-on budget 子項得 0 分（GIVEN/WHEN/THEN 可驗證）
- AC-001-2：當 always-on 字元數 ≤ 20,000 時，always-on budget 子項得滿分（3 分）
- AC-001-3：D11 是 budget-shaped——context 越多分數越低，與其他 additive 維度方向相反

### US-002：機械探針量出 always-on 預算與 progressive-disclosure 比例

**Persona**：同上開發者；他想知道有多少 rule / skill 是 path-scoped（按需載入）而非 always-on。
**Action**：執行 `harness-eval`，機械掃描在毫秒內完成。
**Outcome**：`scan_context_economy()` 的 JSON 輸出含 always-on 檔案清單、總字元數、
progressive-disclosure 比例；最大的幾個 always-on 檔案被放入 `semantic_targets` 供語意評分。

**Acceptance Criteria**：

- AC-002-1：root `CLAUDE.md` + 無 `glob:` frontmatter 的 `.claude/rules/*.md` 被計入 always-on 集合
- AC-002-2：有 `glob:` frontmatter 的 rule 被視為 path-scoped，**不**計入 always-on 預算
- AC-002-3：progressive-disclosure 比例 = (glob-scoped rules + scoped skills) / (total rules + total skills)

### US-003：context 過肥時，優先 TODO 出現精簡建議

**Persona**：同上開發者，D11 拿到低分；他不知道下一步怎麼瘦身。
**Action**：查看 harness-eval 的「優先改善 TODO」清單。
**Outcome**：看到 `[D11, medium-effort, high-impact]` 條目，指向「把 always-on rule 改為
path-scoped（加 `glob:` frontmatter）」或「把大段內容移到按需載入的 skill/doc」等可操作步驟。

**Acceptance Criteria**：

- AC-003-1：D11 機械分 < 3 時，TODO 出現 context 精簡建議條目
- AC-003-2：建議條目含具體動作（加 `glob:` frontmatter / 移至 on-demand skill）
- AC-003-3：建議文字明確標示字元數→token 為**近似估計**，非精準計量

## What Changes

- **新增 D11「Context / Token Economy」維度**（機械 5 + 語意 3 = 8 分），衡量 always-on context
  預算與 progressive-disclosure 程度，採 budget-shaped 計分（context 越多分數越低）。
- **新增 `scan_context_economy()` 機械探針**（`tasks/harness_eval/scanners/context_economy.py`）：
  - 計算 always-on 字元數（root CLAUDE.md + 非 glob-scoped rules），依字元分級給 0–3 分
  - 計算 progressive-disclosure 比例（glob-scoped rules + scoped skills 占比），給 0–2 分
  - 最大的 always-on 檔案放入 `semantic_targets`；明細放入 `extra`
- **D11 語意 rubric**（`skills/harness-eval/SKILL.md` Step 3）：
  - right-sizing 判斷（2 分）：最大的 always-on 內容是否「值得」always-on，或可改為按需揭露
  - effort 相稱性（1 分）：重型 skill 的 `effort:` 等級是否與其 body 規模相稱（補上現行只偵測
    「有沒有設 effort」的回饋閉環）
- **SKILL.md Step 2 / Step 4 更新**：機械總滿分 69 → 74；報告分數表新增 D11 列；總分 /115 → /123。
- **D11 TODO 觸發**（Step 4）：D11 機械分 < 3 時加入 context 精簡建議。

## Non-Goals

- **不**做精準 token 計量——只用字元數 × 係數的粗略 proxy，並全程標示為近似（runtime 成本依
  session 實際載入而定，static scan 無法精準，見 design Risks）。
- **不**修改其他維度（D1–D10）的評分邏輯；D11 與 D1（CLAUDE.md 行數）、D7（rule 去重品質）
  職責互斥——D11 只管「預算大小 / 是否漸進揭露」，不碰「內容品質 / 去重」。
- **不**新增 CLI flag；D11 隨既有 `scan` 流程一併輸出。
- **不**實作 always-on 內容與 rules 的逐行冗餘偵測（屬 D7 語意「不重複」職責）。

## Layer 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | rules 以 `.claude/rules/*.md` 存放，無 `glob:` frontmatter 者為 always-on | 若 CC 載入規則改變，always-on 集合判定需調整 |
| A2 | 字元數可作 token 的粗略 proxy（CJK-heavy 約 chars/3.5） | 係數依 tokenizer 而異；僅作分級用，不對外宣稱精準 |
| A3 | progressive-disclosure 訊號 = rule 的 `glob:` + skill 的 scoping 欄位（`allowed-tools`/`glob`/`files`） | 若 CC 新增其他 scoping 機制，比例分母/分子需擴充 |
| A4 | 新增維度可改變總分分母（/115 → /123），因等級採百分比、且尚無 harness-track 歷史比較 | 若日後有跨時間追蹤，需做版本化基準 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | `scan_context_economy()` 執行時間不可超過 100ms | harness-eval 機械分毫秒完成原則（與 D5 spec C1 一致） |
| C2 | D11 機械分上限 5、語意分上限 3、總上限 8；不更動 D1–D10 既有分值 | 維持各維度互斥與既有比較基準 |
| C3 | `extra` 欄位型別維持 `dict[str, list[str]]`；數值摘要寫入 `findings` 文字 | `models.py` 現有 schema，不修改 model |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 精準 token 計量（接 tokenizer） | 增加重依賴、跨模型不一致、違反 C1 毫秒原則 | 可作 `harness-eval-focus D11 --deep` 子命令 |
| always-on ↔ rules 逐行冗餘偵測 | 屬 D7 語意「規則不重複」職責，避免維度重疊 | 由 D7 既有 rubric 涵蓋 |
| runtime context 實測（攔截實際載入） | static scan 無法觀測 runtime；需 hook 層整合 | 長期研究方向 |

## Layer 5 — 可測試性

### Done 定義

- [ ] `tasks/harness_eval/scanners/context_economy.py` 新增 `scan_context_economy()`，回傳
      `MechanicalFinding(dimension="D11", max_score=5)`
- [ ] `service.py` 的 `run_scan()` 納入 D11，`total_mechanical_max` 變為 74
- [ ] `test_scanners.py` 新增至少 3 個 D11 測試（budget 分級邊界、glob-scoped 排除、ratio 計算）
- [ ] `skills/harness-eval/SKILL.md`：Step 2 機械總滿分更新為 74、Step 3 新增 D11 語意 rubric、
      Step 4 報告表新增 D11 列且總分改 /123、D11 TODO 觸發規則
- [ ] `make ci` 通過（ruff + mypy + pytest）

### 冒煙測試情境

**ST-001：肥 always-on context 得低分**
- GIVEN repo 的 root CLAUDE.md + 非 glob rules 合計 > 100,000 字元
- WHEN 執行 `scan_context_economy()`
- THEN always-on budget 子項 = 0 分

**ST-002：glob-scoped rule 不計入 always-on**
- GIVEN 一個 rule 檔含 `glob:` frontmatter
- WHEN 執行 `scan_context_economy()`
- THEN 該檔不在 `extra["always_on_files"]`，且計入 progressive-disclosure 分子

**ST-003：progressive-disclosure 比例計算**
- GIVEN 5 個 rules 中 2 個有 `glob:`、4 個 skills 中 1 個有 scoping 欄位
- WHEN 計算比例
- THEN ratio = 3/9 ≈ 0.33

**ST-004：context 過肥時 TODO 出現精簡建議**
- GIVEN D11 機械分 = 0（excessive budget + zero progressive disclosure）
- WHEN agent 執行 Step 4
- THEN TODO 含 `[D11, ...]` context 精簡條目，且標示 token 為近似估計

## Capabilities

### New Capabilities

- `d11-context-economy-rubric`：D11 維度的機械探針定義（always-on 預算分級、progressive-disclosure
  比例）與語意評分（right-sizing、effort 相稱性），含 budget-shaped 計分與 TODO 觸發條件。

### Modified Capabilities

（無；`openspec/specs/` 目前為空。`harness-eval` 既有 D1–D10 行為未變更。）

## Impact

- 受影響的規格：`d11-context-economy-rubric`（新建）
- 受影響的程式碼：
  - 新增：`tasks/harness_eval/scanners/context_economy.py`
  - 修改：`tasks/harness_eval/service.py`（`run_scan()` 納入 D11）
  - 修改：`tasks/harness_eval/tests/test_scanners.py`（D11 探針測試）
  - 修改：`skills/harness-eval/SKILL.md`（D11 機械/語意 rubric、總分、報告表、TODO）
  - 修改：`plugins/harness/README.md`（維度數由「8」更新為含 D11；同步既有 D1–D10 落差）
