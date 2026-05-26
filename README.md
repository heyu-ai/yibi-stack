# yibi-stack

> [English](#english) | [繁體中文](#繁體中文)

---

## English

### What is yibi-stack?

yibi-stack is a Claude Code skill and plugin stack for engineering teams who use Claude as their primary development tool.
It transforms Claude Code from a capable-but-undisciplined assistant into a workflow-aware engineering partner with built-in guardrails.

The stack ships in two layers:

- **Plugins** (`plugins/`) — installable via `claude plugin install`, add hooks and skills that activate automatically in every session
- **Skills** (`skills/`) — SKILL.md runbooks that tell Claude *how* to approach specific tasks (TDD, PR review, spec writing, release workflow)

### Why yibi-stack?

Without guardrails, Claude Code tends to:

- Write bash commands that trigger Claude Code's internal confirmation dialogs (nested quotes, stateful `cd`, inline multi-language)
- Generate specs too shallow to build from
- Lose work context when conversations compress
- Skip test discipline under time pressure

yibi-stack layers three forms of enforcement on top of Claude Code:

1. **Automated hooks** — catch problems before execution, not after
2. **Methodology skills** — runbooks that embed TDD, spec-writing, and review discipline into Claude's workflow
3. **Persistent tooling** — mycelium, scheduler, and port registry that survive across conversations

### Benefits

| Benefit | Mechanism |
|---------|-----------|
| Safer shell execution | `bash-hygiene` plugin intercepts 3 anti-pattern categories (AP1: overcomplex single commands / AP2: unicode in shell strings / AP3: stateful `cd`) via PreToolUse hooks — before they cause silent failures |
| Spec-first development | `sdd` plugin + `spectra-amplifier` skill expands thin requirements into 5-layer specs (Context → Behavior → Data → Constraints → Acceptance Criteria), compatible with OpenSpec change management |
| Multi-model PR review | `pr-review-cycle-mob` orchestrates Claude + Codex + Gemini in parallel independent review → cross-model debate → aggregate, catching issues no single model would flag |
| Persistent work memory | `mycelium` skill auto-handovers before context compression and restores on next session start — no more losing track of multi-day work |
| Release discipline | `bump-version`, `protect-push`, and `ci-triage` skills codify release workflow so Claude doesn't push to main without explicit intent |
| Test methodology | `tdd-kentbeck` (Kent Beck Red→Green→Refactor) and `qa-test-design` (6 test design techniques) embed testing discipline into daily work |

### Architecture

```text
plugins/          Claude Code plugin packs (installable via claude plugin install)
  bash-hygiene/   PreToolUse hook enforcement, shell hygiene rules, anti-pattern guide
  sdd/            Spec-Driven Development: Spectra + OpenSpec methodology, qa-test-design
  growth/         Session continuity: mycelium, learn, handover/newjob commands
  pr-flow/        PR workflow: review cycles, retrospective, bump-version, pr commands
  3rd-tools/      Third-party AI: Codex, Gemini model verification, AI slop detection
  tdd/            Test-Driven Development: Kent Beck TDD, Flutter TDD, CI triage
  util/           Utility: local port manager, debug command
  harness/        Harness readiness evaluation (README only, no package.json -- skill installed via make install)

skills/           Agent execution layer -- SKILL.md runbooks (installed via make install)
  <skill-name>/   Each skill is a flat directory with a SKILL.md runbook (or a symlink)
                  scope:global  -- works in any repo (methodology, cross-project tools)
                  scope:project -- requires this repo's Python tasks

tasks/            Python implementation (CLI, service, models, SQLite DB)
commands/         Claude Code slash commands (symlinked to ~/.claude/commands/)
scripts/          CI and lint tooling
```

### Plugins vs Skills — what's the difference?

**Plugins** (`plugins/bash-hygiene`, `plugins/sdd`, `plugins/growth`, `plugins/pr-flow`, `plugins/3rd-tools`, `plugins/tdd`, `plugins/util`)
are proper Claude Code plugins with `package.json` manifests. They install hooks, rules, and bundled skills. Installable via `claude plugin install` without cloning.
`plugins/harness` is a documentation placeholder only (no `package.json`) — its `harness-eval` skill installs via `make install-one SKILL=harness-eval` (see Plugins table).

**Skills** (`skills/*/SKILL.md`) are runbook files — not plugins. They're installed as symlinks into `~/.claude/skills/` via `make install`.
They tell Claude *how* to approach a workflow; no hooks are involved. Skills are **not** individually installable via `claude plugin install`.

### Install

**Plugin-only** (lightweight, no clone needed):

```bash
claude plugin marketplace add howie/yibi-stack
claude plugin install bash-hygiene@yibi-stack
claude plugin install sdd@yibi-stack
claude plugin install growth@yibi-stack
claude plugin install pr-flow@yibi-stack
claude plugin install tdd@yibi-stack
```

Note: `harness-eval` is not installable via `claude plugin install` — clone the repo and run `make install-one SKILL=harness-eval` (or `make install-all` for a full setup).

**Full install** (plugins + all skills + hooks + scheduler):

```bash
# 1. Install plugins (pre-execution hooks + rules)
claude plugin marketplace add howie/yibi-stack
claude plugin install bash-hygiene@yibi-stack sdd@yibi-stack growth@yibi-stack pr-flow@yibi-stack tdd@yibi-stack

# 2. Clone and install skills + hooks + scheduler
git clone https://github.com/howie/yibi-stack
cd yibi-stack
make install-all
```

Verify install status (shows only this repo's skills, excludes gstack/external):

```bash
make status-own
```

### Key Skills

| Skill | What it does |
|-------|-------------|
| `spectra-amplifier` | 5-layer spec expansion via `sdd` plugin |
| `pr-review-cycle` | Full PR lifecycle: create -> parallel review -> fix -> CI -> merge |
| `pr-review-cycle-mob` | Multi-model mob review (Claude + Codex + Gemini) |
| `bash-anti-patterns` | AP1/AP2/AP3 detection guide + shell quoting hygiene reference |
| `tdd-kentbeck` | Kent Beck TDD + Tidy First methodology |
| `qa-test-design` | 6 test design techniques (equivalence, boundary, decision table...) |
| `mycelium` | Cross-session work handover and insight collection |
| `bump-version` | Version bump (Flutter/Python/Node/Go) + CHANGELOG + git tag |
| `protect-push` | Hook to prevent accidental pushes from worktree branches to main |
| `ci-triage` | CI failure triage funnel (Lint -> Type -> Security -> Tests) |
| `learn` | Browse, search, prune, and export lessons learned |
| `pr-retrospective` | 5-question PR retro, routes lessons to `.claude/rules/` or CLAUDE.md |
| `harness-eval` | 8-dimension harness readiness score (0-100) with PASS/WARN/FAIL checklist and priority TODO |

See [`skills/README.md`](skills/README.md) for the full index.

### Plugins

| Plugin | Install | Description |
|--------|---------|-------------|
| `bash-hygiene` | `claude plugin install bash-hygiene@yibi-stack` | Pre-execution bash anti-pattern detection with auto-fix guidance |
| `sdd` | `claude plugin install sdd@yibi-stack` | Spectra + OpenSpec spec-amplifier methodology + qa-test-design |
| `growth` | `claude plugin install growth@yibi-stack` | Session continuity: mycelium, learn, handover/newjob commands |
| `pr-flow` | `claude plugin install pr-flow@yibi-stack` | Full PR workflow: 6 skills + 5 slash commands |
| `3rd-tools` | `claude plugin install 3rd-tools@yibi-stack` | Codex, Gemini model verification, AI slop detection |
| `tdd` | `claude plugin install tdd@yibi-stack` | Kent Beck TDD, Flutter TDD, CI triage |
| `util` | `claude plugin install util@yibi-stack` | Local port manager + debug command |
| `harness` | `make install-one SKILL=harness-eval` | Harness readiness evaluation |

---

## 繁體中文

### yibi-stack 是什麼？

yibi-stack 是一套專為以 Claude Code 作為主力開發工具的工程師設計的 skill 與 plugin 集。它讓 Claude Code 從一個能力強但缺乏紀律的助手，升級為有工作流程意識、有自我約束力的工程夥伴。

這個 stack 分兩層：

- **Plugins**（`plugins/`）— 透過 `claude plugin install` 安裝，每次 session 自動啟用 hook 與 skill
- **Skills**（`skills/`）— SKILL.md runbook，告訴 Claude 如何處理特定任務（TDD、PR review、規格撰寫、發版流程）

### 為什麼需要 yibi-stack？

沒有護欄的 Claude Code 容易出現這些問題：

- 寫出觸發 Claude Code 確認框的 bash 指令（巢狀引號、stateful `cd`、內嵌多語言）
- 產生粒度太粗、無法直接實作的規格
- 對話壓縮後遺失工作脈絡
- 在時間壓力下跳過測試紀律

yibi-stack 在 Claude Code 之上疊加三層約束：

1. **自動化 hook** — 在執行前攔截問題，而不是事後除錯
2. **方法論 skill** — 把 TDD、規格撰寫、PR 審閱的紀律嵌入 Claude 的工作流程
3. **持久化工具** — 跨對話的 session 記憶、定期排程器、port 登記表

### 主要好處

| 好處 | 機制 |
|------|------|
| 更安全的 shell 執行 | `bash-hygiene` plugin 透過 PreToolUse hook，在執行前攔截三類反模式（AP1 過複雜單行 / AP2 bash 字串 Unicode / AP3 stateful cd），避免靜默失敗 |
| 規格先行的開發 | `sdd` plugin + `spectra-amplifier` skill 把薄需求展開為五層規格（情境→行為→資料→約束→驗收條件），兼容 OpenSpec 變更管理框架 |
| 多模型 PR 審閱 | `pr-review-cycle-mob` 讓 Claude + Codex + Gemini 並行獨立審閱再交叉辯論，捕捉單一模型漏掉的問題 |
| 持久化工作記憶 | `mycelium` skill 在對話壓縮前自動交班，下次 session 開啟時自動恢復工作上下文，多日開發不斷線 |
| 發版紀律 | `bump-version` + `protect-push` + `ci-triage` 讓 Claude 不會在沒有明確意圖的情況下推上 main |
| 測試方法論 | `tdd-kentbeck`（Kent Beck Red→Green→Refactor）和 `qa-test-design`（六大測試設計技術）把測試紀律內建到日常工作中 |

### 架構

```text
plugins/          Claude Code plugin packs（可透過 claude plugin install 安裝）
  bash-hygiene/   PreToolUse hook 防線、shell 衛生規則、反模式修法指南
  sdd/            Spec-Driven Development：Spectra + OpenSpec 方法論、qa-test-design
  growth/         跨 session 連續性：mycelium、learn、handover/newjob commands
  pr-flow/        PR 全流程：review cycles、retrospective、bump-version、PR commands
  3rd-tools/      第三方 AI：Codex、Gemini 模型驗證、AI slop 偵測
  tdd/            測試驅動開發：Kent Beck TDD、Flutter TDD、CI 診斷
  util/           工具：local port manager、debug command
  harness/        Harness 就緒度評量（純 README，無 package.json，skill 透過 make install 安裝）

skills/           Agent 執行介面層（SKILL.md runbook，透過 make install 安裝）
  <skill-name>/   每個 skill 是一個目錄（或指向 plugins/ 的 symlink）
                  scope:global  -- 跨專案可用（方法論、通用工具）
                  scope:project -- 本 repo 限定（需要 tasks/ Python 實作）

tasks/            Python 實作（CLI、service、models、SQLite DB）
commands/         Claude Code slash commands（symlink 到 ~/.claude/commands/）
scripts/          CI 與 lint 工具腳本
```

### Plugin 與 Skill 的差別？

**Plugin**（`plugins/bash-hygiene`、`plugins/sdd`、`plugins/growth`、`plugins/pr-flow`、`plugins/3rd-tools`、`plugins/tdd`、`plugins/util`）
是有 `package.json` manifest 的正式 Claude Code plugin，會安裝 hook、rules 和隨附 skill，不需 clone 即可用 `claude plugin install` 安裝。
`plugins/harness` 是純文件容器（無 `package.json`）——其 `harness-eval` skill 透過 `make install-one SKILL=harness-eval` 安裝（見下方 Plugins 表格）。

**Skill**（`skills/*/SKILL.md`）是 runbook 檔案，不是 plugin。透過 `make install` 以 symlink 安裝到 `~/.claude/skills/`，告訴 Claude 如何執行特定工作流程。**Skills 無法透過 `claude plugin install` 個別安裝。**

### 安裝

**只安裝 Plugin**（輕量，不需 clone）：

```bash
claude plugin marketplace add howie/yibi-stack
claude plugin install bash-hygiene@yibi-stack
claude plugin install sdd@yibi-stack
claude plugin install growth@yibi-stack
claude plugin install pr-flow@yibi-stack
claude plugin install tdd@yibi-stack
```

注意：`harness-eval` 無法透過 `claude plugin install` 安裝——需 clone 本 repo 後執行 `make install-one SKILL=harness-eval`（或 `make install-all` 一次裝齊）。

**完整安裝**（plugin + 所有 skill + hook + scheduler）：

```bash
# 1. 安裝 plugin（pre-execution hook + 規則）
claude plugin marketplace add howie/yibi-stack
claude plugin install bash-hygiene@yibi-stack sdd@yibi-stack growth@yibi-stack pr-flow@yibi-stack tdd@yibi-stack

# 2. Clone 並安裝 skill + hook + scheduler
git clone https://github.com/howie/yibi-stack
cd yibi-stack
make install-all
```

確認安裝狀態（只顯示本 repo 的 skill，排除 gstack / 外部安裝）：

```bash
make status-own
```

### 主要 Skills

| Skill | 功能 |
|-------|------|
| `spectra-amplifier` | 五層規格展開（透過 `sdd` plugin） |
| `pr-review-cycle` | 完整 PR 生命週期：建立 → 並行 review → 修正 → CI → merge |
| `pr-review-cycle-mob` | 多模型群審（Claude + Codex + Gemini） |
| `bash-anti-patterns` | AP1/AP2/AP3 偵測指南 + shell 引號衛生參考 |
| `tdd-kentbeck` | Kent Beck TDD + Tidy First 方法論 |
| `qa-test-design` | 六大測試設計技術（等價類別、邊界值、決策表……） |
| `mycelium` | 跨對話工作交班與洞察收集 |
| `bump-version` | 版本 bump（Flutter/Python/Node/Go）+ CHANGELOG + git tag |
| `protect-push` | 防止 worktree branch 意外推上 main 的 hook |
| `ci-triage` | CI 失敗快速診斷漏斗（Lint → Type → Security → Tests） |
| `learn` | 瀏覽、搜尋、修剪、匯出教訓記錄 |
| `pr-retrospective` | PR 收尾五問回顧，路由 lesson 到 `.claude/rules/` 或 CLAUDE.md |
| `harness-eval` | 8 維度 harness 就緒度評分（0-100），附 PASS/WARN/FAIL 清單與優先改善 TODO |

完整索引見 [`skills/README.md`](skills/README.md)。

### Plugins

| Plugin | 安裝指令 | 說明 |
|--------|---------|------|
| `bash-hygiene` | `claude plugin install bash-hygiene@yibi-stack` | 執行前 bash 反模式偵測，附自動修法指引 |
| `sdd` | `claude plugin install sdd@yibi-stack` | Spectra + OpenSpec 規格展開 + qa-test-design 測試設計 |
| `growth` | `claude plugin install growth@yibi-stack` | 跨 session 記憶：mycelium、learn、handover/newjob |
| `pr-flow` | `claude plugin install pr-flow@yibi-stack` | 完整 PR 流程：6 個 skill + 5 個 slash command |
| `3rd-tools` | `claude plugin install 3rd-tools@yibi-stack` | Codex、Gemini 模型驗證、AI slop 偵測 |
| `tdd` | `claude plugin install tdd@yibi-stack` | Kent Beck TDD、Flutter TDD、CI 診斷 |
| `util` | `claude plugin install util@yibi-stack` | 本機 port 管理 + debug command |
| `harness` | `make install-one SKILL=harness-eval` | Harness 就緒度評量 |

---

## License

MIT
