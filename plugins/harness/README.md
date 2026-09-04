# harness

Claude Code plugin for harness readiness evaluation, bash anti-pattern enforcement, hook audit
logging, worktree push protection, and fleet usage guarding.

## Prerequisites

`harness-eval` and `bash-hygiene-audit` require the yibi-stack repository to be cloned and
`make install` to be run because they invoke `python -m tasks.*`.
Plugin install provides the skill runbooks, slash command, and enforcement hooks.

```bash
git clone https://github.com/heyu-ai/yibi-stack && cd yibi-stack && make install
```

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add heyu-ai/yibi-stack

# Install plugin
claude plugin install harness@yibi-stack
```

> **Upgrade note:** `bash-hygiene@yibi-stack` has been merged into `harness@yibi-stack`
> (including all hooks). Run
> `claude plugin uninstall bash-hygiene@yibi-stack && claude plugin install harness@yibi-stack`.
> **After installing, verify the hooks are actually firing**: run a command that deliberately
> violates AP2 (a bash string containing an em dash), and confirm it gets blocked by
> `bash-ap2-check.py`. **Not blocked means the hooks did not take effect** — do not treat
> install as successful until you have run this check.

## What you get

| Component | Description |
|-----------|-------------|
| `harness-eval` skill | 11 維度 harness 就緒度評量；PASS/WARN/FAIL 健康清單與優先改善 TODO |
| `harness-eval-focus` skill | 針對 D1–D11 單一維度做深度稽核並提供具體修法 |
| `bash-hygiene-audit` skill | 管理 hook audit log：啟用／停用記錄、查看攔截事件、統計違規比例與熱點 pattern |
| `bash-anti-patterns` skill | Full methodology guide for AP1/AP2/AP3 detection and shell quoting hygiene |
| `protect-push` skill | Git pre-push hook installer: blocks direct push to main/master from worktree branches |
| `plugin-migration-check` skill | Detects installed yibi-stack packs that were renamed/merged/split/removed and prints the exact `claude plugin uninstall`/`install` commands to fix them |
| `plugin-cache-prune` skill | Scans `~/.claude/plugins/cache/` across all marketplaces for stale plugin version directories no longer referenced by `installed_plugins.json`, and removes them on request |
| `fleet-usage-guard` skill | Estimates recent fleet-wide transcript cost in USD/hour, deduplicates repeated request rows, and broadcasts a reason-specific stop when the user-owned threshold is exceeded |
| AP1 PreToolUse hook | Blocks `python -c` multi-line, `osascript` heredoc, `grep "\|"` BRE, nested `$(outer "$(inner)")`, `$(jq '...')` subshell |
| AP2 PreToolUse hook | Blocks em dash, en dash, emoji, zero-width chars in bash strings |
| Smart-fix PreToolUse hook | Detects Rule 2 `"$(cmd)"` standalone token and shows corrected command inline |
| SessionStart hook | Injects anti-pattern rules into every session context |

## Use cases

- Run `harness-eval` for an 11-dimension readiness assessment, then use
  `harness-eval-focus` to investigate a weak dimension.
- Use the AP1/AP2 and smart-fix hooks to block fragile shell commands before execution.
- Inspect hook behavior and recurring violations with `bash-hygiene-audit`.
- Install `protect-push` to prevent worktree branches from pushing directly to main/master.
- Consult `bash-anti-patterns` for shell-safe command construction and remediation guidance.
- Run `plugin-migration-check` after a marketplace update if a skill you used to have
  seems to have disappeared, or right after any yibi-stack pack taxonomy refactor.
- Run `plugin-cache-prune` periodically to reclaim disk space from stale plugin version
  directories that accumulate under `~/.claude/plugins/cache/` every time a marketplace
  plugin is updated.
- Run `fleet-usage-guard` from a monitoring session to stop active peers when either the
  transcript-derived USD/hour rate or account quota reaches the configured boundary.

## Known Limitations

### Smart-fix hook: inner parentheses not supported

`_RULE2_STANDALONE` uses `[^()]+` — patterns with inner `()` like
`"$(python3 -c 'print(1)')"` are not detected. Requires shell AST parsing to handle.

### Output filter detection intentionally removed

`| tail -N` / `| head -N` detection was prototyped but removed: regex cannot distinguish
semantic data filters (`git branch | grep -v main`) from safety bounds on streaming
pipelines (`kubectl logs -f | head -20`). Removing a safety bound causes hangs.
Re-adding requires proper shell AST semantics, not regex.

## License

MIT
