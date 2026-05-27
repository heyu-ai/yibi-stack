# sdd

Claude Code plugin for Spec-Driven Development: Spectra amplifier methodology, qa-test-design framework, and OpenSpec change-management workflow.

> **This plugin does NOT bundle the spectra CLI. Install Spectra.app separately (see Prerequisites).**
> **v0.2 Upgrade note:** PR review skills (`pr-review-cycle`, `pr-review-cycle-mob`) have moved to `pr-flow@yibi-stack`. If upgrading from `yibi-spectra`, run:
> `claude plugin uninstall yibi-spectra@yibi-stack && claude plugin install sdd@yibi-stack pr-flow@yibi-stack`

## Prerequisites

**macOS (recommended):**

```bash
brew install --cask spectra-app
```

Upstream: <https://github.com/kaochenlong/spectra-app> (open source, active — v2.3.x, monthly releases)

**Linux / Windows or no-CLI mode:**

Amplifier methodology and all openspec templates work standalone without the CLI.
`archive`, `validate`, `analyze` sub-flows require the macOS CLI (degraded mode on other platforms).

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add howie/yibi-stack

# Install plugin
claude plugin install sdd@yibi-stack
```

## What you get

| Component | Description |
|-----------|-------------|
| `spectra-amplifier` skill | Wave D Plugin Edition：Step 0-5 規格展開，含 BDD Gherkin scenarios（多 capability 平行展開）、qa-test-design dispatch、docstring trace |
| `event-storming` skill | 領域發現前置 skill；amplifier Step 0 的 handoff 來源（draft：接口 + handoff artifact）|
| `qa-test-design` skill | 測試設計框架（人類入口）：六大技術方法論，生成結構化 test case；方法論詳見 `methodology.md` |
| `qa-test-designer` agent | Step 2a 自動 subagent：由 spectra-amplifier 平行 dispatch，model: opus，pure-transformation TC 生成 |
| `gherkin-scenario-writer` agent | Step 1c 平行 subagent：為單一 capability 撰寫 Gherkin scenarios（RFC 2119 GIVEN/WHEN/THEN）；多 capability 時由 spectra-amplifier 平行 dispatch |
| `scripts/check_spec_coverage.py` | BDD Spec-Test Traceability Scanner（ADR-0008）；`--specs-dir`/`--tests-dir` 參數化 |
| SessionStart hook | Detects whether `spectra` CLI is in PATH; injects a nudge when absent (silent when present) |
| `/sdd:setup` command | Diagnose CLI installation status and print setup instructions |
| `references/` | 7 個 openspec 範本（新增 testplan-template.md） |

## openspec 目錄範例

```text
docs/openspec/changes/<feature-name>/
├── proposal.md    (Step 1b US+AC + Step 4 假設 + Step 5 DoD + Traceability Matrix)
├── specs/
│   └── <name>.md  (Step 1c Gherkin scenarios，#### Scenario: <slug> -- <title>)
├── testplan.md    (Step 2 TC 表格 + Coverage Analysis, NEW in v1.3)
├── design.md      (Step 3 data model + API schema, 按需)
└── tasks.md       (Phase 結構任務拆解, per-US pytest -k 驗收)
```

參見 `references/openspec-layout.md` 取得完整格式說明與 CLI 指令對照。

## Templates (references/)

| 檔案 | 用途 |
|------|------|
| `openspec-layout.md` | 目錄結構指引 + Spectra CLI 指令速查 + amplifier Step 0-5 對應 |
| `proposal-template.md` | Proposal 空骨架（Step 1b US+AC + Step 4 + Step 5） |
| `design-template.md` | Design 空骨架（Step 3） |
| `tasks-template.md` | Implementation checklist 空骨架（含 pytest -k 驗收）|
| `spec-delta-template.md` | Delta spec 骨架（GIVEN/WHEN/THEN + [ADDED]/[MODIFIED]/[REMOVED]） |
| `testplan-template.md` | testplan.md 空骨架（Step 2 TC 表格 + Coverage Analysis, **NEW v1.3**）|
| `spectra-archive-snippet.md` | PR 收尾 Spectra Archive + Jira Sync 完整步驟 |

## License

MIT
