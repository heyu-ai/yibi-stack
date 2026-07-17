# util

Claude Code plugin for everyday utility tools.

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add heyu-ai/yibi-stack

# Install plugin
claude plugin install util@yibi-stack
```

## Prerequisites

`local-port-manager` calls the `portman` CLI, which ships as an installable Python
distribution — **no repository clone and no `make install` required**:

```bash
uv tool install git+https://github.com/heyu-ai/yibi-stack
```

The skill's Step 1 fails loud with this exact command if `portman` is missing, so you can
also just run the skill and follow the error.

`/debug` needs nothing beyond the plugin itself.

## What you get

| Component | Description |
|-----------|-------------|
| `local-port-manager` skill | 本機 port 登記與衝突檢查，避免多服務 port 撞號 |
| `/debug` command | 啟動結構化 debug session，引導逐步縮小問題範圍 |
