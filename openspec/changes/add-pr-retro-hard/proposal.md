## Why

`/pr-retro`（`plugins/growth/skills/pr-retrospective/SKILL.md`）Step 2 由 agent 自行從 PR context 推論 Q1–Q5 草稿，Step 3 直接交給使用者校準——**這些結論在被人判斷前沒有經過任何獨立挑戰**。下游 Step 5 通過 Evidence Gate 的項目會被建議寫入 `.claude/rules/*` 或 `CLAUDE.md`，那是每 session 全量載入的面，一條錯的指引會誤導此後每一次對話。

這不是新發現的缺口，而是既有 change `add-retro-evidence-gate` 已具名並刻意延後的續作。該 change 的假設表 W1 寫道：「retro agent 誠實執行分級與 probe（lint 只驗『有無標記』，不驗『標記是否誠實』）……最大假設風險：假證據標記可繞過 gate。減災：封閉列舉、**mob review 抽查**、三分法；殘餘由 golden-transcript harness 收斂（OOS）」，其 Out of Scope 亦寫明該 harness 是「收斂 W1 殘餘的唯一途徑，另開」。本 change 落實其中的「mob review 抽查」。

**為何是現在**：Evidence Gate 的實作已落地（`scripts/lint_rule_evidence.py`、`scripts/check_always_loaded_growth.py` 與 SKILL.md Step 5.0 皆存在），W1 因此成為該子系統最大的未減災風險——gate 能擋住「沒有證據標記」，但擋不住「標記所指的宣稱其實不成立」。

**為何需要跨家 LLM 而非單一 reviewer**：retro 草稿本身是 LLM 因果推論，同一個模型自審會系統性放過自己的推論偏誤。同時，跨家一致**不可**被當成證據——本 repo 已記錄 prompt 汙染使多家模型各自附和同一引導問句、以及某 voice 在交叉輪看過他家結果後反轉並全數附和兩種假共識。故本 change 的彙整規則對「一致」與「異議」刻意不對稱。

## What Changes

1. **新 skill `pr-retro-hard`（新 capability `retro-draft-mob-review`）**：在 `/pr-retro` 流程的兩個位置插入 mob review——M1 於 Step 2 草稿產生後、Step 3 交付使用者前，審 Q1–Q5 與各 lesson 的 confidence/source 評分；M2 於 Step 5 分級後、寫檔建議產生前，審 rule/hook 草稿文字。三個 voice：codex 與 antigravity 各自條件式（透過既有 `/codex-consult`、`/agy-consult`，其偵測與 auth gate 由該兩 skill 自有），加上一個無條件的 Claude 對抗式 subagent。`pr-retrospective` 為流程引擎所有者，本 skill 不重新推導其任何 gate。

2. **可執行彙整核心（新 capability `retro-review-aggregation`）**：彙整規則不以散文交由 agent 執行，而是 `aggregate_review.py` 純函式，且它就是 production path。輸入結構化 findings、voice 身分與輪次、settling check 執行結果、原始 confidence/source、草稿與 packet hash；輸出保留與排除的 findings、排除原因、tier disposition 建議、是否允許 mutation。SKILL.md 只記錄呼叫哪個 script、哪些回傳必須停止、哪些欄位交給人裁決；防 drift 靠腳本的 policy 說明輸出與 CI 雙向交叉檢查。

3. **對「一致」與「異議」不對稱**：mob 內部一致 MUST NOT 抬升 confidence、MUST NOT 改寫 source 為 cross-model（三個 voice 讀同一份草稿與同一套 prompt，依建構相關而非獨立）；只有異議能降。對抗 voice 的輸出 MUST NOT 計入共識票數。共識僅由獨立首輪建立，交叉輪只能反證、降級、撤回或補 settling check，不得新增獨立票。

4. **降級是建議而非裁決**：mob 判定證據不支持某宣稱時，產出的是餵給既有 Evidence Gate 的 tier 降級**建議**，MUST NOT 繞過或重新定義其 tier 語意，且該建議 MUST 以「已執行且結果為 confirmed 的 settling check」為前提——單純標籤不足以觸發機械動作。呈現給使用者的草稿項目 MUST NOT 被 mob 刪改，只能加註。

5. **Shadow 出貨**：本 change 的降級建議預設不生效，僅產生標注。生效條件與量測方法屬後續 change。

**非 BREAKING**：新增獨立 skill 與其命令，不改 `pr-retrospective` SKILL.md 任何既有步驟、不改四道 gate 的行為、不改 typed-lessons schema。使用者仍可照舊執行 `/pr-retro`。

## Non-Goals

範圍排除與否決方案記於 `design.md` 的 Goals/Non-Goals 段。摘要：不建 conformance eval 模組（oracle / fixture / mutation binding，屬後續 change）、不做 trigger accuracy fixture、不改 `/pr-retro` 既有步驟、不改 `tasks/gate_eval` 或 `tasks/skill_eval`、不 archive 尚未 archive 的 `add-retro-evidence-gate`。

## Capabilities

### New Capabilities

- `retro-draft-mob-review`：retro 草稿與規則草稿在交付人類判斷前的跨家審查契約——兩個插入點的邊界、voice 可用性與退化階梯、packet 純度（只含實際蒐集到的原文與開放式問題，嵌入的 PR 原文標為不可信引述資料）、共識僅由獨立首輪建立、每 voice 的輸出格式驗證與失敗上限、審查產物的隔離與陳舊偵測、外部模型資料邊界。
- `retro-review-aggregation`：審查結果的可執行彙整契約——finding 結構與封閉列舉的分類、settling check 的五種執行狀態、一致不得抬升評分的單向性、對抗 voice 不計票、草稿語意變更使既有審查結果失效、tier 降級以建議形式輸出且以已執行證據為前提、以及該契約與 SKILL.md 摘要表的雙向一致性檢查。

### Modified Capabilities

（無。本 change 不修改任何既有 capability 的 requirements。與既有 retro 證據閘門子系統的關係——包含其 spec 尚未 archive 因而無 canonical spec 可作 delta、以及本 change 刻意採「產出建議、不改其 tier 語意」的邊界——記於設計文件的 Context 段。本 repo 現有 specs 與本 change 的 requirements 無交集：作用於深度 PR review 迴圈的兩個 capability 屬不同子系統，記憶體分層 capability 僅被既有 park 出口使用而本 change 不新增 park 路徑。）

## Impact

- Affected specs：新增 `retro-draft-mob-review`、`retro-review-aggregation`
- Affected code：
  - New：`plugins/growth/skills/pr-retro-hard/SKILL.md`
  - New：`plugins/growth/skills/pr-retro-hard/schemas/review-finding.schema.json`
  - New：`plugins/growth/skills/pr-retro-hard/scripts/setup-retro-review-dir.sh`
  - New：`plugins/growth/skills/pr-retro-hard/scripts/aggregate_review.py`
  - New：`plugins/growth/skills/pr-retro-hard/scripts/tests/test_setup_retro_review_dir.py`
  - New：`plugins/growth/skills/pr-retro-hard/scripts/tests/test_aggregate_review.py`
  - New：`plugins/growth/skills/pr-retro-hard/scripts/tests/test_skill_contract.py`
  - New：`plugins/growth/commands/pr-retro-hard.md`
  - New：`commands/pr-retro-hard.md`（指向 plugin 命令檔的 symlink，與既有 `commands/pr-retro.md` 同形）
  - Modified：`skills/README.md`（新增索引列；並修正既有錯誤敘述——該檔仍稱 pr-retrospective 寫入 mycelium handover，實際寫入 retrospectives table）
  - Modified：`plugins/growth/.claude-plugin/plugin.json`（keywords）
  - Modified：`plugins/growth/package.json`（版本 lockstep bump，經 `scripts/sync-plugin-versions.sh`）
- 不影響 `plugins/growth/skills/pr-retrospective/SKILL.md`（引擎不動）、不影響 `/pr-cycle-deep` 的 review 迴圈、不影響 `tasks/mycelium` 的讀寫路徑。
- 執行期依賴：`aggregate_review.py` 與 `setup-retro-review-dir.sh` 由 SKILL.md 以 plugin 安裝路徑定址（沿用 `pr-retrospective` Step 0 解析 `installed_plugins.json` 的既有作法），不需要 repo 根層 skills symlink，亦不需要 `make install`。
