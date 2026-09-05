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
| `agy-review` skill | 使用 Antigravity CLI（agy）對 diff 做輕量 code review 與對抗模式 bug hunt 的 runbook。預設模型 `gemini-3.8-flash-high` |
| `agy-consult` skill | 使用 Antigravity CLI（agy）閱讀 codebase 回答任意技術問題（第二意見）的 runbook。預設模型 `gemini-3.8-flash-high`；把它當成跨廠商聲音前仍先讀腳本印出的 `[INFO] agy 模型`（可被 `AGY_MODEL` 覆寫回 Claude） |

| `verify-gemini-models` skill | 確認 Gemini 模型列表與 API 可用性 |

> `agy-review`、`agy-consult` 預設使用 `gemini-3.8-flash-high`；`/pr-cycle-deep`
> 的所有 agy stages 固定使用同一模型（2026-09-03 以 agy 1.1.25 在台灣實測可用）。
> `/pr-cycle-deep` 使用完整 display name `Gemini 3.8 Flash (High)`，避免 auto-select
> 選到其他模型或 Claude 而破壞預期的模型與跨廠商 review 獨立性。

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
