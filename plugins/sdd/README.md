# sdd

Claude Code plugin for Spec-Driven Development: Spectra amplifier methodology, qa-test-design framework, and OpenSpec change-management workflow.

> **This plugin does NOT bundle the spectra CLI. Install Spectra.app separately (see Prerequisites).**
> **v0.2 Upgrade note:** PR review skills (`pr-review-cycle`, `pr-review-cycle-mob`, `pr-review-cycle-codex`) have moved to `pr-flow@yibi-stack`. If upgrading from `yibi-spectra`, run:
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
| `spectra-amplifier` skill | Spec Kit 五層深度規格展開 + OpenSpec/Spectra 變更管理框架方法論 |
| `qa-test-design` skill | 測試設計框架：邊界分析、等價類劃分、決策表，生成結構化 test case |
| SessionStart hook | Detects whether `spectra` CLI is in PATH; injects a nudge when absent (silent when present) |
| `/sdd:setup` command | Diagnose CLI installation status and print setup instructions |
| `references/` | 6 個 openspec 範本：目錄結構說明、proposal/design/tasks/spec-delta 骨架、archive 步驟 snippet |

## openspec 目錄範例

```text
docs/openspec/changes/<feature-name>/
├── proposal.md    (Spec Kit Layer 1-2-4-5)
├── design.md      (Layer 3: data model + API schema)
├── tasks.md       (implementation checklist)
└── specs/
    └── <name>-core.md   (GIVEN/WHEN/THEN delta specs)
```

參見 `references/openspec-layout.md` 取得完整格式說明與 CLI 指令對照。

## Templates (references/)

| 檔案 | 用途 |
|------|------|
| `openspec-layout.md` | 目錄結構指引 + Spectra CLI 指令速查 + Spec Kit 五層對應 |
| `proposal-template.md` | Proposal 空骨架（Layer 1-2-4-5） |
| `design-template.md` | Design 空骨架（Layer 3） |
| `tasks-template.md` | Implementation checklist 空骨架 |
| `spec-delta-template.md` | Delta spec 骨架（GIVEN/WHEN/THEN + [ADDED]/[MODIFIED]/[REMOVED]） |
| `spectra-archive-snippet.md` | PR 收尾 Spectra Archive + Jira Sync 完整步驟 |

## License

MIT
