# util

Claude Code plugin for everyday utility tools.

## Prerequisites

The `local-port-manager` skill requires the yibi-stack repository to be cloned and `make install` to be run for task execution (`python -m tasks.local_port_manager`). Plugin install provides the skill runbook and debug command only.

```bash
git clone https://github.com/howie/yibi-stack && cd yibi-stack && make install
```

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install util@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `local-port-manager` skill | 本機 port 登記與衝突檢查，避免多服務 port 撞號 |
| `/debug` command | 啟動結構化 debug session，引導逐步縮小問題範圍 |
