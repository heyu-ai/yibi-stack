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
  rm -f "$CLAUDE_JOB_DIR/commit_msg.txt"
  ```

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
- **`plugins/`** — Claude Code plugin packs（7 個）：bash-hygiene / sdd / growth / pr-flow / 3rd-tools / tdd / util

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

## Search Strategy

- `rg --type py` 優先於通用 grep 搜尋 Python 程式碼
- `rg -l` 先列出匹配檔案清單，再用 Read 讀取內容

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

## 已知 Gotcha

- **protect-push 攔截 `gh pr merge`**：agent 無法自行 merge；需使用者執行 `! gh pr merge <n> --squash --delete-branch`
- **`CLAUDE_EFFORT=normal` 是 hook 預設值**：hooks 使用 `${CLAUDE_EFFORT:-normal}`；SKILL.md effort 表格的 fallback note 必須同時涵蓋 unset 和 `normal`（兩者皆視為 medium）。
  CC 2.1.133+ 起 `$CLAUDE_EFFORT` 在 Bash tool（含 hook script）中已是真實 env var，可直接讀取；`:-normal` fallback 是相容舊版或未設定 session 的保護
- **Effort fallback 是風險判斷，非慣例**：一般工具 fallback 設 `medium`；規格展開／深度 review 工具（如 spectra-amplifier）可設 `high`，因規格缺漏代價高於多做
- **`${CLAUDE_EFFORT}` 在 SKILL.md 不展開**：靜態 Markdown 中 agent 讀到的是 literal string；若需實際值，用 `echo "${CLAUDE_EFFORT:-normal}"` eval。Hook script（bash）中則可直接讀取（CC 2.1.133+），無需 eval
- **Slash command 的 bash code block 被 agent 重寫**：commands/*.md 或 SKILL.md 中，
  agent 理解意圖後自行生成 bash 而非複製貼上，可能引入反模式（fat command、
  `if [ $? -ne 0 ]`、`||` 條件分支）。複雜 bash 邏輯移到 `commands/scripts/*.sh` 或
  `skills/<name>/scripts/*.sh`，文件只保留單行 `bash <script-path>` 呼叫。範例：
  `plugins/pr-flow/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh`
  （PR review Step 3.1 工作目錄準備）。配合 `.claude/rules/16-allowlist-hygiene.md`，
  allow-list 永久放行 pattern 用完整 script 路徑而非 fat command wildcard。
- **make target 名稱一律逐字引用**：README/CLAUDE.md 中的 target 名稱必須從 Makefile 直接 copy，不可改寫成「可讀標籤」（例如把 `patch-pr-review-agents` 縮寫為其他名稱），否則使用者執行時 404
- **hook 腳本在 `.claude/hooks/` 不等於已啟用**：Claude Code 只執行在 `settings.json` 的 `hooks` 命令字串中登記的 hook；評估 hook 有效性必須做「檔案存在 × settings.json 登記」雙重交叉驗證
- **`Path.rglob()` 不追蹤 symlink**：`pathlib` 的 `rglob()` 預設不進 symlink 子目錄。若目標目錄含 symlink（如本 repo `skills/` 的 plugin symlink），改用 `os.walk(followlinks=True)` 或 Python 3.13+ 的 `glob(follow_symlinks=True)`
- **`plugins/harness` 無 `package.json`**：`plugins/` 下並非所有子目錄都是可 `claude plugin install` 的正式 plugin。
  `plugins/harness` 是 README-only 容器，需用 `make install-one SKILL=harness-eval`；並列時必須 inline 標注例外，否則讀者繼承區塊語意靜默失敗。
- **bootstrap script 的 `[SKIP]` 應改 `[WARN]`**：`make install-all` chain 中目標資源（如 `~/.claude/settings.json`）不存在時，靜默 `[SKIP]` + exit 0 等同問題隱藏。
  應改 `[WARN]` 並說明修復指令（例：「請先啟動 Claude Code 以產生設定檔，再重跑 `make patch-agy-allow-list`」）。
- **agy auth 偵測用 `onboardingComplete`，不用 `installation_id`**：
  `~/.gemini/antigravity-cli/installation_id` 在 agy 首次啟動（OAuth 完成前）就存在，用它做 auth check 會 false positive。
  正確做法：檢查 `~/.gemini/antigravity-cli/cache/onboarding.json` 的 `onboardingComplete: true` 欄位。
- **linked worktree 內 `git rev-parse --show-toplevel` 回傳 worktree 路徑，不是主 repo 路徑**：
  在 `.claude/worktrees/<name>/` 等 linked worktree 內呼叫 `--show-toplevel`，得到的是 worktree 自身的目錄（如 `.claude/worktrees/feat+...`），不是 repo 根目錄。
  需要主 repo 路徑時改用 `git rev-parse --path-format=absolute --git-common-dir`，再取 `Path(result).parent`。
  適用場景：任何在 worktree 內計算 project slug、log 路徑、transcript 目錄等依賴主 repo 位置的邏輯。
- **`pre-commit run --files` 只掃指定檔案，CI `--all-files` 掃全 repo**：本地跑 `pre-commit run --files <file>` 只檢查指定檔案，push 前若有未改動但有 pre-existing 問題的檔案（如 `settings.json` 缺 trailing newline），本地不會報錯但 CI 會失敗。
  正確做法：push 前執行 `make ci`（內含 `pre-commit run --all-files` + pytest），而非只跑 `pre-commit run --files <file>`。
