# add-mycelium-cli-distribution — Test Plan

> Source: `openspec/changes/add-mycelium-cli-distribution/specs/mycelium-cli/spec.md`
> Phase: A（install-from-git only；PyPI publishing 為 Non-Goal）

---

## Coverage Analysis

### Acceptance Criteria

- 在完全沒有 yibi-stack checkout 的 clean environment，選定並記錄單一具體 immutable release tag，以該 tag 形成的 exact tag-pinned Git command 安裝成功，`mycelium --help` 成功，且六個 skill 的 installed CLI invocation path 全部成功。
- `make ci` fully green。
- README English / 繁體中文 install docs 更新為 plugin 加上 `uv tool install` 的 two-track，且不預先文件化 PyPI。

[MODIFIED] Coverage table 保留 proposal Step 5 的三個 smoke scenario，並將 skill failure coverage 擴為每個實際 invoked console script；正式 US／TC mapping 仍只維護於本檔 Traceability Matrix。

| Scenario slug | Covered | Technique | TC-ID(s) | Notes |
|--------------|---------|-----------|---------|-------|
| `git-install-exposes-all-console-scripts` | ✓ planned | ST | MYCLI-ST-001, MYCLI-ST-002 | clean environment、無 checkout、三個 help |
| `distribution-retains-existing-package` | ✓ planned | ST | MYCLI-ST-003 | wheel metadata/content，不抽 package |
| `missing-mycelium-fails-before-skill-work` | ✓ planned | DT | MYCLI-DT-001 | 六個 skill 依實際 invoked script 參數化；含 mycelium present / pr-orchestrator absent |
| `six-skills-run-without-checkout` | ✓ planned | ST | MYCLI-ST-004 | 六條 invocation matrix |
| `mycelium-commands-receive-project` | ✓ planned | DT | MYCLI-DT-002 | fake binary capture argv |
| `pr-orchestrator-receives-repo-root` | ✓ planned | DT | MYCLI-DT-003 | 沿用現有 `--repo-root` contract |
| `portman-receives-project` | ✓ planned | DT | MYCLI-DT-004 | option / positional 兩種介面 |
| `settings-hooks-use-stable-binary` | ✓ planned | ST | MYCLI-ST-005 | [MODIFIED] install-time 固定絕對路徑、shared matcher ownership、state-file fail-open |
| `checkout-hook-wrappers-avoid-source-imports` | ✓ planned | ST | MYCLI-ST-006 | PATH 上的 fake binary + source scan |
| `test-import-paths-remain-stable` | ✓ planned | CV | MYCLI-CV-001 | 26 個 issue baseline test files |
| `failed-verification-retains-links` | ✓ planned | DT | MYCLI-ORD-001 | gate fail 時禁止 cleanup |
| `successful-verification-allows-cleanup` | ✓ planned | ST | MYCLI-ORD-002 | gate pass 後六 symlink cleanup |
| `readme-shows-two-track-install` | ✓ planned | ST | MYCLI-DOC-001 | English + 繁中 |
| `pypi-install-is-not-pre-documented` | ✓ planned | VL | MYCLI-DOC-002 | README + 六個 gate source scan |
| `smk-install-happy-path` | ✓ planned | SMK | SMK-001 | US-001 release smoke；Git-tag install 到三個 CLI help |
| `smk-missing-binary-gate` | ✓ planned | SMK | SMK-002 | US-002 release smoke；缺 binary 的共同 preflight |
| `smk-hook-registration` | ✓ planned | SMK | SMK-003 | US-002 release smoke；registration-time absolute path |

Legend: ✓ planned = 已有 TC 且待 apply 執行 · △ partial = 僅部分路徑有 TC · ✗ missing = 尚無 TC

---

## TC Table

[MODIFIED] TC table 保留 SMK-001..003，並更新 recorded-tag consistency、required-script preflight 與 shell-safe hook path cases；apply phase 必須將它們轉為 executed。

| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|-------------|-------|-----------|----------------|
| MYCLI-ST-001 | 驗證 Git-tag install 在無 checkout 環境可完成 | ST | High | clean HOME、PATH、uv、git；filesystem 無 yibi-stack checkout | 1. 建 clean env 2. 安裝指定 release tag 3. 檢查 tool metadata | exact Phase A install command + 實際 tag | install exit 0；distribution 為 `yibi-stack`；不需 checkout |
| MYCLI-ST-002 | 驗證三個 console scripts 可啟動 | ST | High | MYCLI-ST-001 已通過 | 1. 執行 `mycelium --help` 2. 執行 `pr-orchestrator --help` 3. 執行 `portman --help` | installed PATH | 三者 exit 0；無 ImportError/AttributeError/checkout lookup |
| MYCLI-ST-003 | 驗證沿用 package 與 wheel boundary | ST | High | 可 build wheel | 1. 讀 metadata 2. 列 wheel files 3. 查 distributions/dependencies | `yibi-stack`、`tasks`、`tasks/**/tests/**` | 只有 `yibi-stack`；含 tasks；不含 tests；core deps 仍只有 Click/Pydantic |
| MYCLI-DT-001 | 缺 required console script 時 skill fail-loud | DT | High | 六個 SKILL.md 可執行 preflight；每列 PATH 缺少 selected path 實際會呼叫的 script | 對六個 skill 各觸發一次 required-script preflight | 下方六列 decision table | 每列先指出缺少的 script、印 `[FAIL]` + exact recorded-tag install command、exit non-zero；未執行工作或 fallback |
| MYCLI-ST-004 | 六個 skill 在無 checkout 時走 installed command | ST | High | MYCLI-ST-001 已通過；plugin skills 可見 | 1. `pr-cycle-fast` 進入 pr-orchestrator help/smoke 2. `pr-control-log` 進入 control-log 3. `pr-retrospective` 進入 retro 4. `mycelium` 進入 root group 5. `learn` 進入 lessons 6. `local-port-manager` 進入 portman | 六條 skill-to-command mapping | 六列皆呼叫 installed binary；零 `uv run ... tasks.*`、零 checkout lookup |
| MYCLI-DT-002 | mycelium project-sensitive commands 不靠 cwd | DT | High | fake mycelium capture argv；cwd 設成 unrelated repo | 執行 control-log `add`、retro、lessons、insight、token-usage 的 project-sensitive 代表路徑；另執行 control-log `stats` / `advice` global aggregate 路徑 | intended project=`target-repo`、cwd=`other-repo` | project-sensitive argv 含 `--project target-repo` 且未採用 `other-repo`；DB-wide global `stats` / `advice` argv 不含 `--project` |
| MYCLI-DT-003 | pr-orchestrator 明確取得 target checkout | DT | High | fake pr-orchestrator capture argv；兩個 repo paths | 執行 detect 與 auto-fix path | target=`/tmp/target-repo`、cwd=`/tmp/other-repo` | argv 含 `--repo-root /tmp/target-repo`；未使用 cwd |
| MYCLI-DT-004 | portman 明確取得 project | DT | Med | fake portman capture argv | 執行 list/get/suggest/reserve/release path | project=`target-repo` | list 用 `--project target-repo`；其餘命令的 explicit project operand 正確 |
| MYCLI-ST-005 | [MODIFIED] auto-handover settings 使用 stable binary，且 hook state/matcher fail-safe | ST | High | empty temp settings.json；名稱含空白的 temp dir 內 fake `mycelium` 已加入 PATH；另備 shared hook entry 與 state-file failure doubles | 1. 以 `command -v mycelium` 記錄解析路徑 2. install hooks 3. 讀兩個 command 4. 以 POSIX shell-word parser 解析 command 5. 再 install 驗冪等 6. PATH 無 mycelium 時執行 install-hooks 7. 更新含 owned + foreign hook 的 shared entry 8. 模擬 unlink race、touch PermissionError 與 malformed JSON | fake HOME；`PATH="<temp root>/bin dir:$PATH"`；fake binary path `/tmp/mycli test/bin dir/mycelium`；custom matcher；best-effort state file | command 以 `shlex.quote` 或等價方式 shell-quote resolved path；shell parsing 後 first argv 等於 install 時解析的 absolute path；不含 checkout、`python -m tasks.mycelium`、uvx；各事件只有一筆；缺 binary 時印 `[FAIL]` 且不寫 unresolved command；shared entry matcher 保持不變；state-file OSError 不逃出且 touch 失敗仍 exit 2；malformed JSON 回 `(0, None)` |
| MYCLI-ST-006 | checkout hook wrapper 不再 in-process import | ST | High | temp dir 內的 fake `mycelium` 已加入 PATH，記錄 stdin/argv/exit | 1. 以 `command -v mycelium` 記錄解析路徑 2. 對 PreCompact 與 SessionStart wrapper 各送 supported payload 3. 以 PATH 無 mycelium 再執行 wrapper | session id + matcher；`PATH=<temp-bin>:$PATH` | wrapper 呼叫 `command -v` 解析到的 binary 與正確 subcommand、保留 observable exit/output；缺 binary 時印 `[FAIL]` 並非零退出；source scan 無 `tasks.mycelium`/uvx/uv run |
| MYCLI-CV-001 | package root 與 26 個 test imports 不漂移 | CV | High | apply edits 完成、cleanup 前後各跑一次 | 1. inventory issue #222 的 26 tests 2. 掃 import 3. 跑 suite | `tasks/mycelium/tests` baseline | imports 仍為 `tasks.mycelium...`；package root 仍是 `tasks/mycelium`；suite 全綠 |
| MYCLI-ORD-001 | 任一 E2E 失敗時禁止 unlink | DT | Critical | 故意讓 fake entry point 的 help exit 1 | 1. 跑 verify gate 2. 嘗試進 cleanup | failing `pr-orchestrator --help` | gate non-zero；六個 symlink 與 consumer resolver lane 全部仍存在 |
| MYCLI-ORD-002 | 全部 E2E 成功後才 cleanup | ST | Critical | MYCLI-ST-001..006、DT-002..004 全 PASS 且 tag 已記錄 | 1. 執行 cleanup 2. 查六 symlink 3. 掃六 consumers 4. 重跑 plugin discovery/smoke | 六個指定 skill | 六 symlink 消失、consumer resolver refs 消失、plugin 仍發現 skill、installed CLI 仍全通過 |
| MYCLI-DOC-001 | README 兩語系呈現 two-track install | ST | Med | README 更新完成；recorded release tag 已保存 | 讀 English / 繁中 Install sections | plugin commands + recorded-tag exact Phase A CLI command | 兩節都說明 plugin 與 CLI 不同目的，並列由 recorded release tag 形成的 exact tag-pinned command |
| MYCLI-DOC-002 | 不預先文件化 PyPI 或其他 install 變體 | VL | High | README + 六個 SKILL.md 更新完成；recorded release tag 已保存 | 搜尋 `pip install`、省略 recorded tag 的 Git install、HEAD install、PyPI 文案，並比對七個文件的 `[FAIL]` / README install strings | 7 個文件範圍 | 七個文件的 supported install string 完全相同且含 recorded release tag；無 PyPI command；assertion 不 hardcode illustrative tag 或 literal placeholder |
| MYCLI-CI-001 | 全 repo regression gate | ST | Critical | 所有 apply task 完成 | 執行 `make ci` | repository tree | exit 0；無 lint/type/security/test regression |
| SMK-001 | 驗證 Git-tag 安裝後三個 CLI 可立即使用 | SMK | High | clean HOME/PATH；uv、git 與 GitHub 可用；filesystem 無 yibi-stack checkout；此 illustrative row 的 recorded immutable tag 為 `v1.11.0` | 1. 以唯一 Phase A command 安裝 illustrative `v1.11.0` 2. 執行 `mycelium --help` 3. 執行 `pr-orchestrator --help` 4. 執行 `portman --help` | illustrative command `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"` | install 與三個 help 皆 exit 0；distribution 為 `yibi-stack`；不查找或 import checkout；apply 時使用實際 recorded release tag |
| SMK-002 | 驗證缺少 required script 時六個 skill 在工作前 fail-loud | SMK | High | plugin cache 可見六個 skill；每列 PATH 缺少 selected path 實際 invoked script | 依序啟動 `pr-cycle-fast`、`pr-control-log`、`pr-retrospective`、`mycelium`、`learn`、`local-port-manager` 的 required-script preflight | MYCLI-DT-001 六列 decision table | 每個 skill 皆先指出缺少的 script、印 `[FAIL]` 與 exact recorded-tag install command、exit non-zero；未嘗試 `SKILL_REPO`、`uv run`、`uvx` 或 `python -m tasks.*` |
| SMK-003 | 驗證 hook registration 固定使用 PATH 解析出的 mycelium | SMK | High | clean HOME；empty `~/.claude/settings.json`；PATH 上的 installed binary 為 `/tmp/mycli-smoke/bin/mycelium` | 1. 記錄 `command -v mycelium` 2. 執行 `mycelium handover install-hooks` 3. 檢查 PreCompact 與 SessionStart command | recorded absolute mycelium path | 兩個 command 經 shell parsing 後的 first argv 均為 `/tmp/mycli-smoke/bin/mycelium` 並使用正確 hook subcommand，resolved path 以 shell-safe 形式寫入；不含 checkout path、`python -m tasks.mycelium` 或 `uvx` |

### MYCLI-DT-001 Decision Rows

[ADDED] 每列只移除 selected skill path 實際會呼叫的 console script；其他同 distribution scripts 可保留，以覆蓋 stale/partial install。

| Row | Skill | PATH setup | Required preflight | Expected result |
|-----|-------|------------|--------------------|-----------------|
| DT-001-A | `pr-cycle-fast` | `mycelium` present；`pr-orchestrator` absent | `command -v pr-orchestrator`；若 selected path 另用 `mycelium` 也檢查它 | 在任何 detect/auto-fix/state work 前指出 `pr-orchestrator`、印 `[FAIL]` 與 exact recorded-tag command、exit non-zero |
| DT-001-B | `pr-control-log` | `mycelium` absent | `command -v mycelium` | 在 control-log work 前 `[FAIL]` |
| DT-001-C | `pr-retrospective` | `mycelium` absent | `command -v mycelium` | 在 retro/lessons/token-usage work 前 `[FAIL]` |
| DT-001-D | `mycelium` | `mycelium` absent | `command -v mycelium` | 在 tasks-backed work 前 `[FAIL]` |
| DT-001-E | `learn` | `mycelium` absent | `command -v mycelium` | 在 lessons/insight work 前 `[FAIL]` |
| DT-001-F | `local-port-manager` | `mycelium` present；`portman` absent | `command -v portman` | 在 list/get/suggest/reserve/release work 前指出 `portman`、印 `[FAIL]` 與 exact recorded-tag command、exit non-zero |

### Smoke ID Exception

[ADDED] 依 spectra-amplifier Step 5 與本 revision 的 host convention decision，smoke tests 使用兩段式 `SMK-NNN`，不改寫為 `MYCLI-SMK-NNN`；所有既有 `MYCLI-*` TC-IDs 保持不變。

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

[MODIFIED] Matrix 保留三個 proposal smoke slugs，並將 MYCLI-CI-001 以 Definition of Done global gate 映射到兩個 US；此表是唯一 traceability source，proposal.md 不重複矩陣。

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
| US-001 | `smk-install-happy-path` | SMK-001 | `proposal smoke: #smk-install-happy-path`; spec anchor: `mycelium-cli#git-install-exposes-all-console-scripts` |
| US-002 | `smk-missing-binary-gate` | SMK-002 | `proposal smoke: #smk-missing-binary-gate`; spec anchor: `mycelium-cli#missing-mycelium-fails-before-skill-work` |
| US-002 | `smk-hook-registration` | SMK-003 | `proposal smoke: #smk-hook-registration`; spec anchor: `mycelium-cli#settings-hooks-use-stable-binary` |
| US-001 | `definition-of-done` | MYCLI-CI-001 | `proposal DoD: #definition-of-done`; global regression gate |
| US-002 | `definition-of-done` | MYCLI-CI-001 | `proposal DoD: #definition-of-done`; global regression gate |
