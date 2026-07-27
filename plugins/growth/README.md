# growth

Claude Code plugin for extracting knowledge from finished work and retaining it across conversations.

## Prerequisites

These skills require the yibi-stack repository to be cloned and `make install` to be run for task execution
(mycelium and `learn` invoke `python -m tasks.*`).
Plugin install provides the skill runbooks and slash commands only.

```bash
git clone https://github.com/heyu-ai/yibi-stack && cd yibi-stack && make install
```

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add heyu-ai/yibi-stack

# Install plugin
claude plugin install growth@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `mycelium` skill | 記錄並恢復跨 session 的工作上下文、決策與待辦事項 |
| `learn` skill | 從對話中擷取知識，建立長期可查詢的知識庫 |
| `pr-retrospective` skill | PR 收尾五問回顧（agent 推論草稿、使用者校準），寫入 mycelium retrospectives table；依 Lesson Classifier 路由 lessons 到 `.claude/rules/` 或 CLAUDE.md，再觸發 hookify、writing-skills 等下游 skill |
| `pr-control-log` skill | PR 完成後的 AI 行為審計：從 git log / PR diff / PR body 推論 7 類 entries（autonomous_decision / assumption / spec_deviation 等），使用者 3 輪校準後寫入 mycelium DB，產生 .runtime/control-logs/pr-N.md artifact，並依閾值輸出 CLAUDE.md / hook 補充建議 |
| `claude-md-prune` skill | 審查並精簡 CLAUDE.md：把累積的 gotcha 路由到對應的 `.claude/rules/` 子檔，刪除過期或重複內容，維持 CLAUDE.md 在 Anthropic 建議的 200 行軟上限內 |
| `/pr-retro` command | 觸發 PR 收尾五問回顧，將校準結果寫入 mycelium 並建議下游動作 |

## Use cases

- PR 完成後執行 `/pr-retro`，提取可長期保留的教訓與改善項目
- 用 `pr-control-log` 審計 AI 行為與規格偏離，累積治理依據
- 定期用 `claude-md-prune` 把過時或重複指引整理到正確位置
- 用 `mycelium` 與 `learn` 保存、搜尋及修剪跨 session 知識
