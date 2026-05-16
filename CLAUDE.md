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
  - **可執行 skill**：有對應的 `tasks/` Python 實作（如 session-memory、scheduler）
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

# 新環境一次到位
make install-all         # 等同 install + install-handover-hooks + install-scheduler
```

## Runtime 設定檔（不進 git）

| 檔案 | 用途 |
|------|------|
| `~/.agents/ports.json` | Local Port Manager port 登記（機器層，跨專案共用） |
| `.env` | 環境變數（帳號密碼、加密金鑰） |
| `.runtime/schedules.json` | Scheduler 排程設定（job 清單、時間、類型） |
| `.runtime/scheduler.db` | Scheduler 執行歷史（SQLite） |
| `.runtime/logs/` | Scheduler 每次執行的 stdout/stderr log |

## 已知 Gotcha

- **protect-push 攔截 `gh pr merge`**：agent 無法自行 merge；需使用者執行 `! gh pr merge <n> --squash --delete-branch`
- **`CLAUDE_EFFORT=normal` 是 hook 預設值**：hooks 使用 `${CLAUDE_EFFORT:-normal}`；SKILL.md effort 表格的 fallback note 必須同時涵蓋 unset 和 `normal`（兩者皆視為 medium）
- **Effort fallback 是風險判斷，非慣例**：一般工具 fallback 設 `medium`；規格展開／深度 review 工具（如 spectra-amplifier）可設 `high`，因規格缺漏代價高於多做
- **`${CLAUDE_EFFORT}` 在 SKILL.md 不展開**：靜態 Markdown 中 agent 讀到的是 literal string；若需實際值，用 `echo "${CLAUDE_EFFORT:-normal}"` eval
- **Slash command 的 bash code block 被 agent 重寫**：commands/*.md 中，agent 理解意圖後自行生成 bash 而非複製貼上，可能引入反模式。複雜 bash 邏輯移到 `commands/scripts/*.sh`
