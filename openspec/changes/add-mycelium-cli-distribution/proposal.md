## Why

Issue #222 的 Gap A 已定案採方向 1：六個依賴 `tasks/` 的 skill 目前必須先定位一份 yibi-stack checkout，再以 `uv run ... python -m tasks.*` 執行；例如 `pr-cycle-fast` 直接呼叫 `tasks.pr_orchestrator`（`plugins/pr-flow/skills/pr-cycle-fast/SKILL.md:23-55`），`learn` 也先解析 `SKILL_REPO` 才能呼叫 `tasks.mycelium`（`plugins/growth/skills/learn/SKILL.md:25-43`）。這使 plugin 已安裝但本機沒有 checkout 的環境無法使用完整 skill 路徑，且 cwd 推斷曾把資料寫入錯誤 project。

現有 `yibi-stack` package 已具備 Phase A 所需的發行骨架：Hatchling build、只包含 `tasks` 的 wheel、排除 tests、核心依賴只有 Click 與 Pydantic，並已有 `portman` console script 先例（`pyproject.toml:1-46`）。因此本 change 讓既有 package 從 Git tag 安裝後直接提供 CLI，不再要求這六個 skill 透過 checkout import `tasks`。

## What Changes

[MODIFIED] 既有變更內容保留，並重整為 delivery summary；正式 Persona／Action／Outcome 與 Acceptance Criteria 見 Step 1。

- 在既有 `yibi-stack` package 的 `[project.scripts]` 新增 `mycelium = "tasks.mycelium.cli:cli"`；因 `tasks.pr_orchestrator` 已是 Click group（`tasks/pr_orchestrator/cli.py:71-73`），同一 wheel 也新增 `pr-orchestrator = "tasks.pr_orchestrator.cli:cli"`。既有 `portman` entry point 保持不變。
- Apply/verification 選定並記錄單一具體 immutable release tag；README 與六個 SKILL.md `[FAIL]` gate 只寫入由該 recorded release tag 形成的同一條 exact tag-pinned Git install command。
- 將 `pr-cycle-fast`、`pr-control-log`、`pr-retrospective`、`mycelium`、`learn`、`local-port-manager` 的執行路徑改為已安裝的 `pr-orchestrator`、`mycelium` 或 `portman`；project-sensitive 呼叫顯式傳入 project，避免依賴 cwd 推斷。
- 每個 skill 都在工作前以 `command -v` preflight 實際會呼叫的每個 console script：`pr-cycle-fast` 檢查 `pr-orchestrator`（若其路徑也呼叫 `mycelium` 則兩者都檢查）、四個 mycelium-backed skills 檢查 `mycelium`、`local-port-manager` 檢查 `portman`；找不到時以 `[FAIL]` 顯示唯一的 recorded-tag 安裝指令並停止。
- 將 auto-handover hook 註冊改為在 install-hooks 時從 PATH 動態解析 `mycelium` 的絕對路徑，以 `shlex.quote` 或等價方式 shell-quote 後固定寫入 `~/.claude/settings.json`；解析失敗時以 `[FAIL]` 停止。`.claude/hooks` 的相容 wrapper 則以 `command -v mycelium` 尋找 binary，找不到時同樣以 `[FAIL]` 停止，不再 in-process import `tasks.mycelium`。hook 不使用 `uvx`。
- 遷移採 verify-before-unlink：保留六個 real-checkout skill symlink 與其 `SKILL_REPO` / `resolve-skill-repo` 相容路徑，直到無 checkout 的乾淨環境完成安裝與六條 CLI 路徑驗證；驗證成功後才移除。
- README 的 English 與繁體中文 install 章節改為 plugin 安裝加上 `uv tool install` CLI 安裝的 two-track 說明。

## Step 1 - User Stories

[MODIFIED] 原本散落於 What Changes 的 US-001／US-002 敘事改為正式 User Story blocks；識別碼維持不變。

### US-001: Install yibi-stack CLIs from a Git tag

[MODIFIED]

**Persona**：只安裝 Claude Code plugins、沒有 yibi-stack checkout 的使用者，需要可重現地取得 skills 所依賴的 Python CLIs。

**Action**：以已記錄的 release tag 執行唯一 Phase A Git install command，並依 README 的 plugin／CLI two-track 指引完成安裝。

**Outcome**：使用者可從既有 `yibi-stack` distribution 啟動 `mycelium`、`pr-orchestrator`、`portman`，且 package boundary、test imports 與 Phase A 文件不漂移。

**Acceptance Criteria**：

- **AC-001-1**：GIVEN 目標環境有 `uv`、可存取 GitHub、沒有 yibi-stack checkout，WHEN 使用 recorded release tag 執行 exact Phase A command，THEN 安裝 MUST 成功，且 `mycelium --help`、`pr-orchestrator --help`、`portman --help` MUST 全部 exit 0，不得從 checkout import。
- **AC-001-2**：GIVEN Phase A wheel 與 migration edits 完成，WHEN 檢查 distribution metadata、wheel contents、package root 與 issue #222 的 26 個 test imports，THEN 唯一 distribution MUST 仍為 `yibi-stack`、wheel MUST 含 `tasks` 且排除 `tasks/**/tests/**`、MUST NOT 產生獨立 `mycelium` distribution，`tasks/mycelium` 與 `tasks.mycelium` imports MUST 保持不變。
- **AC-001-3**：GIVEN 使用者閱讀 English 或繁體中文 README install section 或任一六個 skill failure gate，WHEN 尋找安裝方式，THEN MUST 看見 plugin 與 CLI 兩條不同目的的互補軌，README 與六個 gates MUST 使用由同一 recorded release tag 形成的同一條 exact Git-tag command，且 MUST NOT 出現 PyPI install command。

Granularity self-check：**Medium**；預估 3-5 天，單一 Actor（plugin-only 使用者）、單一 Goal（從 Git tag 取得可用 CLI）、3 條可獨立測試的 AC，未超過 7 條且不需拆分。

### US-002: Run the six skills without a checkout

[MODIFIED]

**Persona**：透過 Claude Code plugin cache 使用六個 tasks-dependent skills 的使用者，希望從任意 project cwd 執行既有 workflow。

**Action**：啟動六個 skills、project-sensitive commands 與 auto-handover hooks，全部使用 PATH 中已安裝的 console scripts 與顯式 target。

**Outcome**：六個 skills 不再依賴 checkout，缺少 binary 時會在副作用前 fail-loud，hooks 使用穩定 binary，且 cleanup 只有在 clean-environment verification 全綠後發生。

**Acceptance Criteria**：

- **AC-002-1**：GIVEN PATH 缺少任一 skill 實際將呼叫的 console script，WHEN 該 skill 開始第一個 tasks-backed operation，THEN skill MUST 已 preflight 每個 required script、指出缺少者、輸出 `[FAIL]` 與 exact recorded-tag command、非零退出，且 MUST NOT 嘗試 `SKILL_REPO`、`uv run`、`uvx` 或 `python -m tasks.*`；`pr-cycle-fast` 即使可找到 `mycelium`，找不到 `pr-orchestrator` 也 MUST 在工作前失敗。
- **AC-002-2**：GIVEN Git-tag distribution 已安裝且沒有 yibi-stack checkout，WHEN 六個 skills 各執行代表路徑，THEN `pr-cycle-fast` MUST 呼叫 `pr-orchestrator`，其他 mycelium consumers MUST 呼叫 installed `mycelium` command groups，`local-port-manager` MUST 呼叫 `portman`。
- **AC-002-3**：GIVEN CLI process cwd 與 intended target 不同，WHEN 六個 skills 執行 project-sensitive operation，THEN mycelium MUST 收到 `--project <slug>`、pr-orchestrator MUST 收到 `--repo-root <absolute-path>`、portman MUST 收到既有介面要求的 explicit project option 或 operand，且 global commands MUST NOT 收到虛構 scope flag。
- **AC-002-4**：GIVEN PATH 中有 installed `mycelium`，WHEN install-hooks 註冊 auto-handover 或 checkout wrapper 處理支援的 payload，THEN settings commands MUST 以 `shlex.quote` 或等價方式 shell-quote registration-time resolved absolute path，shell parsing 後的第一個 argv MUST 等於該路徑，wrappers MUST 使用 runtime `command -v` 結果，且兩者 MUST NOT 使用 checkout import 或 `uvx`；解析失敗 MUST `[FAIL]` 並停止。
- **AC-002-5**：GIVEN 六個 symlink 與 resolver lane 仍存在，WHEN recorded-tag clean-environment verification 失敗、未執行或全部通過，THEN 前兩種狀態 MUST 阻擋 cleanup；只有全部通過後才 MUST 移除六個指定 symlink 與已無用途的 resolver logic，並保持 plugin discovery 與 installed CLI 可用。

Granularity self-check：**Medium**；預估 3-5 天，單一 Actor（plugin-cache skill 使用者）、單一 Goal（無 checkout 執行六個 skills）、5 條可獨立測試的 AC，未超過 7 條且不需拆分。

## Step 4 - Assumptions and Constraints

[ADDED]

### Assumptions

[ADDED] 本表只引用 `problem-frame.md` 的 W-ID 與原始內容／後果，W 仍是單一來源。

| W-ID | 假設內容 | 若不成立的影響 |
|------|----------|----------------|
| W1 | `uv` 已存在於目標機器，且可執行 `uv tool install`。 | Phase A 唯一安裝入口無法啟動；需新增 uv bootstrap 或重定義支援矩陣。 |
| W2 | PATH 在 interactive shells 與執行 hooks 的 contexts 都暴露 uv tool bin directory。 | skill preflight、install-hooks 或 checkout wrapper 會找不到已安裝 binary，R1/R3 不成立。 |
| W3 | 目標機器可透過 `git+https` 存取 `github.com/heyu-ai/yibi-stack`。 | Git-tag install 與 clean-environment acceptance 無法執行，cleanup 必須停止。 |
| W4 | release tags 已存在且不可變，驗證證據會記錄實際 tag。 | 安裝結果不可重現，verify-before-unlink 證據無效，cleanup 必須停止。 |
| W5 | 六個 skills 由 Claude Code plugin cache 消費，不依賴 repo-root `skills/` symlink 才能被發現。 | unlink 後 plugin discovery 會失敗；須保留相容 lane 或先修正 plugin packaging。 |
| W6 | issue #222 field data 顯示 real-checkout symlinks 已在野外被移除，目前狀態對 plugin-only 使用者是 broken。 | 若證據不成立，需重評緊急度與遷移風險，不得以該 field claim 支持 cleanup。 |

### Hard Constraints

[ADDED]

| # | 限制 | 來源 |
|---|------|------|
| C1 | Phase A 在 apply/verification 選定並記錄單一具體 immutable release tag；README 與六個 gates 必須提供由該 tag 形成的同一條 exact tag-pinned Git install command，不得提供變體。 | issue #222 Gap A direction 1、design D3、spec Two-track installation documentation |
| C2 | verify-before-unlink 順序不可顛倒；任一 verification 失敗或未執行都不得移除六個 symlink/resolver lane。 | design D6、spec Verify-before-unlink migration |
| C3 | `tasks/mycelium` package root 與 issue #222 的 26 個 `tasks.mycelium` test import paths 不可變。 | design D1/D6、spec Package root and test import stability |
| C4 | Phase A 只能沿用 `yibi-stack` distribution、wheel 只出貨 `tasks` 且排除 tests，不新增 runtime dependency 或第二個 package。 | design D1/D2、spec Installable yibi-stack CLI distribution |
| C5 | settings hook 在 registration time 將 PATH 解析出的 absolute path shell-quote 後固定寫入 command，且 shell parsing 後第一個 argv 必須等於該 path；checkout wrapper 在 runtime 使用 `command -v mycelium`；兩者都不得使用 `uvx` 或 checkout import。 | design D5、spec Stable installed hook binary |
| C6 | project-sensitive calls 必須使用既有 explicit target contract；不得以 CLI process cwd 推斷 project，也不得替 global command 發明 flag。 | design D4、spec Explicit project targeting |

### Out of Scope

[MODIFIED] 原 Non-Goals bullets 已轉為附理由與未來考量的正式範圍表。

| Item | Reason | Future Consideration |
|------|--------|----------------------|
| PyPI publishing 或 PyPI install command | Phase A 只交付 recorded Git-tag install；提前文件化尚未存在的路徑會誤導使用者。 | **Phase B** 完成 publishing、版本與 release gate 後再評估。 |
| 獨立 `mycelium` package 或新的 distribution 名稱 | `mycelium` 名稱已被其他 library 使用，拆包會引入雙重版本與 import governance。 | 只有在另案核准 distribution split 與 migration plan 時重評。 |
| 移動 `tasks.mycelium` root 或改寫 26 個 test imports | 這是 Phase A 的 compatibility invariant，移動會把 distribution change 擴張為 package migration。 | 未來 major-version package migration 必須獨立提案。 |
| 六個指定 skills 以外的 tasks-dependent consumers | Gap A direction 1 Phase A 已明確限定六個 field-broken consumers。 | 依後續 field evidence 以獨立 change 分批遷移。 |
| 改變 mycelium、pr-orchestrator 或 portman 業務語意 | 本 change 只處理 distribution、invocation、hook boundary 與 migration ordering。 | 任何 workflow/data-model 變更使用各自 capability change。 |

## Step 5 - Completion Standard

[ADDED]

### Definition of Done

[ADDED]

- [ ] US-001 與 US-002 的全部 AC 已實作。
- [ ] `testplan.md` 的 planned TCs 已在 apply phase 轉為 executed，結果與證據已記錄。
- [ ] SMK-001、SMK-002、SMK-003 三個 smoke scenarios 全部通過。
- [ ] `make ci` exit 0。
- [ ] 變更已完成 code review 並 merge。

### Smoke Test Scenarios

[ADDED]

#### Scenario: smk-install-happy-path -- SMK-001 Git-tag 安裝成功

**GIVEN** clean HOME/PATH 有 `uv` 與 `git`、可存取 GitHub、沒有 yibi-stack checkout，且此 illustrative scenario 的 recorded immutable tag 為 `v1.11.0`
**WHEN** 執行 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"`，再執行三個 console scripts 的 `--help`
**THEN** install、`mycelium --help`、`pr-orchestrator --help`、`portman --help` MUST 全部 exit 0，且 MUST NOT 查找 checkout

#### Scenario: smk-missing-binary-gate -- SMK-002 缺 required binary 時先阻擋

**GIVEN** Claude Code plugin cache 可發現六個 skills，且每列 PATH 都缺少該 skill 實際會呼叫的一個 console script；`pr-cycle-fast` 列特別保留 `mycelium` 但移除 `pr-orchestrator`
**WHEN** 依序啟動六個 skills 的 required-script preflight
**THEN** 每個 skill MUST 先指出缺少的 script、印 `[FAIL]` 與 exact recorded-tag install command、非零退出，且 MUST NOT 嘗試 `SKILL_REPO`、`uv run`、`uvx` 或 `python -m tasks.*`

#### Scenario: smk-hook-registration -- SMK-003 hook 固定已解析路徑

**GIVEN** clean HOME 的 `~/.claude/settings.json` 為空，PATH 中 installed `mycelium` 的絕對路徑為 `/tmp/mycli-smoke/bin/mycelium`
**WHEN** 執行 `mycelium handover install-hooks` 並讀取 PreCompact 與 SessionStart commands
**THEN** 兩個 command 經 shell parsing 後的第一個 argv MUST 等於 `/tmp/mycli-smoke/bin/mycelium` 並使用正確 hook subcommand，resolved path MUST 以 shell-safe 形式寫入，且 command MUST NOT 含 checkout path、`python -m tasks.mycelium` 或 `uvx`

### Traceability Source

[ADDED] `testplan.md` 的 **Traceability Matrix** 是 US、scenario slug、TC-ID 與 evidence mapping 的單一來源；本 proposal 不複製該矩陣。

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
