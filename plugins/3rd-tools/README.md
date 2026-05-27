# 3rd-tools

Claude Code plugin for integrating third-party AI tools into your workflow.

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install 3rd-tools@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `codex` skill | 使用 OpenAI Codex 進行程式碼 review、說明與重構的 runbook |
| `agy` skill | 使用 Antigravity CLI（Gemini）進行輕量 code review 與對抗模式 bug hunt |
| `verify-gemini-models` skill | 確認 Gemini 模型列表與 API 可用性 |
