# /pr-review-cycle-mob — Mob Review PR 生命週期

多模型（Codex / Gemini agy）並行 mob review 完整 PR 生命週期。適合中大型 PR 或高風險改動。
偵測不到任何外部模型時自動退回 `/pr-review-cycle`（Claude-only）。

## 用法

- `/pr-review-cycle-mob` — 從當前 branch 開始（含建立 PR）
- `/pr-review-cycle-mob #<PR number>` — PR 已存在，直接跳到 mob review

## 執行

呼叫 `Skill(skill="pr-review-cycle-mob", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。
