# /pr-cycle-deep — Mob Review PR 生命週期

多模型（Codex / Gemini agy）並行 mob review 完整 PR 生命週期。適合中大型 PR 或高風險改動。
偵測不到任何外部模型時自動退回 `/pr-review-cycle`（Claude-only）。

## 用法

- `/pr-cycle-deep` — 從當前 branch 開始（含建立 PR）
- `/pr-cycle-deep #<PR number>` — PR 已存在：略過建立 PR，但仍先跑 Step 1 Review Contract gate，再進 mob review

## 執行

呼叫 `Skill(skill="pr-cycle-deep", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。
