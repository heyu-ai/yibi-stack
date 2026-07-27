# methodology

Portable, project-agnostic methodology skills for Claude Code agents.

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install methodology@yibi-stack
```

> **Upgrade note:** `tdd-kentbeck` and `flutter-tdd` moved from `tdd@yibi-stack` to
> `methodology@yibi-stack`; `event-storming`, `problem-frames`, and `qa-test-design` moved
> from `sdd@yibi-stack` to `methodology@yibi-stack`. `ci-triage` moved from `tdd@yibi-stack`
> to `dev-cycle@yibi-stack` (it is operational, not methodology, and stayed out of this pack).
> If you had `tdd@yibi-stack` installed, run
> `claude plugin uninstall tdd@yibi-stack && claude plugin install methodology@yibi-stack dev-cycle@yibi-stack`
> (note **two** install targets — `tdd` split across both). `sdd@yibi-stack` users who relied
> on `event-storming`/`problem-frames`/`qa-test-design` should additionally run
> `claude plugin install methodology@yibi-stack`.

## What you get

| Component | Description |
|-----------|-------------|
| `tdd-kentbeck` skill | 以 Kent Beck 的 Test-Driven Development (TDD) 與 Tidy First 方法論驅動軟體開發 |
| `flutter-tdd` skill | Flutter 行動應用的測試驅動開發（TDD）專家指引 |
| `event-storming` skill | 領域發現前置 skill，在開始寫 spec 之前使用 |
| `problem-frames` skill | Michael Jackson Problem Frames 方法論：在寫 spec 之前，把問題拆成 R（需求）/ S（規格）/ W（領域假設），並證明 S ∧ W ⟹ R，藉此把領域假設前置顯式化 |
| `qa-test-design` skill | Senior QA test design techniques using structured methods to produce high-quality test cases；涵蓋 Equivalence Partitioning、Boundary Value Analysis、Decision Table、State Transition、Pairwise / Combinatorial Testing 與 Risk-Based Testing |

## Use cases

- Use Kent Beck TDD or Flutter-specific TDD to drive implementation through disciplined test-first cycles.
- Discover domain events and system boundaries before writing a specification.
- Separate requirements, specifications, and domain assumptions with Jackson Problem Frames.
- Design and review test coverage with six structured QA techniques.

## License

MIT
