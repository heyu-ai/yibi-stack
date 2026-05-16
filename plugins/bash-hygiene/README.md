# bash-hygiene

Claude Code plugin for bash anti-pattern detection and enforcement.

## What it does

Automatically detects and blocks common bash anti-patterns that cause Claude Code's shell parser to fail:

- **AP1**: Overly complex single commands (inline `python -c` multi-line, `osascript` heredoc, nested subshells, double-quoted BRE)
- **AP2**: Unicode characters in bash strings (em dash, en dash, emoji, zero-width chars)
- **Rules injection**: Shell quoting hygiene, stateful `cd` avoidance, irreversible operation boundaries

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install bash-hygiene@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| AP1 PreToolUse hook | Blocks `python -c` multi-line, `osascript` heredoc, `grep "\|"` BRE, nested `$(outer "$(inner)")`, `$(jq '...')` subshell |
| AP2 PreToolUse hook | Blocks em dash, en dash, emoji, zero-width chars in bash strings |
| Smart-fix PreToolUse hook | Detects Rule 2 `"$(cmd)"` standalone token and shows corrected command inline |
| SessionStart hook | Injects anti-pattern rules into every session context |
| `bash-anti-patterns` skill | Full methodology guide (invoke via `/bash-hygiene:bash-anti-patterns`) |

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
