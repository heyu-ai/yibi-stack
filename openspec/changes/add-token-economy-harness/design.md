## Context

harness-eval 現有 10 維度（D1–D10）由 `tasks/harness_eval/service.py` 的 `run_scan()` 串接，
每維度一個 `scanners/*.py`，回傳 `MechanicalFinding`；語意分由 `skills/harness-eval/SKILL.md`
Step 3 的 agent rubric 補充。`total_mechanical_max` 由各維度 `max_score` 自動加總（現為 69）。

本變更新增 D11「Context / Token Economy」：第一個 **budget-shaped（懲罰型）維度**——always-on
context 越多分數越低，用以衡量 token 經濟性並修正現行 additive 計分「獎勵多而非剛好」的偏差。

動機數據（yibi-stack 自掃，PR #127）：always-on context = root CLAUDE.md（9,701 字元）+ 14 個
`.claude/rules/*.md`（全部無 `glob:` frontmatter）= **115,278 字元、~30k tokens、3,007 行**，
progressive-disclosure 比例 = 0。本維度應使該 repo 的 D11 機械分落在低分（excessive + zero
disclosure），與其 D7=6/7 形成對照。

## Goals / Non-Goals

**Goals：**

- 新增 D11 維度（機械 5 + 語意 3 = 8），budget-shaped 計分
- `scan_context_economy()` 機械探針：always-on 字元分級 + progressive-disclosure 比例
- D11 機械分 < 3 時，TODO 自動加入 context 精簡建議
- 全程標示 token 為**近似估計**，不宣稱精準

**Non-Goals：**

- 不接 tokenizer 做精準計量（依賴重、跨模型不一致、違反毫秒原則）
- 不做 always-on ↔ rules 逐行冗餘偵測（屬 D7 職責）
- 不修改 D1–D10 評分邏輯
- 不新增 CLI flag

## Layer 3 — 資料模型（Brownfield）

> **Brownfield 判斷依據**：`MechanicalFinding`（`tasks/harness_eval/models.py`）已含
> `extra: dict[str, list[str]]` 擴充位與 `semantic_targets`，D11 沿用即可，**不修改 model**。
> `ScanOutput.total_mechanical_max` 由各 `MechanicalFinding.max_score` 加總，新增 D11（max 5）
> 後自動變為 74，無需改 model。

### Entity：MechanicalFinding（既有，verify intent）

D11 沿用既有欄位，新增 `extra` 鍵：

| `extra` 鍵 | 型別 | 值域 | 說明 |
|------------|------|------|------|
| `always_on_files` | `list[str]` | 相對 target_dir 的路徑 | 計入 always-on 預算的檔案（root CLAUDE.md + 非 glob rules） |
| `scoped_files` | `list[str]` | 相對 target_dir 的路徑 | path-scoped（glob rule / scoped skill）的檔案，作 progressive-disclosure 分子 |

數值摘要（總字元數、估計 token、ratio、分級）寫入 `findings` 文字（符合 C3：`extra` 僅存 `list[str]`）。

### 衝突偵測結果

`openspec/specs/` 為空（baseline）；`d11-context-economy-rubric` 為新 capability，與既有
`enhance-d5-behavior-harness` 的 `d5-behavior-quality-rubric` 無 entity / event 重疊。
`extra` 新增鍵不影響既有 `factory_helper_files` 鍵，無向後不相容。

## Decisions

### D11 採 budget-shaped 計分（context 越多分數越低）

這是本維度的核心設計，刻意與其他 additive 維度方向相反，修正 `docs/harness-eval-effectiveness-review.md`
C-1 指出的「additive 獎勵多而非剛好」偏差。

always-on budget 子項（機械 0–3），依 always-on 總字元數分級：

| always-on 字元數 | 分數 | 分級標籤 |
|------------------|------|----------|
| ≤ 20,000 | 3 | lean |
| 20,001 – 50,000 | 2 | moderate |
| 50,001 – 100,000 | 1 | heavy |
| > 100,000 | 0 | excessive |

**替代方案考量**：用行數分級——否決，因行長度差異大（CJK 密集行 vs 短行），字元數更穩定。
**替代方案考量**：接 tokenizer——否決，違反 C1 毫秒原則且跨模型不一致；字元數 × 係數已足夠分級。

### progressive-disclosure 比例（機械 0–2）

衡量「按需載入」相對「always-on」的占比，鼓勵 path-scoping：

`ratio = (glob-scoped rules + scoped skills) / (total rules + total skills)`

| ratio | 分數 |
|-------|------|
| ≥ 0.5 | 2 |
| 0.2 – 0.49 | 1 |
| < 0.2 | 0 |

- glob-scoped rule：frontmatter 含 `glob:`（沿用 `scanners/rules.py:_has_glob_frontmatter` 邏輯）
- scoped skill：SKILL.md frontmatter 含 `allowed-tools` / `allowed_tools` / `glob` / `files` / `paths`
  （沿用 `scanners/skills.py:_SCOPING_KEYS`）
- 分母為 0（無 rule 也無 skill）時，此子項給滿分 2（無可漸進揭露的對象，不懲罰）

**程式碼重用**：偵測邏輯重用 `scanners/rules.py` 與 `scanners/skills.py` 既有 helper，避免重複實作。

### always-on 集合定義

always-on = root `CLAUDE.md` + `.claude/rules/*.md` 中**無** `glob:` frontmatter 者。

**替代方案考量**：把所有 rules 都計入——否決，glob-scoped rule 是 path-conditional，不應算 always-on
（否則懲罰了正確使用 scoping 的 repo）。

### 字元→token 係數僅供顯示，不影響評分

評分一律以**字元數**分級（門檻如上）。findings 文字另附 `~tokens ≈ chars / 3.5（CJK-heavy 近似）`
作參考，並明確標註「近似估計」。評分不依賴 token 數，規避 tokenizer 不一致風險（B-3 / A2）。

### TODO 觸發門檻為 D11 機械分 < 3

機械分 < 3 表示 always-on budget 偏 heavy/excessive 或 progressive-disclosure 偏低——值得精簡。
≥ 3 表示預算精實或已善用 scoping，不需提示。

邊界：D11 機械 = 2 → 顯示；D11 機械 = 3 → 不顯示。

## Implementation Contract

**新增 `tasks/harness_eval/scanners/context_economy.py`：**

```python
def scan_context_economy(target_dir: Path) -> MechanicalFinding:
    # 1. 收集 always-on 檔案：root CLAUDE.md + 非 glob rules
    # 2. 統計總字元數 -> always-on budget 子項分級（0-3）
    # 3. 計算 progressive-disclosure 比例 -> 子項（0-2）
    # 4. semantic_targets = 最大的前 N 個 always-on 檔案
    # 5. extra["always_on_files"] / extra["scoped_files"]
    # 回傳 MechanicalFinding(dimension="D11", max_score=5, ...)
```

**`scanners/__init__.py`**：export `scan_context_economy`。

**`service.py` `run_scan()`**：dimensions 清單追加
`_safe_scan(scan_context_economy, target, "D11", "Context / Token Economy", 5)`。
`total_mechanical_max` 自動由 69 變 74。

**`skills/harness-eval/SKILL.md`：**

- Step 2：機械分維度滿分加列 `D11=5`，「機械總滿分 69」→「74」。
- Step 3：新增 D11 語意（3 分）：
  - right-sizing（2 分）：讀 `semantic_targets`（最大 always-on 檔案），判斷內容是否「值得」
    always-on，或可移至按需載入的 skill/doc。多數內容站得住 → 2；部分可移 → 1；大段內容明顯
    應 on-demand → 0。
  - effort 相稱性（1 分）：重型 skill 的 `effort:` 等級與 body 規模相稱（補 D4 只偵測「有沒有設」
    的回饋閉環）；相稱或無重型 skill → 1；明顯不符 → 0。
- Step 4：報告分數表新增 D11 列；`總分 /115` → `/123`；新增 D11 TODO 觸發（機械分 < 3）：

  ```text
  [D11, medium-effort, high-impact] always-on context 過肥（~<chars> 字元、約 <tokens> tokens，近似估計）
    - 將 always-on rule 改為 path-scoped：在 frontmatter 加 glob: 限定生效路徑
    - 將大段內容移至按需載入的 skill/doc，降低每回合 always-on 預算
  ```

**`plugins/harness/README.md`**：維度描述由「8 維度」更新為涵蓋 D1–D11（同步既有落差）。

**Acceptance criteria：**

- always-on > 100,000 字元 → budget 子項 0 分；≤ 20,000 → 3 分
- 含 `glob:` 的 rule 不在 `extra["always_on_files"]`，且計入 progressive-disclosure 分子
- `ratio` 計算正確（含分母為 0 給滿分的 guard）
- `service.py` 納入 D11 後 `total_mechanical_max == 74`
- SKILL.md Step 2/3/4 三處同步更新，spec 與 SKILL.md 行為守則一致（rule 11「Spec and SKILL.md
  behavioral guards must stay in sync」）

## Risks / Trade-offs

- **[Risk] 字元→token 係數粗略，跨模型不一致**（B-3）→ 緩解：評分只用字元數分級，token 數僅作
  顯示且標示「近似」；不對外宣稱精準。
- **[Risk] 新增維度改變總分分母（/115 → /123），破壞跨時間可比性** → 接受：等級採百分比、目前無
  harness-track 歷史；design A4 記錄，待日後 harness-track 做版本化基準。
- **[Risk] 「非 glob rule 即 always-on」高估**（CC 對無 glob rule 的實際載入時機可能更細緻）→
  接受：proxy 偏保守（傾向多標 always-on），寧可提醒過度也不漏報；A1 記錄。
- **[Risk] D11 與 D1（CLAUDE.md 行數）、D7（rule 去重）職責重疊** → 緩解：D11 只衡量「預算大小 /
  漸進揭露比例」，明確不碰「內容品質 / 去重」；Non-Goals 與 spec 各 Requirement 標註互斥邊界。
- **[Risk] right-sizing 語意判斷主觀** → 緩解：rubric 附可觀察指標（「大段 how-to 內容是否能成為
  on-demand skill」「rule 是否限定特定路徑才需要」），縮小模糊空間。
