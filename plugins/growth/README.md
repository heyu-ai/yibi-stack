# growth

Claude Code plugin for session continuity and knowledge retention across conversations.

## Prerequisites

These skills require the yibi-stack repository to be cloned and `make install` to be run for task execution (`session-memory` and `learn` invoke `python -m tasks.*`; the `/handover`, `/handover-back`, and `/newjob` commands do the same). Plugin install provides the skill runbooks and slash commands only.

```bash
git clone https://github.com/howie/yibi-stack && cd yibi-stack && make install
```

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install growth@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `session-memory` skill | 記錄並恢復跨 session 的工作上下文、決策與待辦事項 |
| `learn` skill | 從對話中擷取知識，建立長期可查詢的知識庫 |
| `/handover` command | 建立交班摘要，保存進度供下個 session 繼續 |
| `/handover-back` command | 從上次交班恢復工作狀態 |
| `/newjob` command | 啟動新工作 session，初始化 session-memory |

## Use cases

- 長對話即將 compact 前執行 `/handover` 保存進度
- 新 session 開始時執行 `/handover-back` 快速恢復上次工作
- 每次工作結束後用 `session-memory` 更新知識庫
