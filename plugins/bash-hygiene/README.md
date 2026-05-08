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
claude plugin marketplace add ainization/ainization-skill

# Install plugin
claude plugin install bash-hygiene@ainization-skill
```

## What you get

| Component | Description |
|-----------|-------------|
| AP1 PreToolUse hook | Blocks `python -c` multi-line, `osascript` heredoc, `grep "\|"` BRE, nested `$(outer "$(inner)")`, `$(jq '...')` subshell |
| AP2 PreToolUse hook | Blocks em dash, en dash, emoji, zero-width chars in bash strings |
| SessionStart hook | Injects anti-pattern rules into every session context |
| `bash-anti-patterns` skill | Full methodology guide (invoke via `/bash-hygiene:bash-anti-patterns`) |

## License

MIT
