# pr_orchestrator — Developer Reference

## Module Purpose

PR 生命週期 Orchestrator 的 Python 實作層。管理可中斷/可 resume 的 state machine，
封裝 gh CLI 呼叫、CI log 解析、fixer 執行、spawn-manifest 生成。

## Entry Point

```bash
uv run python -m tasks.pr_orchestrator <command> [options]
```

## Commands

| Command | 說明 |
|---------|------|
| `detect [--pr N] [--branch B]` | 偵測 PR，建立初始 state file |
| `transition --pr N --to STATE [--reason R]` | 手動觸發 state transition |
| `status [--pr N]` | 顯示 state JSON |
| `resume [--pr N]` | 顯示 resume 指引與 blockers |
| `log-view [--pr N]` | 顯示 transition JSONL log |
| `gc --pr N [--dry-run]` | 清理已完成 PR 的 runtime 暫存 |

## State File Location

- Active: `.runtime/pr_orchestrator/<pr>.json`
- Archive: `~/.claude/pr_orchestrator/<repo>/<pr>.json`（CLEANED 後搬移）

## Fixer Extension

在 `tasks/pr_orchestrator/fixers/` 新增 fixer：
1. 繼承 `BaseFixer`，設定 `name`，實作 `can_fix(log_text)` 和 `run(repo_root, pr_files)`
2. 在 `registry.py` 的 `_FIXERS` list 中加入實例

## Test IDs

- State machine: `PROR-DT-NNN`
- Service integration: `PROR-ST-NNN`
- Edge cases: `PROR-EG-NNN`

## Agent Interface

見 `skills/pr-cycle/SKILL.md`。
