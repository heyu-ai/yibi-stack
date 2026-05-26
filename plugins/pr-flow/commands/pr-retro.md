# /pr-retro -- PR Retrospective 入口

跑完 `/pr-review-cycle-codex` 後收尾用：agent 從 PR context 推論 5 題答案草稿，使用者校準後
寫入 mycelium（標 `pr-retrospective` tag，不污染 handover-back），並建議下游動作。

## 用法

- `/pr-retro` -- 自動偵測 current branch 對應的 PR
- `/pr-retro --pr 123` -- 指定 PR 號

## 執行

呼叫 `Skill(skill="pr-retrospective", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。
