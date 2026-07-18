## Why

Issue #222 的 Gap A 已定案採方向 1：六個依賴 `tasks/` 的 skill 目前必須先定位一份 yibi-stack checkout，再以 `uv run ... python -m tasks.*` 執行；例如 `pr-cycle-fast` 直接呼叫 `tasks.pr_orchestrator`（`plugins/pr-flow/skills/pr-cycle-fast/SKILL.md:23-55`），`learn` 也先解析 `SKILL_REPO` 才能呼叫 `tasks.mycelium`（`plugins/growth/skills/learn/SKILL.md:25-43`）。這使 plugin 已安裝但本機沒有 checkout 的環境無法使用完整 skill 路徑，且 cwd 推斷曾把資料寫入錯誤 project。

現有 `yibi-stack` package 已具備 Phase A 所需的發行骨架：Hatchling build、只包含 `tasks` 的 wheel、排除 tests、核心依賴只有 Click 與 Pydantic，並已有 `portman` console script 先例（`pyproject.toml:1-46`）。因此本 change 讓既有 package 從 Git tag 安裝後直接提供 CLI，不再要求這六個 skill 透過 checkout import `tasks`。

## What Changes

- **US-001 — Install from Git:** 在既有 `yibi-stack` package 的 `[project.scripts]` 新增 `mycelium = "tasks.mycelium.cli:cli"`；因 `tasks.pr_orchestrator` 已是 Click group（`tasks/pr_orchestrator/cli.py:71-73`），同一 wheel 也新增 `pr-orchestrator = "tasks.pr_orchestrator.cli:cli"`。既有 `portman` entry point 保持不變。
- 唯一支援且寫入 README 與 SKILL.md `[FAIL]` gate 的 Phase A 安裝指令為 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"`。
- **US-002 — Run six skills without a checkout:** 將 `pr-cycle-fast`、`pr-control-log`、`pr-retrospective`、`mycelium`、`learn`、`local-port-manager` 的執行路徑改為已安裝的 `pr-orchestrator`、`mycelium` 或 `portman`；project-sensitive 呼叫顯式傳入 project，避免依賴 cwd 推斷。
- 六個 skill 都先執行 `command -v mycelium`；找不到時以 `[FAIL]` 顯示唯一的 Git-tag 安裝指令並停止。
- 將 auto-handover hook 註冊改為在 install-hooks 時從 PATH 動態解析 `mycelium` 的絕對路徑，並將解析結果固定寫入 `~/.claude/settings.json`；解析失敗時以 `[FAIL]` 停止。`.claude/hooks` 的相容 wrapper 則以 `command -v mycelium` 尋找 binary，找不到時同樣以 `[FAIL]` 停止，不再 in-process import `tasks.mycelium`。hook 不使用 `uvx`。
- 遷移採 verify-before-unlink：保留六個 real-checkout skill symlink 與其 `SKILL_REPO` / `resolve-skill-repo` 相容路徑，直到無 checkout 的乾淨環境完成安裝與六條 CLI 路徑驗證；驗證成功後才移除。
- README 的 English 與繁體中文 install 章節改為 plugin 安裝加上 `uv tool install` CLI 安裝的 two-track 說明。

## Non-Goals

- 不發布 PyPI package；PyPI publishing 是 Phase B，README 與 skill gate 不預先寫 PyPI 安裝方式。
- 不建立或抽離獨立 `mycelium` package。`mycelium` 名稱已被其他 library 使用，本 change 沿用既有 `yibi-stack` distribution。
- 不移動 `tasks.mycelium` package root，也不改寫 issue #222 所列 26 個 `tasks/mycelium/tests` 測試檔的 import path。
- 不擴充到這六個 skill 以外的 tasks-dependent consumers，也不改變 mycelium、pr-orchestrator 或 portman 的業務語意。

## Capabilities

### New Capabilities

- `mycelium-cli`: 定義 mycelium CLI 的 Git-tag 安裝／distribution contract，以及六個 tasks-dependent skill 改用 installed CLI、顯式 project target、install-time-resolved hook binary 與 verify-before-unlink 遷移順序的行為。

### Modified Capabilities

(none)

## Impact

- Affected specs: `mycelium-cli`（new）
- Affected code:
  - New: (none)
  - Modified:
    - pyproject.toml
    - README.md
    - scripts/tests/test_packaging.py
    - tasks/mycelium/cli.py
    - tasks/mycelium/auto_handover_hooks.py
    - tasks/mycelium/tests/test_cli.py
    - tasks/mycelium/tests/test_auto_handover_hooks.py
    - tasks/pr_orchestrator/tests/test_cli.py
    - .claude/hooks/pre-compact-handover.sh
    - .claude/hooks/post-compact-handover-back.sh
    - plugins/pr-flow/skills/pr-cycle-fast/SKILL.md
    - plugins/pr-flow/skills/pr-control-log/SKILL.md
    - plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh
    - plugins/pr-flow/skills/pr-retrospective/SKILL.md
    - plugins/pr-flow/skills/pr-retrospective/scripts/bootstrap.sh
    - plugins/growth/skills/mycelium/SKILL.md
    - plugins/growth/skills/learn/SKILL.md
    - plugins/util/skills/local-port-manager/SKILL.md
  - Removed（only after end-to-end CLI verification passes）:
    - skills/pr-cycle-fast
    - skills/pr-control-log
    - skills/pr-retrospective
    - skills/mycelium
    - skills/learn
    - skills/local-port-manager
- Dependencies: 不新增 runtime dependency；維持 `click>=8.1` 與 `pydantic>=2.0`（`pyproject.toml:7-12`）。
