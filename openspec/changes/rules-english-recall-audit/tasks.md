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

## PR-C ⏳ 待重做：6 條 always-loaded rules 英文化

> 背景：原 PR-C 分支因誤推 main 後 revert，需從 `origin/main` 重建。
> 翻譯策略：rule body 只英文；Wrong/Right 雙欄表格取代 prose 說明；
> description frontmatter 保留中文觸發詞。

- [ ] T-C1 `01-language-and-tone.md` 英文化（~40 行，最小）
- [ ] T-C2 `02-error-and-import.md` 英文化（~60 行）
- [ ] T-C3 `03-security.md` 英文化（~50 行）
- [ ] T-C4 `15-irreversible-operations.md` 英文化（~160 行，含大表格）
- [ ] T-C5 `16-allowlist-hygiene.md` 英文化（~180 行，含大表格）
- [ ] T-C6 `13-bash-anti-patterns.md` 英文化（~500+ 行，最大，分 3 section）
- [ ] T-C7 PR 開 + `/pr-review-cycle-mob` 群審（翻譯正確性需多重 review）

**依賴**：PR5（worktree `pr-c-rules-english` HEAD 需確認，見 issue #61）

## PR-D ⏳ 待啟動：plugins SKILL.md body 英文化（分 4 批）

> 策略：description 保留中文觸發詞 + 英文 body；按觸發頻率 × 風險加權排序。
> 依賴：PR-C 完成後再啟動（先建立英文化慣例再推廣）。

### Batch 1（觸發頻率最高）

- [ ] T-D1 `plugins/bash-hygiene/skills/bash-anti-patterns/SKILL.md` body 英文化
- [ ] T-D2 PR + `/pr-review-cycle-mob`

### Batch 2

- [ ] T-D3 `plugins/pr-flow/skills/pr-review-cycle/SKILL.md` body 英文化
- [ ] T-D4 `plugins/pr-flow/skills/pr-review-cycle-mob/SKILL.md` body 英文化
- [ ] T-D5 PR + `/pr-review-cycle-mob`

### Batch 3

- [ ] T-D6 `plugins/bash-hygiene/skills/protect-push/SKILL.md` body 英文化
- [ ] T-D7 PR + `/pr-review-cycle`

### Batch 4（低頻，慢做）

- [ ] T-D8 `plugins/sdd/skills/spectra-amplifier/SKILL.md` body 英文化
- [ ] T-D9 `plugins/sdd/skills/qa-test-design/SKILL.md` body 英文化
- [ ] T-D10 PR + `/pr-review-cycle`
