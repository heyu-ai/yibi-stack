## Why

issue #145 指出兩個文件缺口，經 2026-07-23 盤點確認全數未完成、且前提在目前 Claude Code 官方文件仍成立：
（1）`/code-review --fix` 與 `/simplify` 已能自動套用 cleanup 修正，但 pr-review-cycle 與 pr-cycle-deep 的
Step「Code Review」只記載 report-only 路徑，明寫「does not modify code」，缺少 opt-in 自動套用路徑的指引；
（2）skill frontmatter 的 `disallowed-tools` key（把「唯讀 skill 不改 code」從慣例變成硬保證）與
skill 內文輸出 literal `$` 的 `\$` escape 機制，在 rule 11、rule 13 與 skill 模板中零著墨——
rule 11 後續已補齊 effort 與 v2.1.186 各 frontmatter key 的文件，唯獨這兩項缺席。

issue 原文的檔案清單已過時（pr-review-cycle-mob 已由 pr-cycle-deep 取代；引用的 spectra fork skill
佐證已離開本 repo），本 change 以更新後的範圍執行。

## What Changes

- pr-review-cycle 的 Step 2（Code Review）之後新增「Auto-apply cleanups（optional）」小節：
  說明 /code-review --fix 與 /simplify 的分工（前者偵測 bug 並可自動套用全部發現、
  後者僅做 cleanup 不找 bug），標明為 opt-in、預設 report-only 不變，
  並註明自動套用產生的 code changes 必須走既有的 diff-review + commit 流程。
- pr-cycle-deep 的 Solo Review 段落（原「does not modify code」處）加入同樣的 opt-in 小節，
  措辭與 pr-review-cycle 一致。
- rule 11（.claude/rules/11-skill-authoring.md）新增「Frontmatter — disallowed-tools（Optional）」
  段落：官方 key 名稱為 disallowed-tools（hyphen 形式；v2.1.186 起 key 名 case/separator-insensitive，
  文件以官方 hyphen 形式為準）、值格式（空格/逗號分隔字串或 YAML list）、語意
  （skill 執行期間自列表移除工具，turn 結束後解除）、適用情境（唯讀契約 skill、背景 loop 禁用
  AskUserQuestion），並引用官方文件原文（Cross-doc Cite 紀律：貼原文不憑記憶改寫）。
- rule 11 同段補 `\$` literal-dollar escape 指引：單一反斜線直接置於 `$` 前才轉義
  （`\$1.00`、`\$ARGUMENTS`）；`\\$1` 不轉義；反斜線在其他字元前原樣保留。
- rule 13（.claude/rules/13-bash-anti-patterns.md）新增「`\$` literal dollar in skill command
  body」小節：定位為 Markdown/skill 內文層的機制（非 bash 層），cross-ref rule 11 完整說明，
  避免與 bash 的 `\$` 語意混淆。
- skill 模板（skills/_template/SKILL.md.tpl）frontmatter 加入 disallowed-tools 註解行
  （比照現有 scope 的註解形式）。

## Capabilities

### New Capabilities

- `review-cleanup-optin`: pr-review-cycle 與 pr-cycle-deep 的 code review 步驟提供 opt-in
  自動套用 cleanup 路徑；預設維持 report-only，套用後的變更必須經 diff-review 與 commit 流程。
- `skill-authoring-feature-docs`: rule 11/13 與 skill 模板記載 disallowed-tools frontmatter
  與反斜線-dollar（literal-dollar escape）的官方語意，供 skill 作者引用。

### Modified Capabilities

（無——pr-review-convergence 的 evidence gate requirements 不受本次文件變更影響）

## Impact

- Affected specs: 新增 review-cleanup-optin 與 skill-authoring-feature-docs 兩個 capability spec
- Affected code:
  - Modified: plugins/pr-flow/skills/pr-review-cycle/SKILL.md
  - Modified: plugins/pr-flow/skills/pr-cycle-deep/SKILL.md
  - Modified: .claude/rules/11-skill-authoring.md
  - Modified: .claude/rules/13-bash-anti-patterns.md
  - Modified: skills/_template/SKILL.md.tpl
  - Modified: plugins/pr-flow/package.json（plugin 內容變更需 lockstep 版本 bump）
  - New: （無）
  - Removed: （無）
