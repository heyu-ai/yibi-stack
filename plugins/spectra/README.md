# spectra

Claude Code plugin for Spectra + OpenSpec change-management methodology and workflow.

> **This plugin does NOT bundle the spectra CLI. Install Spectra.app separately (see Prerequisites).**

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
claude plugin marketplace add howie/ainization-skill

# Install plugin
claude plugin install spectra@ainization-skill
```

## What you get

| Component | Description |
|-----------|-------------|
| `spectra-amplifier` skill | Spec Kit 五層深度規格展開 + OpenSpec/Spectra 變更管理框架方法論。呼叫方式：`/spectra:spectra-amplifier` |
| `pr-review-cycle` skill | 完整 PR 生命週期：PR 建立 → parallel review → fix → CI → merge → spectra archive + Jira sync |
| `pr-review-cycle-mob` skill | Mob review：多家 frontier model（Codex / Gemini / open-weights）並行 R1 + R2 交叉 debate，適用中大型 PR |
| `pr-review-cycle-codex` skill | [DEPRECATED] codex-only review，改用 pr-review-cycle 或 pr-review-cycle-mob |
| SessionStart hook | Detects whether `spectra` CLI is in PATH; injects a nudge when absent (silent when present) |
| `/spectra:setup` command | Diagnose CLI installation status and print setup instructions |
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

## Skill invocation

Skills installed by this plugin are namespaced under `spectra:`:

```text
/spectra:spectra-amplifier      Spec Kit 五層展開方法論
/spectra:pr-review-cycle        完整 PR 生命週期
/spectra:pr-review-cycle-mob    Mob review（多 model 群審）
```

## Command invocation

```text
/spectra:setup                  CLI 診斷 + 安裝引導
```

## License

MIT
