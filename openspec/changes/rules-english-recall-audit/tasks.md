# tasks.md — rules-english-recall-audit

> 版本：v1.0 | 日期：2026-05-25 | 對應 proposal.md v2.0

## PR-A #48 ✅ MERGED 2026-05-23

- [x] T-A1 `.claude/hooks/bash-ap1-inline-check.sh` 補寫 `rule_id`、`outcome`、`cmd_snippet` 欄位
- [x] T-A2 `plugins/bash-hygiene/hooks/bash-ap1-inline-check.sh` 同步補 audit 欄位
- [x] T-A3 新增 `commands/recall.md`（包裝 session-memory `lessons show/search`）
- [x] T-A4 `.claude/hooks/pre-commit.sh` 擴大覆蓋 markdownlint + ruff format check

## PR-B #50 ✅ MERGED 2026-05-23

- [x] T-B1 `skills/pr-retrospective/SKILL.md` Step 5 加 3-condition promotion gate
- [x] T-B2 rule 14 內容合併到 rule 13（`13-bash-anti-patterns.md`）
- [x] T-B3 `14-shell-quoting-hygiene.md` 刪除
- [x] T-B4 `12-auto-handover.md` 移至 `docs/rules-reference/`

## PR-C #77 ✅ MERGED 2026-05-25

> cherry-pick 策略：從舊 PR-C draft commits 逐一 cherry-pick 到新 worktree，
> 逐衝突解決（rule 15 保留 PR #59 revert checklist；rule 16 inline 翻譯 PR #66 /less-permission-prompts section）。

- [x] T-C1 `01-language-and-tone.md` 英文化
- [x] T-C2 `02-error-and-import.md` 英文化
- [x] T-C3 `03-security.md` 英文化
- [x] T-C4 `15-irreversible-operations.md` 英文化
- [x] T-C5 `16-allowlist-hygiene.md` 英文化（含 PR #66 /less-permission-prompts section 翻譯）
- [x] T-C6 `13-bash-anti-patterns.md` 英文化
- [x] T-C7 PR #77 merged + markdownlint fixup

## PR-D ✅ plugins SKILL.md body 英文化（分 4 批）

> 策略：description 保留中文觸發詞 + 英文 body；按觸發頻率 × 風險加權排序。

### Batch 1 ✅ MERGED #79

- [x] T-D1 `plugins/bash-hygiene/skills/bash-anti-patterns/SKILL.md` body 英文化
- [x] T-D2 PR + `/pr-review-cycle-mob`

### Batch 2 ✅ MERGED #84

- [x] T-D3 `plugins/pr-flow/skills/pr-review-cycle/SKILL.md` body 英文化
- [x] T-D4 `plugins/pr-flow/skills/pr-review-cycle-mob/SKILL.md` body 英文化
- [x] T-D5 PR + `/pr-review-cycle-mob`

### Batch 3 ✅ landed on main directly (62dced8)

- [x] T-D6 `plugins/bash-hygiene/skills/protect-push/SKILL.md` body 英文化
- [x] T-D7 PR + `/pr-review-cycle`

### Batch 4 ✅ MERGED #89

- [x] T-D8 `plugins/sdd/skills/spectra-amplifier/SKILL.md` body 英文化
- [x] T-D9 `plugins/sdd/skills/qa-test-design/SKILL.md` body 英文化
- [x] T-D10 PR + `/pr-review-cycle`

## PR-E ✅ MERGED #86 — .claude/rules/ 04-11 English translation

> Scope: PR-C only covered 01/02/03/13/15/16; rules 04-11 body was still Chinese.
> rules/ files are high-frequency context-loaded the same as SKILL.md — same rationale applies.

- [x] T-E1 `04-module-structure.md` translate to English
- [x] T-E2 `05-pydantic-models.md` translate to English
- [x] T-E3 `06-config-pattern.md` translate to English
- [x] T-E4 `07-db-pattern.md` translate to English
- [x] T-E5 `08-cli-pattern.md` translate to English
- [x] T-E6 `09-test-conventions.md` translate to English
- [x] T-E7 `10-parser-pattern.md` translate to English
- [x] T-E8 `11-skill-authoring.md` translate to English
- [x] T-E9 PR + `/pr-review-cycle`
