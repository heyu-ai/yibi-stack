## 1. 前置 probe（驗證後才動筆）

- [x] 1.1 以拋棄式 slash command 實測 `\$` escape 邊界（`\$1.00`、`\$ARGUMENTS`、`\\$1`、`\$x`），產出「官方引文照貼原文並加驗證戳記」決策要求的 probe 結果：每個輸入的實際 render 輸出 + 實測時 claude --version。驗證：probe 結果與官方描述逐項比對，差異（若有）記入 rule 11 段落草稿與 PR 描述。
- [x] 1.2 以拋棄式 skill（frontmatter 含 disallowed-tools: [Bash]）經 claude -p 實測列出的工具確實自可用池移除（要求跑 bash 時被拒或改道），確認 key 名 hyphen 形式生效。驗證：probe session 輸出顯示 Bash 不可用；結果與版本記入 PR 描述。

## 2. Lifecycle runbook opt-in 小節

- [x] 2.1 pr-review-cycle 在 report-only code review 區塊後提供「Auto-apply cleanups (optional)」小節，交付 Opt-in auto-apply cleanups subsection 契約三要素（opt-in 條件、/code-review --fix 與 /simplify 分工、套用後變更走既有 diff-review + commit 流程），同時維持 Report-only remains the default code review path（預設措辭不動）。落點：plugins/pr-flow/skills/pr-review-cycle/SKILL.md Step 2 之後。驗證：內容對照 spec review-cleanup-optin 前三個 scenario 逐項成立；uv run pre-commit run markdownlint-cli2 --files 該檔通過。
- [x] 2.2 pr-cycle-deep 的 Solo Review 段落加入同款小節，依「opt-in 小節落點：pr-review-cycle 與 pr-cycle-deep 兩處，措辭一致」決策與 2.1 措辭一致。落點：plugins/pr-flow/skills/pr-cycle-deep/SKILL.md。驗證：兩小節並排 diff 比對，opt-in 條件 / 分工 / commit-flow 三要素措辭一致（Wording consistent across both runbooks scenario）；markdownlint 單檔通過。

## 3. Skill authoring 文件

- [x] 3.1 rule 11 交付 disallowed-tools frontmatter documentation：依「採用官方 hyphen 形式 disallowed-tools，不用 issue 原文的 disallowedTools」決策使用 hyphen key 名，含官方引文原文、值格式（空格/逗號分隔字串或 YAML list）、語意（skill 執行期間移除、turn 結束解除）、至少一個具體使用情境（唯讀契約 skill / 背景 loop 禁 AskUserQuestion）、來源 URL + 查證日期戳記。落點：.claude/rules/11-skill-authoring.md 既有 frontmatter 段落群。驗證：對照 spec skill-authoring-feature-docs 的 Author consults rule 11 scenario 逐項成立。
- [x] 3.2 rule 11 交付 Literal dollar escape documentation：官方引文原文 + 邊界表（比照 spec 的 escape boundary table）+ 1.1 probe 版本戳記；若 probe 與官方文字不符，依 design 風險條款記實測行為並標注差異。驗證：對照 spec 的 Escape semantics stated scenario 與 Example 表。
- [x] 3.3 rule 13 交付 layer 消歧小節：依「rule 11 為 owner，rule 13 只放 cross-ref 消歧小節」決策，僅說明 `\$` 是 Markdown/skill-body 層替換（非 bash quoting）並 cross-ref rule 11，不重複完整規則。落點：.claude/rules/13-bash-anti-patterns.md。驗證：對照 spec 的 Rule 13 disambiguates the layer scenario；小節內不含邊界表（避免 dual-source drift）。
- [x] 3.4 skill 模板 frontmatter 提供 disallowed-tools 註解行（含值格式提示，比照現有 scope 註解形式）。落點：skills/_template/SKILL.md.tpl。驗證：對照 spec 的 Template exposes the key scenario；模板整檔仍為合法 YAML frontmatter 範例。

## 4. 版本與 CI

- [x] 4.1 依「plugin 內容變更走 lockstep version bump」決策執行 bash scripts/sync-plugin-versions.sh 帶入新 patch 版本，並依 CLAUDE.md 的 sdd lockstep gotcha 確認 plugins/sdd/.claude-plugin/plugin.json 同步。驗證：所有 plugins/*/package.json 版本一致且等於新版本號。
- [x] 4.2 全部變更 git add 後 make ci 全綠（未 add 的新內容 --all-files 掃不到；formatter hook 改樹則 commit 該改寫）。驗證：make ci exit 0，且跑完後 git diff --name-only 為空。
