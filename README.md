# yibi-stack

Agentic skill stack for Claude Code — bash hygiene, Spectra/OpenSpec methodology, PR review workflows, TDD, and productivity tools.

## Install

```bash
claude plugin marketplace add howie/yibi-stack
claude plugin install bash-hygiene@yibi-stack
claude plugin install spectra@yibi-stack
```

## Skills

See [`skills/README.md`](skills/README.md) for the full index.

Key skills:
- **spectra-amplifier** — Spec Kit 5-layer expansion (via `spectra` plugin)
- **pr-review-cycle** / **pr-review-cycle-mob** — PR review with optional multi-model mob (Claude + Codex + Gemini)
- **bash-anti-patterns** — AP1/AP2/AP3 detection and fix guide
- **tdd-kentbeck** / **qa-test-design** — TDD and test design methodology
- **session-memory** / **scheduler** — persistent context and scheduled jobs
- **local-port-manager** — local port registry
- **bump-version** / **protect-push** / **ci-triage** — release workflow tools

## Plugins

| Plugin | Install | Description |
|--------|---------|-------------|
| `bash-hygiene` | `claude plugin install bash-hygiene@yibi-stack` | Pre-commit bash anti-pattern detection |
| `spectra` | `claude plugin install spectra@yibi-stack` | Spectra + OpenSpec spec-amplifier methodology |

## License

MIT
