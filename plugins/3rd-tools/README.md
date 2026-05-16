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
| `verify-gemini-models` skill | 確認 Gemini 模型列表與 API 可用性 |
| `detect-ai-slop` skill | 偵測 AI 生成文字中的品質問題（過度通用、陳腔濫調、無意義填充） |
