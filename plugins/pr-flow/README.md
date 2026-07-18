# pr-flow

Claude Code plugin for the full PR lifecycle: from writing to review, merge, and retrospective.

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install pr-flow@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `investigate` skill | 系統化除錯：先根因調查（五階段 + Iron Law）再修，然後交棒給 PR 生命週期。改寫自 garrytan/gstack（MIT），剝除 gstack 產品 plumbing。Scope Lock 階段可選用編輯範圍護欄（`freeze` scope-guard 為獨立 follow-up） |
| `pr-review-cycle` skill | 完整 PR 生命週期：PR 建立 → review → fix → CI → merge → archive |
| `pr-cycle-fast` skill | PR 生命週期快速版：Python state machine，1 reviewer，支援 resume |
| `pr-cycle-deep` skill | PR 生命週期深度版：mob review（Codex + Gemini）+ SDD amplifier-verifier |
| `mob-code-review-only` skill | Mob review 別人的 PR（只給建議、不修改）：共用 pr-cycle-deep 引擎，產出彙整建議貼回 PR，不改 code / 不 merge |
| `pr-retrospective` skill | PR 合併後事後檢討，提取改善點存入知識庫 |
| `bump-version` skill | 語意化版本號遞增（semver），更新 CHANGELOG |
| `claude-md-prune` skill | 定期清理 CLAUDE.md 過時內容，保持指引簡潔 |
| `verify-done` skill | 宣告完成前的端對端驗證：pre-commit、CI checks、Spectra amplifier、worktree 安全性 |
| `issue-triage` skill | GitHub Issue 定期盤點治理（唯讀優先）：逐 issue 研判 close / 更新範圍 / 整併 / label / 優先排序 |
| `/pr-review-cycle` command | 完整 PR 生命週期（含建立 PR → code review → merge） |
| `/pr-cycle-fast` command | PR 生命週期快速版（含 resume） |
| `/pr-cycle-deep` command | PR 生命週期深度版（mob review + SDD） |
| `/mob-code-review-only` command | Mob review 別人的 PR（只給建議、不修改） |
| `/pr-retro` command | 觸發 PR 事後檢討 |
| `/clean-wt` command | 統一清理本地分支與 worktree（merged / gone / 無價值殘留）；預設只報告，`--apply` 才刪 |
| `/debug-to-pr` command | 從 debug session 結果產生 PR |
