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
| `pr-review-cycle` skill | 完整 PR 生命週期：PR 建立 → review → fix → CI → merge → archive |
| `pr-review-cycle-mob` skill | Mob review：多模型（Codex / Gemini）並行 R1+R2 交叉 debate，適合大型 PR |
| `pr-retrospective` skill | PR 合併後事後檢討，提取改善點存入知識庫 |
| `bump-version` skill | 語意化版本號遞增（semver），更新 CHANGELOG |
| `claude-md-prune` skill | 定期清理 CLAUDE.md 過時內容，保持指引簡潔 |
| `/pr-review-cycle` command | 完整 PR 生命週期（含建立 PR → code review → merge） |
| `/pr-review-cycle-mob` command | Mob review 完整 PR 生命週期（多模型並行） |
| `/pr-retro` command | 觸發 PR 事後檢討 |
| `/clean-gone` command | 清除遠端已刪除的本地追蹤 branch |
| `/clean-merged` command | 清除已合併的本地 branch |
| `/debug-to-pr` command | 從 debug session 結果產生 PR |
