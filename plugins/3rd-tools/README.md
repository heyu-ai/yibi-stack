# 3rd-tools

Claude Code plugin for integrating third-party AI tools into your workflow.

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add heyu-ai/yibi-stack

# Install plugin
claude plugin install 3rd-tools@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `codex-review` skill | 使用 OpenAI Codex 對當前 branch diff 做 code review 或 challenge 對抗模式找 bug 的 runbook |
| `codex-consult` skill | 使用 OpenAI Codex 閱讀 codebase 回答任意技術問題（第二意見）的 runbook |
| `codex-cli` skill | 委託 OpenAI Codex 實作（`-s workspace-write`）並由 Claude 驗收的 runbook；含委託契約 `contract.md` 與 rule picker |
| `agy-review` skill | 使用 Antigravity CLI（Gemini）對 diff 做輕量 code review 與對抗模式 bug hunt 的 runbook |
| `agy-consult` skill | 使用 Antigravity CLI（Gemini）閱讀 codebase 回答任意技術問題（第二意見）的 runbook |
| `verify-gemini-models` skill | 確認 Gemini 模型列表與 API 可用性 |

## Migration

The unused `detect-ai-slop` skill was removed from yibi-stack. There is no replacement plugin
to install.

The `agy` skill was renamed and split into `agy-review` + `agy-consult` (see the table above).
`make install`/`make uninstall` only walk currently-existing `skills/*/` directories — they do
**not** prune a symlink whose source directory was deleted or renamed. On an existing checkout,
`~/.claude/skills/agy` and `~/.agents/skills/agy` (created by a prior `make install` against the
old `plugins/3rd-tools/skills/agy/`) become dangling after this rename, silently — `git status`
does not surface it. Before re-running `make install`, remove the stale symlinks manually:

```bash
rm -f ~/.claude/skills/agy ~/.agents/skills/agy
```
