# dev-cycle

Claude Code plugin for the full development lifecycle: workspace setup, debugging, CI triage,
PR review, merge, and release hygiene.

## Prerequisites

`/newjob`, `/handover`, and `/handover-back` require the yibi-stack repository to be
cloned and `make install` to be run (`local_port_manager` and `tasks.mycelium` invoke
`python -m tasks.*`). Plugin install alone provides the runbooks and slash commands only.

```bash
git clone https://github.com/heyu-ai/yibi-stack && cd yibi-stack && make install
```

## Install

```bash
# Register marketplace (one-time)
claude plugin marketplace add heyu-ai/yibi-stack

# Install plugin
claude plugin install dev-cycle@yibi-stack
```

> **Upgrade note:** `pr-flow@yibi-stack` has been renamed to `dev-cycle@yibi-stack`. Run
> `claude plugin uninstall pr-flow@yibi-stack && claude plugin install dev-cycle@yibi-stack`.

## What you get

| Component | Description |
|-----------|-------------|
| `investigate` skill | 系統化除錯：先根因調查（五階段 + Iron Law）再修，然後交棒給 PR 生命週期。改寫自 garrytan/gstack（MIT），剝除 gstack 產品 plumbing。Scope Lock 階段可選用編輯範圍護欄（`freeze` scope-guard 為獨立 follow-up） |
| `ci-triage` skill | 快速定位 CI 失敗原因的通用診斷漏斗（Lint → Format → Type check → Tests），適用 Python、JavaScript、Go 等技術棧 |
| `pr-review-cycle` skill | 完整 PR 生命週期：PR 建立 → review → fix → CI → merge → archive |
| `pr-cycle-fast` skill | PR 生命週期快速版：Python state machine，1 reviewer，支援 resume |
| `pr-cycle-deep` skill | PR 生命週期深度版：mob review（Codex + Gemini）+ SDD amplifier-verifier |
| `mob-code-review-only` skill | Mob review 別人的 PR（只給建議、不修改）：共用 pr-cycle-deep 引擎，產出彙整建議貼回 PR，不改 code / 不 merge |
| `bump-version` skill | 語意化版本號遞增（semver），更新 CHANGELOG |
| `local-port-manager` skill | 本機 port 登記與衝突檢查，避免多服務 port 撞號 |
| `verify-done` skill | 宣告完成前的端對端驗證：pre-commit、CI checks、Spectra amplifier、worktree 安全性 |
| `issue-triage` skill | GitHub Issue 定期盤點治理（唯讀優先）：逐 issue 研判 close / 更新範圍 / 整併 / label / 優先排序 |
| `/newjob` command | 開始新工作前的 worktree-first 環境準備：偵測環境、建立隔離 worktree、push 安全驗證、複製 gitignored 開發檔案、透過 `local-port-manager` 預防多 worktree port 衝突、驗證環境就緒 |
| `/handover` command | 建立交班摘要，保存進度供下個 session 繼續 |
| `/handover-back` command | 從上次交班恢復工作狀態 |
| `/debug` command | 啟動結構化 debug session，引導逐步縮小問題範圍 |
| `/pr-review-cycle` command | 完整 PR 生命週期（含建立 PR → code review → merge） |
| `/pr-cycle-fast` command | PR 生命週期快速版（含 resume） |
| `/pr-cycle-deep` command | PR 生命週期深度版（mob review + SDD） |
| `/mob-code-review-only` command | Mob review 別人的 PR（只給建議、不修改） |
| `/clean-wt` command | 統一清理本地分支與 worktree（merged / gone / 無價值殘留）；預設只報告，`--apply` 才刪 |
| `/debug-to-pr` command | 從 debug session 結果產生 PR |
