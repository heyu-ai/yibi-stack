<!-- markdownlint-disable MD041 -->
<!-- SPECTRA:START v1.0.2 -->

### Spectra Instructions

This project uses Spectra for Spec-Driven Development(SDD). Specs live in `openspec/specs/`, change proposals in `openspec/changes/`.

## Use `/spectra-*` skills when

- A discussion needs structure before coding → `/spectra-discuss`
- User wants to plan, propose, or design a change → `/spectra-propose`
- Tasks are ready to implement → `/spectra-apply`
- There's an in-progress change to continue → `/spectra-ingest`
- User asks about specs or how something works → `/spectra-ask`
- Implementation is done → `/spectra-archive`
- Commit only files related to a specific change → `/spectra-commit`

## Workflow

discuss? → propose → apply ⇄ ingest → archive

- `discuss` is optional — skip if requirements are clear
- Requirements change mid-work? Plan mode → `ingest` → resume `apply`

## Parked Changes

Changes can be parked（暫存）— temporarily moved out of `openspec/changes/`. Parked changes won't appear in `spectra list` but can be found with `spectra list --parked`.
To restore: `spectra unpark <name>`. The `/spectra-apply` and `/spectra-ingest` skills handle parked changes automatically.

## Commit Message Convention

執行 `/spectra-commit`（以及任何需要 multi-line commit message 的 skill）時：

- **單行 message**：直接 `git commit -m "type(scope): description"`
- **多行 message**（含空行或多段落）：先用 Write tool 寫入 `$CLAUDE_JOB_DIR/commit_msg.txt`，再執行：

  ```bash
  git commit -F "$CLAUDE_JOB_DIR/commit_msg.txt"
  ```

  不需要（也不應該）之後執行 `rm -f "$CLAUDE_JOB_DIR/commit_msg.txt"`：
  `$CLAUDE_JOB_DIR` 在 job 結束後自動清理；`rm` 是 Bash call 且 Rule 16 Red Flag 2 禁止 allow-list `Bash(rm:*)`，每次都跳 permission prompt。

**不要**用 `git commit -m "$(cat <<'EOF' ... EOF)"`：外層 `"..."` 包 `$()`
subshell 觸發 Claude Code parser `Unhandled node type: string`（Quoting Rule 2）；
heredoc 讓命令跨多行，`Bash(git commit:*)` allow-list prefix 無法 match，每次跳 approval prompt。

<!-- SPECTRA:END -->

# yibi-stack

Agentic skill stack for Claude Code — bash hygiene, Spectra/OpenSpec methodology, PR review workflows, TDD, and productivity tools.

## 專案架構

```text
skills/   → Agent 介面層（SKILL.md runbook，agent 讀這個來執行）
tasks/    → Python 實作（CLI、config、models、service、tests）
commands/ → Claude Code slash commands（symlink 到 ~/.claude/commands/）
plugins/  → Claude Code plugin（本 repo 作為 marketplace，各 plugin 獨立子目錄）
docs/     → 技術文件與 OpenSpec live example（docs/openspec/changes/）
scripts/  → CI/lint 工具腳本
```

- **`skills/`** — Agent 的執行介面，每個 skill 有獨立的 `SKILL.md` runbook
  - **可執行 skill**：有對應的 `tasks/` Python 實作（如 mycelium、scheduler）
  - **知識型 skill**：純 Markdown 方法論指引（如 tdd-kentbeck、qa-test-design）
- **`tasks/`** — 實作細節，包含 CLI entry point、設定模型、服務邏輯；`tasks/*/skill.md` 為開發者參考文件
- **`plugins/`** — Claude Code plugin packs（8 個）：bash-hygiene / sdd / growth / pr-flow / 3rd-tools / tdd / util / writing

## 編碼慣例

詳細規範在 `.claude/rules/`，Claude Code 依 glob pattern 自動載入：

- **全域**（01-03）：雙語規範、錯誤處理、安全性
- **`tasks/**`**（04-08）：module 結構、Pydantic、config、DB、CLI
- **`tasks/**/tests/**`**（09）：測試命名與結構化 Test ID
- **`tasks/**/parsers/**`**（10）：abstract base + registry pattern
- **`skills/**`**（11）：SKILL.md 格式與撰寫規範

## 外來 Skill 管理

`skills-lock.json` 追蹤從外部安裝的 skill（版本、hash、來源）。
安裝的外來 skill 透過 symlink 掛載到 `~/.agents/skills/`，內容不在 `skills/` 目錄維護。

## 如何找到可用 Skill

讀 [`skills/README.md`](skills/README.md)，裡面有所有 skill 的索引表格。

## Codebase Map

完整的目錄樹狀地圖與模組入口見 @ARCHITECTURE.md。

關鍵路徑速查：

- 共用路徑常數：@tasks/_paths.py
- Bash lint 工具：@scripts/lint_skill_bash.py
- 編碼慣例總覽：@.claude/rules/（01-16 條規則，依 glob 自動載入）

## 如何執行 Skill

1. 找到對應的 `skills/<skill-name>/SKILL.md`
2. 照 runbook 的步驟依序執行
3. 每個 SKILL.md 都包含：環境檢查 → 設定確認 → 執行指令 → 結果報告

## 新增 Skill 慣例

**知識型 skill（純 Markdown）：**

1. 在 `skills/<skill-name>/SKILL.md` 建立 agent 執行介面
2. 更新 `skills/README.md` 的索引表格

**可執行 skill（有 Python 實作）：**

1. 在 `tasks/<task_name>/` 建立 Python 實作
2. 在 `skills/<skill-name>/SKILL.md` 建立 agent 執行介面
3. 更新 `skills/README.md` 的索引表格

參考 `skills/_template/SKILL.md.tpl` 取得標準格式。

## Dev 指令

```bash
# Python 開發
uv sync                  # 安裝依賴
make ci                  # 本地 CI：pre-commit（lint+format+type+security）+ pytest
make check               # 執行所有檢查（lint + format + typecheck + test）
make lint                # 只跑 ruff linter
make format              # 只跑 ruff formatter
make typecheck           # 只跑 mypy
make test                # 只跑 pytest

# Skill 管理
make install             # 安裝 scope=global skill（跨專案可用）+ commands
make install-one SKILL=x # 安裝單一 skill
make status              # 查看安裝狀態
make uninstall           # 移除自己的 symlink

# Hook 管理（Claude Code auto-handover hook）
make install-handover-hooks   # 安裝 PreCompact + SessionStart hook 到 ~/.claude/settings.json
make uninstall-handover-hooks # 移除 auto-handover hook

# Scheduler 管理
make install-scheduler   # 安裝 LaunchAgent（每 60 秒 tick）
make uninstall-scheduler # 卸載 LaunchAgent
make scheduler-status    # 查看 job 執行狀態

# Plugin 發布（lockstep 版本：所有 plugin 同步升版）
make release TYPE=patch  # patch / minor / major
# 流程：bump pyproject.toml -> sync plugins/*/package.json -> changelog -> test gates -> commit -> tag + GitHub Release

# 新環境一次到位
make install-all         # 等同 build-tools + install + install-project + install-handover-hooks + install-scheduler + patch-pr-review-agents + patch-agy-allow-list
```

## Runtime 設定檔（不進 git）

| 檔案 | 用途 |
| ------ | ------ |
| `~/.agents/ports.json` | Local Port Manager port 登記（機器層，跨專案共用） |
| `.env` | 環境變數（帳號密碼、加密金鑰） |
| `.runtime/schedules.json` | Scheduler 排程設定（job 清單、時間、類型） |
| `.runtime/scheduler.db` | Scheduler 執行歷史（SQLite） |
| `.runtime/logs/` | Scheduler 每次執行的 stdout/stderr log |

## Known Gotchas

- **protect-push blocks `gh pr merge`**: agent cannot merge; user must run
  `! gh pr merge <n> --squash --delete-branch`. Also: running `gh pr merge` from a linked
  worktree when the main repo has `main` checked out fails (`fatal: 'main' is already used by
  worktree`) — run from the main repo directory instead.
- **plugin command source deleted → top-level symlink becomes dangling**: `git status` does
  not show it (CI `FileNotFoundError` catches it). When deleting `plugins/<pack>/commands/<cmd>.md`,
  also run `git rm commands/<cmd>.md` to remove the top-level symlink.
- **slash command bash code block rewritten by agent**: in commands/*.md or SKILL.md, the agent
  understands intent and generates fresh bash instead of copy-pasting — may introduce anti-patterns
  (fat command, `if [ $? -ne 0 ]`, `||` branching). Move complex bash to `commands/scripts/*.sh`
  or `skills/<name>/scripts/*.sh`; documents keep only a single `bash <script-path>` call.
  See rule 16: use full script paths in allow-list, not fat command wildcards.
  Example: `plugins/pr-flow/skills/pr-cycle-deep/scripts/setup-review-dir.sh`.
- **make target names must be copied verbatim**: target names in README/CLAUDE.md must be
  copied directly from the Makefile — never rephrase as a "readable label" (e.g., abbreviating
  `patch-pr-review-agents`) or users get a make error.
- **hook script in `.claude/hooks/` does not mean enabled**: Claude Code only runs hooks
  registered in `settings.json`'s `hooks` command strings. Evaluate hook effectiveness with a
  double check: file exists AND registered in `settings.json`.
- **`Path.rglob()` does not follow symlinks** — see rule 02 for fix.
- **`plugins/harness` has no `package.json`**: not all subdirectories under `plugins/` are
  installable plugins. `plugins/harness` is a README-only container; install with
  `make install-one SKILL=harness-eval`. Parallel listings must inline-annotate this exception,
  otherwise readers inherit the block's semantic and silently fail.
- **bootstrap script `[SKIP]` should be `[WARN]` for missing prerequisites** — see rule 13 for fix.
- **agy auth detection uses `onboardingComplete`, not `installation_id`**:
  `~/.gemini/antigravity-cli/installation_id` exists before OAuth completes (false positive).
  Check `~/.gemini/antigravity-cli/cache/onboarding.json` for `onboardingComplete: true` instead.
- **linked worktree `git rev-parse --show-toplevel` returns worktree path, not main repo** —
  see rule 15 for the correct `--git-common-dir` pattern.
- **`pre-commit run --files` only scans specified files; CI uses `--all-files`**: local
  `pre-commit run --files <file>` misses pre-existing problems in other files. Always run
  `make ci` before pushing (includes `--all-files` + pytest).
- **`make install` loop skip list requires 4 targets synced**: `install`, `install-project`,
  `status-own`, and `uninstall` all scan `skills/*/`. Any non-skill directory created under
  `skills/` (e.g., `spectra init --dir skills/openspec`) must be added to all four skip lists.
  Failure modes: `install`/`install-project` exit 1; `status-own` silently continues; `uninstall`
  silently skips.
- **`.gitignore` does not mean absent from disk** — see rule 02 for fix.
- **`$CLAUDE_JOB_DIR` permission cannot be permanently allowed via session dialog** —
  see rule 16: Scenario 1 needs `Edit(/Users/<you>/.claude/jobs/*)` + `Write(/Users/<you>/.claude/jobs/*)`
  (Edit/Write tool writes); Scenario 2 needs `Bash(verb:*)` patterns (Bash redirect `>`).
  Using the wrong pattern type silently fails to match.
- **Python module rename → `settings.json` hook commands not updated automatically**: after
  renaming a task module (e.g., `session_memory` → `mycelium`), hook commands in
  `~/.claude/settings.json` and project `settings.json` still reference the old name, causing
  `No module named tasks.<old_name>.__main__`. After every module rename, search both settings
  files for the old name and update manually.
- **sdd plugin version lockstep (package.json vs plugin.json)**: `plugins/sdd/package.json`
  and `plugins/sdd/.claude-plugin/plugin.json` must be bumped together — no CI cross-check.
  After bumping `package.json`, sync the `"version"` field in `.claude-plugin/plugin.json`.
- **`gh` CLI `--json` field names must be verified before use**: fields like `databaseId` do
  not exist in `gh pr checks` (some fields only exist in `gh pr list` or other commands).
  Passing a non-existent field name returns empty values silently — any function consuming that
  field will always return an empty result with no error. Fix: run `gh pr checks --json` with no
  field argument to see the default key list, then confirm the target field exists before using it.
