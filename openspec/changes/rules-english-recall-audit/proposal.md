# Proposal: rules-english-recall-audit

> 版本：v1.0 | 日期：2026-05-23 | 狀態：Draft

## Why

yibi-stack 的 agent-facing surface（`.claude/rules/` + `skills/` + `plugins/*/skills/`）合計約 363KB，其中：

- **`.claude/rules/` 84KB**：8 條無 `globs` frontmatter 的 rule 每 session 啟動時全部載入（~21K tokens）。這些 rule 全部用中文，而 CJK 字符的 tokenizer 成本是英文的 4–6 倍。
- **audit log 無效**：`~/.agents/bash-hygiene-events.jsonl` 有 1,833 個 event，但缺少 `rule_id`、`outcome`、`cmd_snippet` 欄位——無法量化哪條 AP 最常觸發，也無法決定哪個值得寫 hook 自動修。
- **session-memory 無召回入口**：`pr-retrospective` 寫入 145 條 retro lesson 到 `~/.agents/`，但 agent 沒有 slash command 能主動查詢。降級到 session-memory 的 lesson 實際上成了 dead store。
- **promotion gate 形同虛設**：14 天內 9 次 rule edit、只有 1 次寫成 hook。「寫 rule 比寫 hook 容易」使預設行為偏向 rule，導致 session-start token 持續膨脹。

## What Changes

### PR-A：audit log fix + /recall + pre-commit gate（優先，立即見效）

1. **audit log P0 fix**：`.claude/hooks/bash-ap1-inline-check.sh`（及 plugin 版）補寫欄位 `rule_id`、`outcome`（`block`/`warn`/`pass`）、`cmd_snippet`（前 200 chars）
2. **/recall command**：新增 `commands/recall.md`，包裝 `tasks/session_memory/cli.py` 既有的 `lessons show/search`；自動從 git repo basename 推 `--project`
3. **pre-commit gate**：`.claude/hooks/pre-commit.sh` 擴大覆蓋 markdownlint（`.claude/rules/` / `skills/` / `plugins/` 改動檔）+ ruff format check（`.py` 改動檔）

### PR-B：promotion gate + rule 結構調整

1. **promotion gate**：在 `skills/pr-retrospective/SKILL.md` Step 5「Lesson Classifier」加 3 條強制 gate：
   - automation-infeasible（先評估 hook 可行性）
   - onboarding-relevant（新貢獻者 day-1 也會犯）
   - no existing rule covers it（先搜 extend，再建新檔）
2. **rule 合併**：rule 14（shell-quoting-hygiene）內容合併到 rule 13（bash-anti-patterns）；rule 12（auto-handover）降級到 `docs/`（hook 已自動化，rule 為純參考文件）

### PR-C：6 條無 globs rule 英文化

1. **英文化目標**：rule 01/02/03/13/15/16（無 `globs`，每 session 全部載入）改成英文，Wrong→Right 雙欄表格取代 prose 說明
2. **雙語策略**：rule body 只英文；人類學習走 `/recall` 召回 session-memory 中文 retro 原文

### PR-D：plugins SKILL.md body 英文化（分次）

1. **英文化順序**（按觸發頻率 × 風險加權）：
   - 1st: `plugins/bash-hygiene/skills/bash-anti-patterns/`
   - 2nd: `plugins/pr-flow/skills/pr-review-cycle*/`
   - 3rd: `plugins/bash-hygiene/skills/protect-push/`
   - 4th+: spectra-amplifier、qa-test-design（低頻，慢做）
2. **description 策略**：保留中文觸發詞（對齊使用者輸入習慣）+ 英文 body

## Non-Goals

- **06/07/08/10 rule 降級**：4 條已有 `globs: tasks/**/...` frontmatter，session start token 影響 ≈ 0；且它們規範 yibi-stack 特有 `tasks/<module>/` layout，不需要移動或跨專案共享
- **rule 中文版雙份維護**：雙語文件的 drift 風險高於收益；人類學習走 `/recall`，不另建 `docs/conventions-zh/`
- **plugin rules/ 跨專案共享**：Claude Code plugin 規範只有 skills/commands/hooks/agents/mcp 載體，沒有 rules/ 機制；`plugins/bash-hygiene/rules-context.md` 是死檔（沒有任何 SKILL.md 引用它）

## Capabilities

### New Capabilities

- `recall-command`: slash command `/recall <query>` — 查詢 session-memory lessons/approaches，自動偵測 project，群組化格式輸出（lesson / approach / insight）
- `bash-audit-log-v2`: enriched hook events with `rule_id`, `outcome`, `cmd_snippet` — 支援「哪條 AP 最常觸發」量化分析

### Modified Capabilities

- `pr-retrospective-gate`: Lesson Classifier 加 3-condition promotion gate — 不通過只寫 session-memory，不開新 rule 檔
- `rules-english`: 6 條無 globs rule 英文化 + Wrong→Right 表格 — session start token 從 ~21K 降至 ~10K

## Impact

| 影響範圍 | 改動 |
|---------|------|
| `commands/recall.md` | 新增（PR-A） |
| `.claude/hooks/bash-ap1-inline-check.sh` | 補 audit 欄位（PR-A） |
| `plugins/bash-hygiene/hooks/bash-ap1-inline-check.sh` | 同步補 audit 欄位（PR-A） |
| `.claude/hooks/pre-commit.sh` | 擴大 markdownlint + ruff format 覆蓋（PR-A） |
| `skills/pr-retrospective/SKILL.md` | 加 promotion gate（PR-B） |
| `.claude/rules/13-bash-anti-patterns.md` | 合併 14 的內容（PR-B） |
| `.claude/rules/14-shell-quoting-hygiene.md` | 刪除（PR-B） |
| `.claude/rules/12-auto-handover.md` | 移到 `docs/`（PR-B） |
| `.claude/rules/{01,02,03,13,15,16}.md` | 英文化（PR-C） |
| `plugins/*/skills/*/SKILL.md` | body 英文化（PR-D，分次） |
