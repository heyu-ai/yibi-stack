# Architecture Map

本檔案是給 agent `@-mention` 使用的 codebase 地圖。高層次設計說明見 `CLAUDE.md`；本檔專注在**具體檔案路徑**與模組入口。

```text
yibi-stack/
│
├── skills/                          → Agent 執行介面（SKILL.md runbook）
│   ├── README.md                    → 全 skill 索引表（可執行 / 知識型 / 本 repo 限定）
│   ├── _template/SKILL.md.tpl       → 新 skill 標準格式參考
│   └── <skill-name>/SKILL.md        → 各 skill 的 agent runbook
│
├── tasks/                           → Python 實作層
│   ├── _paths.py                    → 共用路徑常數（PROJECT_ROOT, RUNTIME_DIR）
│   ├── __init__.py
│   ├── bash_hygiene_audit/          → Bash 反模式掃描器
│   │   ├── __main__.py
│   │   └── cli.py                   → uv run python -m tasks.bash_hygiene_audit
│   ├── harness_eval/                → Claude Code harness readiness scanner（D1-D10）
│   │   ├── __main__.py
│   │   └── cli.py                   → uv run python -m tasks.harness_eval scan --path .
│   ├── local_port_manager/          → 跨專案 port 登記（~/.agents/ports.json）
│   │   ├── __main__.py
│   │   └── cli.py                   → uv run python -m tasks.local_port_manager
│   ├── scheduler/                   → 排程器（LaunchAgent 每 60 秒 tick）
│   │   ├── __main__.py
│   │   ├── cli.py                   → uv run python -m tasks.scheduler tick
│   │   └── prompts/                 → Claude skill 排程的 prompt 檔
│   └── mycelium/              → 交班記錄讀寫
│       ├── __main__.py
│       └── cli.py                   → uv run python -m tasks.mycelium
│
├── plugins/                         → Claude Code plugin packs（可透過 claude plugin install 安裝）
│   ├── bash-hygiene/                → Bash 衛生工具（AP1/AP2 lint + protect-push hook）
│   ├── growth/                      → 成長工具（mycelium、scheduler skills）
│   ├── pr-flow/                     → PR 流程工具（review cycle、mob review）
│   ├── sdd/                         → Subagent Driven Development 方法論
│   ├── tdd/                         → TDD 方法論（Kent Beck style）
│   ├── util/                        → 通用工具（port manager、handover）
│   ├── 3rd-tools/                   → 第三方工具整合（Gemini、Codex）
│   ├── writing/                     → 寫作品質工具（detect-ai-slop）
│   └── harness/                     → Harness eval（無 package.json，用 make install-one SKILL=harness-eval）
│
├── commands/                        → Claude Code slash commands（symlink 到 ~/.claude/commands/）
│   ├── pr.md                        → /pr
│   ├── debug-to-pr.md               → /debug-to-pr
│   └── ...
│
├── scripts/                         → CI / lint 工具腳本
│   ├── lint_skill_bash.py           → Bash hygiene linter（掃描 SKILL.md / commands/*.md）
│   └── ...
│
├── docs/                            → 技術文件
│   └── openspec/                    → OpenSpec live example（changes/ 目錄）
│
└── .claude/
    ├── rules/                       → 編碼慣例（依 glob pattern 自動載入，01-16）
    │   ├── 01-language-and-tone.md
    │   ├── 13-bash-anti-patterns.md → AP1/AP2 + bash-to-script subagent 觸發條件
    │   └── 16-allowlist-hygiene.md  → Allow-list 衛生準則
    ├── agents/                      → Subagent 定義
    │   ├── bash-to-script.md        → AP1 修法：抽 bash 邏輯到 scripts/
    │   ├── explorer.md              → 唯讀探索（Read/Grep/Glob only）
    │   ├── handover-context.md      → 交班摘要產生
    │   └── security-scanner.md      → Secret 掃描
    └── hooks/                       → PreToolUse / PostToolUse hooks（共 ~10 個）
        ├── bash-ap1-inline-check.sh → 攔截 AP1 違規（multi-line python -c 等）
        ├── bash-ap2-check.py        → 攔截 AP2 違規（Unicode chars in bash blocks）
        ├── protect-push.sh          → 防止從 worktree branch 直推 origin/main
        ├── pre-compact-handover.sh  → context compact 前攔截並建議 handover
        └── ...                      → 其餘 hook 見 .claude/hooks/ 目錄
```

## Runtime 設定（不進 git）

```text
.runtime/
├── schedules.json   → Scheduler job 清單（此 repo 的 job；gmail_newsletter 在 ainization-skill）
├── scheduler.db     → 執行歷史（SQLite）
└── logs/            → 每次執行的 stdout/stderr log

~/.agents/
├── config.json      → skill_repos map + legacy skill_repo 路徑（make install 後自動寫入）
├── ports.json       → Local Port Manager port 登記
└── skills/          → 已安裝 skill 的 symlink
```

## 關鍵入口速查

| 任務 | 指令 |
|------|------|
| 執行所有 CI 檢查 | `make check` |
| 跑 harness 評分 | `uv run python -m tasks.harness_eval scan --path .` |
| 跑 bash lint | `uv run python scripts/lint_skill_bash.py --fail` |
| 安裝 global skills | `make install` |
| 單一 skill | `make install-one SKILL=<name>` |
| scheduler 手動 tick | `uv run python -m tasks.scheduler tick` |
