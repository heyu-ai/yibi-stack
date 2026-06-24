# /mob-code-review-only — Mob Review 別人的 PR（只給建議、不修改）

多模型（Codex / Gemini agy）並行 mob review **別人的 PR**，產出彙整 review 報告並（經確認後）貼回 PR 作為建議留言。
與 `/pr-cycle-deep` 共用同一套 mob review 引擎，差別在於：目標是他人 PR、**只給修改建議、不動手改 code、不 re-review loop、不 merge / archive**。
偵測不到任何外部模型時提示退回 `/pr-review-cycle`（Claude-only review）。

## 用法

- `/mob-code-review-only #<PR number>` — review 指定 PR
- `/mob-code-review-only <PR URL>` — 同上，用 PR 連結

PR 編號（或連結）為**必填**——此 skill 一律 review 你指定的既有 PR。

## 執行

呼叫 `Skill(skill="mob-code-review-only", args="$ARGUMENTS")`，由 SKILL.md 主控完整流程。
