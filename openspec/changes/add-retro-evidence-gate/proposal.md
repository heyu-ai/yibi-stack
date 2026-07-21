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

## Non-Goals（詳見 design.md）

範圍排除與否決方案記於 `design.md` 的 Goals/Non-Goals 段。摘要：不做 rules hot/cold tier 自動汰除、不改 review-loop gate、不建 golden-transcript eval harness、不修 harness-eval D7 scanner 計分 bug（issue #252）、不修 skill-trigger-eval baseline 未進版控（issue #220）。

## Capabilities

### New Capabilities

- `retro-evidence-gate`：`/pr-retro` 產出「加 rule / hook」action item 的寫入前證據契約——三層分級（Probed / Incident-cited / Subjective）、證據形式封閉列舉、三種 probe 執行結果與降級規則、Tier 3 park 出口與 recurrence 升級契約、寫入前 gate 與 commit-time lint 的分層強制、以及契約自身的純函式機械驗證。

（無 Modified Capabilities——本 change 不修改任何既有 capability 的 requirements。已上線的 review-loop 證據閘門與本 change 共用證據模式但作用於不相交的子系統，其關係記於 design.md 的 Context / Decisions，非本 change 的變更對象。本 repo 現有 specs 均與 retro 寫入路徑無 requirement 交集。）

## Impact

- Affected specs：新增 `retro-evidence-gate`
- Affected code：
  - Modified：`plugins/pr-flow/skills/pr-retrospective/SKILL.md`（Step 5.0 Evidence Gate 段、Step 5 Q5→action 映射表加證據前置條件、Lesson Classifier 前置說明指向 Evidence Gate）
  - Modified：`.claude/rules/11-skill-authoring.md`（新增「Retro-authored rule/hook 的三層證據標準」段，複用既有 verify-before-authoring / Cross-doc Cite 脈絡，不淨增 always-loaded 行數見 What Changes #5）
  - New：`scripts/lint_rule_evidence.py` + `scripts/tests/test_lint_rule_evidence.py`（純函式檢查器 + 合成 fixture 負向測試）
  - Modified：`.pre-commit-config.yaml`（註冊新 hook，warn-only 段 `verbose: true`）
- 不影響 `/pr-cycle-deep` 的 review-loop gate（各自獨立子系統）；不影響 typed-lessons 既有讀寫（新增狀態值向後相容）
- 自我約束（可機械檢查）：本 change 對 `.claude/rules/` 的淨新增 always-loaded 行數 = 0
