# add-mycelium-cli-distribution — Test Plan

> Source: `openspec/changes/add-mycelium-cli-distribution/specs/mycelium-cli/spec.md`
> Phase: A（install-from-git only；PyPI publishing 為 Non-Goal）

---

## Coverage Analysis

### Acceptance Criteria

- 在完全沒有 yibi-stack checkout 的 clean environment，執行 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@<tag>"` 成功，`mycelium --help` 成功，且六個 skill 的 installed CLI invocation path 全部成功。
- `make ci` fully green。
- README English / 繁體中文 install docs 更新為 plugin 加上 `uv tool install` 的 two-track，且不預先文件化 PyPI。

| Scenario slug | Covered | Technique | TC-ID(s) | Notes |
|--------------|---------|-----------|---------|-------|
| `git-install-exposes-all-console-scripts` | ✓ planned | ST | MYCLI-ST-001, MYCLI-ST-002 | clean environment、無 checkout、三個 help |
| `distribution-retains-existing-package` | ✓ planned | ST | MYCLI-ST-003 | wheel metadata/content，不抽 package |
| `missing-mycelium-fails-before-skill-work` | ✓ planned | DT | MYCLI-DT-001 | 六個 skill 參數化 |
| `six-skills-run-without-checkout` | ✓ planned | ST | MYCLI-ST-004 | 六條 invocation matrix |
| `mycelium-commands-receive-project` | ✓ planned | DT | MYCLI-DT-002 | fake binary capture argv |
| `pr-orchestrator-receives-repo-root` | ✓ planned | DT | MYCLI-DT-003 | 沿用現有 `--repo-root` contract |
| `portman-receives-project` | ✓ planned | DT | MYCLI-DT-004 | option / positional 兩種介面 |
| `settings-hooks-use-stable-binary` | ✓ planned | ST | MYCLI-ST-005 | install-time resolution 後固定的絕對路徑 |
| `checkout-hook-wrappers-avoid-source-imports` | ✓ planned | ST | MYCLI-ST-006 | PATH 上的 fake binary + source scan |
| `test-import-paths-remain-stable` | ✓ planned | CV | MYCLI-CV-001 | 26 個 issue baseline test files |
| `failed-verification-retains-links` | ✓ planned | DT | MYCLI-ORD-001 | gate fail 時禁止 cleanup |
| `successful-verification-allows-cleanup` | ✓ planned | ST | MYCLI-ORD-002 | gate pass 後六 symlink cleanup |
| `readme-shows-two-track-install` | ✓ planned | ST | MYCLI-DOC-001 | English + 繁中 |
| `pypi-install-is-not-pre-documented` | ✓ planned | VL | MYCLI-DOC-002 | README + 六個 gate source scan |

Legend: ✓ planned = 已有 TC 且待 apply 執行 · △ partial = 僅部分路徑有 TC · ✗ missing = 尚無 TC

---

## TC Table

| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|-------------|-------|-----------|----------------|
| MYCLI-ST-001 | 驗證 Git-tag install 在無 checkout 環境可完成 | ST | High | clean HOME、PATH、uv、git；filesystem 無 yibi-stack checkout | 1. 建 clean env 2. 安裝指定 release tag 3. 檢查 tool metadata | exact Phase A install command + 實際 tag | install exit 0；distribution 為 `yibi-stack`；不需 checkout |
| MYCLI-ST-002 | 驗證三個 console scripts 可啟動 | ST | High | MYCLI-ST-001 已通過 | 1. 執行 `mycelium --help` 2. 執行 `pr-orchestrator --help` 3. 執行 `portman --help` | installed PATH | 三者 exit 0；無 ImportError/AttributeError/checkout lookup |
| MYCLI-ST-003 | 驗證沿用 package 與 wheel boundary | ST | High | 可 build wheel | 1. 讀 metadata 2. 列 wheel files 3. 查 distributions/dependencies | `yibi-stack`、`tasks`、`tasks/**/tests/**` | 只有 `yibi-stack`；含 tasks；不含 tests；core deps 仍只有 Click/Pydantic |
| MYCLI-DT-001 | 缺 mycelium 時六個 skill fail-loud | DT | High | PATH 無 mycelium；六個 SKILL.md 可執行 preflight | 對六個 skill 各觸發一次 preflight | skill 名稱六列 decision table | 每列先印 `[FAIL]` + exact install command、exit non-zero；未執行工作或 fallback |
| MYCLI-ST-004 | 六個 skill 在無 checkout 時走 installed command | ST | High | MYCLI-ST-001 已通過；plugin skills 可見 | 1. `pr-cycle-fast` 進入 pr-orchestrator help/smoke 2. `pr-control-log` 進入 control-log 3. `pr-retrospective` 進入 retro 4. `mycelium` 進入 root group 5. `learn` 進入 lessons 6. `local-port-manager` 進入 portman | 六條 skill-to-command mapping | 六列皆呼叫 installed binary；零 `uv run ... tasks.*`、零 checkout lookup |
| MYCLI-DT-002 | mycelium project-sensitive commands 不靠 cwd | DT | High | fake mycelium capture argv；cwd 設成 unrelated repo | 執行 control-log、retro、lessons、insight、token-usage 代表路徑 | intended project=`target-repo`、cwd=`other-repo` | 每條 argv 含 `--project target-repo`；輸出未採用 `other-repo` |
| MYCLI-DT-003 | pr-orchestrator 明確取得 target checkout | DT | High | fake pr-orchestrator capture argv；兩個 repo paths | 執行 detect 與 auto-fix path | target=`/tmp/target-repo`、cwd=`/tmp/other-repo` | argv 含 `--repo-root /tmp/target-repo`；未使用 cwd |
| MYCLI-DT-004 | portman 明確取得 project | DT | Med | fake portman capture argv | 執行 list/get/suggest/reserve/release path | project=`target-repo` | list 用 `--project target-repo`；其餘命令的 explicit project operand 正確 |
| MYCLI-ST-005 | auto-handover settings 寫入 install-time-resolved binary | ST | High | empty temp settings.json；temp dir 內的 fake `mycelium` 已加入 PATH | 1. 以 `command -v mycelium` 記錄解析路徑 2. install hooks 3. 讀兩個 command 4. 再 install 驗冪等 5. 在另一個 empty settings、PATH 無 mycelium 的 setup 執行 install-hooks | fake HOME；`PATH=<temp-bin>:$PATH` | command 以絕對 `mycelium` 路徑開頭且等於 install 時解析的路徑；不含 checkout、`python -m tasks.mycelium`、uvx；各事件只有一筆；缺 binary 時印 `[FAIL]` 且不寫 unresolved command |
| MYCLI-ST-006 | checkout hook wrapper 不再 in-process import | ST | High | temp dir 內的 fake `mycelium` 已加入 PATH，記錄 stdin/argv/exit | 1. 以 `command -v mycelium` 記錄解析路徑 2. 對 PreCompact 與 SessionStart wrapper 各送 supported payload 3. 以 PATH 無 mycelium 再執行 wrapper | session id + matcher；`PATH=<temp-bin>:$PATH` | wrapper 呼叫 `command -v` 解析到的 binary 與正確 subcommand、保留 observable exit/output；缺 binary 時印 `[FAIL]` 並非零退出；source scan 無 `tasks.mycelium`/uvx/uv run |
| MYCLI-CV-001 | package root 與 26 個 test imports 不漂移 | CV | High | apply edits 完成、cleanup 前後各跑一次 | 1. inventory issue #222 的 26 tests 2. 掃 import 3. 跑 suite | `tasks/mycelium/tests` baseline | imports 仍為 `tasks.mycelium...`；package root 仍是 `tasks/mycelium`；suite 全綠 |
| MYCLI-ORD-001 | 任一 E2E 失敗時禁止 unlink | DT | Critical | 故意讓 fake entry point 的 help exit 1 | 1. 跑 verify gate 2. 嘗試進 cleanup | failing `pr-orchestrator --help` | gate non-zero；六個 symlink 與 consumer resolver lane 全部仍存在 |
| MYCLI-ORD-002 | 全部 E2E 成功後才 cleanup | ST | Critical | MYCLI-ST-001..006、DT-002..004 全 PASS 且 tag 已記錄 | 1. 執行 cleanup 2. 查六 symlink 3. 掃六 consumers 4. 重跑 plugin discovery/smoke | 六個指定 skill | 六 symlink 消失、consumer resolver refs 消失、plugin 仍發現 skill、installed CLI 仍全通過 |
| MYCLI-DOC-001 | README 兩語系呈現 two-track install | ST | Med | README 更新完成 | 讀 English / 繁中 Install sections | plugin commands + exact Phase A CLI command | 兩節都說明 plugin 與 CLI 不同目的，並列 exact tag-pinned command |
| MYCLI-DOC-002 | 不預先文件化 PyPI 或其他 install 變體 | VL | High | README + 六個 SKILL.md 更新完成 | 搜尋 `pip install`、不帶 tag 的 Git install、HEAD install、PyPI 文案，並比對 `[FAIL]` strings | 7 個文件範圍 | 唯一支援字串為 exact Phase A command；無 PyPI command |
| MYCLI-CI-001 | 全 repo regression gate | ST | Critical | 所有 apply task 完成 | 執行 `make ci` | repository tree | exit 0；無 lint/type/security/test regression |

---

## Missing Coverage

所有 in-scope spec scenarios 都已追溯到 planned TC；目前尚未執行，執行結果由 apply phase 填入。PyPI publishing、獨立 package、六個指定 skill 以外的 consumer migration 是明確 Non-Goal，不列為 coverage gap。

---

## Redundant TCs

- MYCLI-ST-002 與 MYCLI-ST-004 都會啟動 CLI，但不重複：前者驗證 distribution entry point，後者驗證 skill-to-command wiring。
- MYCLI-ST-005 與 MYCLI-ST-006 都涉及 hooks，但不重複：前者驗 settings registration，後者驗 runtime delegation 與 observable behavior。
- MYCLI-ORD-001 與 MYCLI-ORD-002 是 migration gate 的 fail/pass 兩側，兩者都保留以防再次違反 ordering。

---

## Traceability Matrix

| US | Scenario slug | TC-ID | pytest docstring / evidence |
|----|--------------|-------|-----------------------------|
| US-001 | `git-install-exposes-all-console-scripts` | MYCLI-ST-001, MYCLI-ST-002 | `spec: mycelium-cli#git-install-exposes-all-console-scripts` |
| US-001 | `distribution-retains-existing-package` | MYCLI-ST-003 | `spec: mycelium-cli#distribution-retains-existing-package` |
| US-002 | `missing-mycelium-fails-before-skill-work` | MYCLI-DT-001 | `spec: mycelium-cli#missing-mycelium-fails-before-skill-work` |
| US-002 | `six-skills-run-without-checkout` | MYCLI-ST-004 | `spec: mycelium-cli#six-skills-run-without-checkout` |
| US-002 | `mycelium-commands-receive-project` | MYCLI-DT-002 | `spec: mycelium-cli#mycelium-commands-receive-project` |
| US-002 | `pr-orchestrator-receives-repo-root` | MYCLI-DT-003 | `spec: mycelium-cli#pr-orchestrator-receives-repo-root` |
| US-002 | `portman-receives-project` | MYCLI-DT-004 | `spec: mycelium-cli#portman-receives-project` |
| US-002 | `settings-hooks-use-stable-binary` | MYCLI-ST-005 | `spec: mycelium-cli#settings-hooks-use-stable-binary` |
| US-002 | `checkout-hook-wrappers-avoid-source-imports` | MYCLI-ST-006 | `spec: mycelium-cli#checkout-hook-wrappers-avoid-source-imports` |
| US-001 | `test-import-paths-remain-stable` | MYCLI-CV-001 | `spec: mycelium-cli#test-import-paths-remain-stable` |
| US-002 | `failed-verification-retains-links` | MYCLI-ORD-001 | `spec: mycelium-cli#failed-verification-retains-links` |
| US-002 | `successful-verification-allows-cleanup` | MYCLI-ORD-002 | `spec: mycelium-cli#successful-verification-allows-cleanup` |
| US-001 | `readme-shows-two-track-install` | MYCLI-DOC-001 | `spec: mycelium-cli#readme-shows-two-track-install` |
| US-001 | `pypi-install-is-not-pre-documented` | MYCLI-DOC-002 | `spec: mycelium-cli#pypi-install-is-not-pre-documented` |
