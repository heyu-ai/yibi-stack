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
| `codex-review` skill | 使用 OpenAI Codex 對當前 branch diff 做 code review 或 challenge 對抗模式找 bug 的 runbook |
| `codex-consult` skill | 使用 OpenAI Codex 閱讀 codebase 回答任意技術問題（第二意見）的 runbook |
| `agy` skill | 使用 Antigravity CLI（Gemini）進行輕量 code review 與對抗模式 bug hunt |
| `verify-gemini-models` skill | 確認 Gemini 模型列表與 API 可用性 |

## Migration

`detect-ai-slop` skill was moved to the `writing` plugin. To keep using it:

```bash
claude plugin install writing@yibi-stack
```
