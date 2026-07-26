# /pr-review-cycle — 完整 PR 生命週期

完整 PR 生命週期：建立 PR → code review → parallel review → fix → CI → merge。
適用任何專案純 PR review（不含 SDD spectra 流程）；中大型 PR 或多模型壓力測試請改用 `/pr-cycle-deep`。

## 用法

- `/pr-review-cycle` — 從當前 branch 開始（含建立 PR）
- `/pr-review-cycle #<PR number>` — PR 已存在，直接跳到 Step 2（code review）

## 執行

呼叫 `Skill(skill="pr-review-cycle", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。
