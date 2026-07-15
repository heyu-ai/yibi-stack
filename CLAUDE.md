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

## Dev 指令

> **小技巧**：`/config key=value` 可即時改設定，省去開 `/config` 選單
> （如 `/config thinking=false`）；在 interactive、`-p` headless、Remote Control 皆可用
> （Claude Code v2.1.181+）。`/config --help` 列出所有 shorthand key（v2.1.183+）。

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

- **suspect a hook/skill/rule is interfering → `claude --safe-mode` first**: this repo carries
  many hooks and rules (protect-push, bash-ap2-check, bash-ap1-inline-check, protect-worktree,
  pre-commit, plus 14 rule files). When something behaves unexpectedly and you suspect the
  customization layer, launch `claude --safe-mode` (or set `CLAUDE_CODE_SAFE_MODE=1`): it
  disables all CLAUDE.md / skills / plugins / hooks / MCP / custom commands & agents, while
  authentication, model, built-in tools, and permissions still work. If the problem disappears
  in safe mode, the culprit is in the customization layer — bisect from there. (Claude Code
  v2.1.169+)
- **protect-push blocks `gh pr merge`**: agent cannot merge; user must run
  `! gh pr merge <n> --squash --delete-branch`. Also: running `gh pr merge` from a linked
  worktree when the main repo has `main` checked out fails (`fatal: 'main' is already used by
  worktree`) — run from the main repo directory instead.
- **plugin command source deleted → top-level symlink becomes dangling**: `git status` does
  not show it (CI `FileNotFoundError` catches it). When deleting `plugins/<pack>/commands/<cmd>.md`,
  also run `git rm commands/<cmd>.md` to remove the top-level symlink. When creating or
  verifying any symlink, always dereference it (`ls <link>/` with trailing slash) —
  `ls -la <link>` only shows the link itself and always succeeds; relative targets count
  parent levels from the symlink's own directory, so one extra `..` silently escapes the
  repo root (PR #150 C1).
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
- **`Path.glob("*/x/*")` doesn't cross `/` like regex `.*` does** — see rule 02 for fix.
- **`plugins/harness` has no `package.json`**: not all subdirectories under `plugins/` are
  installable plugins. `plugins/harness` is a README-only container; install with
  `make install-one SKILL=harness-eval`. Parallel listings must inline-annotate this exception,
  otherwise readers inherit the block's semantic and silently fail.
- **bootstrap script `[SKIP]` should be `[WARN]` for missing prerequisites** — see rule 13 for fix.
- **agy auth detection uses `onboardingComplete`, not `installation_id`**:
  `~/.gemini/antigravity-cli/installation_id` exists before OAuth completes (false positive).
  Check `~/.gemini/antigravity-cli/cache/onboarding.json` for `onboardingComplete: true` instead.
- **`make install` is mandatory after pulling, not optional**: skills locate this repo via
  `~/.agents/bin/resolve-skill-repo`, a symlink that only `make install` creates. Pull without
  re-installing and those skills fail with
  `[FAIL] ... 請在 yibi-stack 目錄執行 make install` until you run it. This is deliberate: the
  failure is loud and names its own fix, replacing the previous `~/.agents/config.json`
  `skill_repo` lookup whose failure mode was **silence** (the key is co-written by several skill
  repos, so the last installer won and every caller silently ran against the wrong checkout —
  measured live in PR #224, where it pointed at `ainization-skill`). Corollary: if you **move**
  a checkout, re-run `make install` — the symlink is repointed only by that run.
- **`make install` must run from the MAIN repo, never from a worktree**: the install targets
  point global symlinks at `$(CURDIR)`, so installing from `.claude/worktrees/<name>/` aims
  them at a directory that `/clean-merged` deletes after the branch merges — then every skill
  dies. Neither the resolver's identity gate nor the Makefile's `resolved == $(CURDIR)` gate
  can catch this (a worktree is a complete checkout, and inside one those two paths are equal
  by definition). `scripts/assert_not_worktree.sh` now blocks it as the first line of
  `install` / `install-project` / `install-one` / `install-force-one` / `promote`; see rule 11
  for why it fails loud instead of auto-deriving the main repo, why its fail-open forgives only
  git's literal `not a git repository`, and why it normalizes with `pwd -P` rather than
  `--path-format=absolute`. Known remaining gap, not yet fixed:
  `make install-scheduler` embeds `PROJECT_ROOT` (`tasks/_paths.py`, self-located from
  `__file__`) into the LaunchAgent plist's `WorkingDirectory` at `tasks/scheduler/cli.py:248`,
  so it reproduces this bug through Python rather than symlinks and is **not** covered by the
  guard. `make install-all` is safe only because it chains `install` first, which aborts.
- **installed skills go stale when local `main` is behind `origin/main`**: `make install` copies
  skill scripts to `~/.agents/skills/`; if you don't pull main + re-run `make install`, those
  copies keep an old version. Concretely, the pr-cycle-deep agy scripts stay on the pre-fix
  `@file` form and go agentic inside worktrees (live-reproduced in PR #157's own mob review).
  Fix: `git pull` on main, then `make install`.
  **A second, distinct failure mode**: some skills (e.g. `pr-retrospective`) are not copied at
  all — `~/.claude/skills/<name>` and `~/.agents/skills/<name>` are symlinks straight into
  `<main-repo-checkout>/skills/<name>` (itself a symlink into `plugins/<pack>/skills/<name>`).
  For these, `make install` does nothing to freshen content — the SKILL.md body is only as
  fresh as the **local `main` checkout's working tree**. Running `/pr-retro` right after merging
  a PR that rewrote that very skill (e.g. PR #205's `handovers`→`retrospectives` migration) can
  load pre-merge instructions straight from a stale local `main`, silently reintroducing the
  exact anti-pattern the merged PR just removed. Fix here is `git pull` on the **main repo
  checkout** (not `make install` — there is no copy to refresh); check `git log -1` /
  `git status` on the resolved `SKILL_REPO` before trusting a freshly-loaded symlinked skill
  body, especially right after merging a PR that touches that skill (PR #205 retro, `/pr-retro`
  on itself).
- **linked worktree `git rev-parse --show-toplevel` returns worktree path, not main repo** —
  see rule 15 for the correct `--git-common-dir` pattern.
- **`pre-commit run --files` only scans specified files; CI uses `--all-files`**: local
  `pre-commit run --files <file>` misses pre-existing problems in other files. Always run
  `make ci` before pushing (includes `--all-files` + pytest).
- **widening a pre-commit hook's `files:` regex doesn't guarantee the underlying tool
  actually scans those paths**: verify the tool's own implementation covers the same
  scope, or you get a "green hook" that runs and passes without checking the changed
  content (incident: PR #190, `lint-skill-overlap`'s regex matched plugin-only skills
  before the scanner itself was extended to cover them).
- **warn-only pre-commit hooks need `verbose: true` to show output**: pre-commit
  hides stdout/stderr for any hook that exits 0 by default, so a warn-only tool's
  `[WARN]` messages are invisible in `make ci` / CI without it. Also: a stale local
  `~/.cache/pre-commit` can report clean when a fresh environment would catch a real
  issue — run `pre-commit clean` before trusting a green local run (incident: PR #190).
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
- **pylint 4.x renamed `max-instance-attributes` to `max-attributes`**: `[tool.pylint.design]`
  in `pyproject.toml` must use `max-attributes = N` (not `max-instance-attributes`). The old
  name triggers `E0015: Unrecognized option found: max-instance-attributes` in pylint 4.0+.
  Local environments with older pylint pass silently; CI with a newer version catches it.
  After upgrading pylint, always run `uv run pylint --generate-toml-config | grep max-` to
  verify the current option names.
- **unattended/scheduled retries use `CLAUDE_CODE_RETRY_WATCHDOG`, not a large
  `CLAUDE_CODE_MAX_RETRIES`**: since Claude Code v2.1.186, `CLAUDE_CODE_MAX_RETRIES` is capped
  at 15, so a scheduled or batch task can no longer get "long auto-retry" by setting it high —
  use the retry watchdog instead. Affects `nightly-self-improvement` (the only `enabled: true`
  job in `.runtime/schedules.json`) and any future ACP Gateway `skill:` job. Setting
  `CLAUDE_CODE_MAX_RETRIES` above 15 silently clamps to 15, not an error.
- **`!` bash command output now auto-triggers a Claude response** (v2.1.186): a `!`-prefixed
  bash command's output used to be context-only; it now makes Claude respond to that output by
  default. To restore the old "context only, no response" behavior, set
  `"respondToBashCommands": false` in `settings.json`. This does not change the protect-push
  gotcha's conclusion (the agent still cannot merge; the user runs `! gh pr merge <n>` manually)
  — but the agent will now speak to the merge output rather than staying silent, so expect a
  follow-up message after a manual `!` command.
