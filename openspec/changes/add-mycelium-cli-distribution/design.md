## Context

現況把「安裝 skill」與「取得 Python implementation」綁在 real checkout。六個目標 skill 中，`pr-cycle-fast` 透過 `uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator` 執行（`plugins/pr-flow/skills/pr-cycle-fast/SKILL.md:23-55`）；`pr-control-log` 與 `pr-retrospective` 的 bootstrap 也驗證 checkout 必須含 `tasks/mycelium`（`plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh:27-62`、`plugins/pr-flow/skills/pr-retrospective/scripts/bootstrap.sh:31-66`）。這正是 issue #222 Gap A 要移除的 distribution coupling。

既有 package 不需要重建。`pyproject.toml` 已宣告 `name = "yibi-stack"`、Hatchling、`packages = ["tasks"]`、tests exclusion、Click/Pydantic 核心依賴與 `portman` entry point（`pyproject.toml:1-46`）。`tasks.mycelium.cli:cli` 是 Click group（`tasks/mycelium/cli.py:29-31`），其 `__main__` 也已直接呼叫同一個 `cli`（`tasks/mycelium/__main__.py:1-3`）。

`tasks.pr_orchestrator` 的檢查結果是「可在本 change 一併 expose」，不是 follow-up：`tasks/pr_orchestrator/cli.py:71-73` 定義 Click group，`tasks/pr_orchestrator/__main__.py:1-3` 已有 module entry。它現有的 target-checkout 介面是 `--repo-root`（`tasks/pr_orchestrator/cli.py:79-92`），因此 `pr-cycle-fast` 使用 installed `pr-orchestrator` 後仍以此旗標明確指定 repo，而不是虛構不存在的 `--project`。

## Goals / Non-Goals

**Goals:**

- 讓沒有 yibi-stack checkout 的乾淨環境可從 Git tag 安裝既有 `yibi-stack` wheel，並執行 `mycelium`、`pr-orchestrator` 與 `portman`。
- 讓指定的六個 skill 不再以 checkout import `tasks`，且所有 project-sensitive 操作都有顯式 target。
- 讓 auto-handover hook 在註冊時從 PATH 解析並固定寫入 `mycelium` 的絕對路徑，checkout wrapper 則在執行時以 `command -v mycelium` 解析 binary；兩者都不依賴 checkout 或 `uvx`。
- 以可證明的 end-to-end gate 保護遷移順序：CLI 驗證成功以前不移除 real-checkout symlink 或 resolver 相容路徑。
- 維持 `tasks.mycelium` package root 與既有測試 import path。

**Non-Goals:**

- 不做 PyPI publishing（Phase B），也不在 README 或 skill gate 預告 PyPI 指令。
- 不抽出獨立 `mycelium` distribution，不更名現有 `yibi-stack` package。
- 不增加第三方 dependency，不搬移 `tasks/`，不把 tests 打進 wheel。
- 不遷移六個指定 skill 以外的 tasks-dependent command、nested sub-skill 或其他 repo tooling。
- 不改變 mycelium、pr-orchestrator、portman 的資料模型與業務結果；只改 distribution、invocation、hook boundary 與安全遷移。

## Decisions

### D1 — Reuse the existing yibi-stack package

Phase A 沿用既有 distribution，wheel 繼續只出貨 `tasks` 並排除 tests。理由是 package 骨架與最小依賴已存在（`pyproject.toml:1-46`），另抽 package 只會製造版本、依賴與 import path 的雙重治理。

**Rejected alternatives:**

- 獨立 `mycelium` package：名稱已被 luigi workflow library 使用，且抽離會破壞「26 個測試保留 `tasks.mycelium` import」的硬限制。
- 新的 distribution 名稱：`yibi-stack` 已完成名稱可用性檢查，沒有為 Phase A 再引入命名面的理由。

### D2 — Expose every shipped Click CLI through console scripts

在 `[project.scripts]` 新增 `mycelium = "tasks.mycelium.cli:cli"` 與 `pr-orchestrator = "tasks.pr_orchestrator.cli:cli"`，保留既有 `portman = "tasks.local_port_manager.cli:cli"`。`pr_orchestrator` 已具 Click CLI，因此依 issue #222 決策同 wheel expose，不列 follow-up。`scripts/tests/test_packaging.py:1-17` 已說明 entry point 路徑必須獨立驗證，現有泛用測試會逐一解析所有 console scripts（`scripts/tests/test_packaging.py:66-84`）。

**Rejected alternative:** `pr-cycle-fast` 繼續跑 `python -m tasks.pr_orchestrator`；這會讓六條路徑中仍有一條要求 checkout，無法滿足 clean-environment acceptance criteria。

### D3 — Publish Phase A as a tag-pinned Git install

Apply/verification 先選定並記錄單一具體 immutable release tag；README 與六個 SKILL.md 的 `[FAIL]` gate 只使用由該 recorded release tag 形成的同一條 exact command。以下 `v1.11.0` 僅為 illustrative value，apply 時以實際 recorded release tag 取代：

```bash
uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"
```

具體 tag pin 讓 skill 與 CLI 版本可重現；README 以 plugin 安裝處理 skill/runbook，以 `uv tool install` 處理 Python CLI，形成 two-track install。Documentation assertions 比對 README 與六個 gates 的 command 完全一致，不 hardcode illustrative `v1.11.0` 或任何 placeholder。

**Rejected alternatives:**

- 預先文件化 PyPI：Phase B 尚未交付，提前寫入會提供目前不可用的安裝路徑。
- 省略 tag 或追蹤 HEAD：無法重現已驗證的 wheel 內容，也無法把 verify-before-unlink 證據綁定到確定版本。

### D4 — Make six skill consumers checkout-independent

[MODIFIED]

所有六個 SKILL.md 都先以 `command -v` 檢查 selected path 實際會呼叫的每個 console script；失敗時指出缺少的 script、印 `[FAIL]`、顯示 D3 的 exact recorded-tag 安裝指令並 exit non-zero。呼叫與 preflight 對應如下：

| Skill | Installed command | Required preflight | Explicit target contract |
|------|-------------------|--------------------|--------------------------|
| `pr-cycle-fast` | `pr-orchestrator` | `command -v pr-orchestrator`；若 selected path 也呼叫 `mycelium`，另執行 `command -v mycelium` | `detect` / `auto-fix` 使用既有 `--repo-root "$REPO_ROOT"`；其他 state command 以明確 `--pr` 操作 |
| `pr-control-log` | `mycelium control-log` | `command -v mycelium` | project-sensitive command 傳 `--project "$ORIG_PROJECT"` |
| `pr-retrospective` | `mycelium retro`、`mycelium lessons`、`mycelium token-usage` | `command -v mycelium` | 傳 `--project "$ORIG_PROJECT"`，需要 filesystem scope 時另傳 `--workdir "$REAL_WORKDIR"` |
| `mycelium` | `mycelium` | `command -v mycelium` | project-sensitive read/write 傳 `--project "$ORIG_PROJECT"`；`debug save` 增加 optional `--project`，skill 顯式傳入，省略時沿用推斷；`init`、`migrate` 等 global command 不虛構 project option |
| `learn` | `mycelium lessons`、`mycelium insight` | `command -v mycelium` | 每條 project query 傳 `--project "$PROJECT"`，移除無 project filter 的 cwd fallback |
| `local-port-manager` | `portman` | `command -v portman` | `list` 使用 `--project`；Click 介面以 positional project 表示的 `get` / `suggest` / `reserve` / `release` 保留顯式 project operand |

`pr-control-log` 與 `pr-retrospective` 仍需要各自隨 plugin 出貨的 bootstrap scripts，因此其 resource root 必須依序嘗試三個候選，且每個候選都以「目標 `scripts/bootstrap.sh` 可讀」作能力檢查：(1) `~/.claude/plugins/installed_plugins.json` 中 `pr-flow@yibi-stack` 目前生效 entry 的 `installPath`，(2) `make install` 建立的 `$HOME/.claude/skills/<skill>` symlink，(3) source checkout 的 `plugins/pr-flow/skills/<skill>` repo-relative path。不得以 cache version glob 或只檢查目錄存在取代。三者皆缺少時，skill 必須在工作前印 `[FAIL]`，並同時指引 `claude plugin install pr-flow@yibi-stack` 與在 yibi-stack checkout 執行 `make install` 兩條支援路徑。

`pr-orchestrator` 的明確目標是 checkout path 而非 project slug；其 source contract 已命名 `--repo-root`，刻意維持現有介面。這是 issue #222 要消除 cwd inference 的等價明確化，不把不相容旗標硬塞進既有 CLI。

**Rejected alternative:** 只把 `uv run` 改成裸 `python -m`；module 仍不可從 plugin-only 環境解析，且 cwd footgun 不會消失。

### D5 — Resolve the settings hook binary at registration time

[MODIFIED]

`auto_handover_hooks.install_hooks()` 在 install-hooks 時以 `shutil.which("mycelium")` 或等價的 `command -v` 從目前 PATH 解析並正規化 binary 的絕對路徑。找不到時必須以 `[FAIL]` fail-loud，不寫入無法執行的 settings command；找到後，以 `shlex.quote` 或等價 POSIX-safe encoding shell-quote 該路徑，再寫入 `~/.claude/settings.json` 的 `mycelium hooks pre-compact` 與 `mycelium hooks session-start` command。command 經 shell parsing 後的第一個 argv 必須等於解析出的絕對路徑，解析結果在註冊後保持固定，直到重新安裝 hooks。checkout 內既有 `.claude/hooks/pre-compact-handover.sh` 與 `.claude/hooks/post-compact-handover-back.sh` 則在每次執行時以 `command -v mycelium` 尋找 binary，找不到時以 `[FAIL]` 停止，找到後呼叫該 binary 的相容 wrapper，不再用 inline Python import `tasks.mycelium.metrics_service`（目前 imports 位於 `.claude/hooks/pre-compact-handover.sh:63-112` 與 `.claude/hooks/post-compact-handover-back.sh:42-59`）。

PreCompact 的 `/tmp/claude-handover-suggested-*` 狀態檔只是 best-effort memory，不是 intercept/passthrough 的可用性 gate。mtime read、`unlink(missing_ok=True)` 與 `touch()` 的任何 `OSError` 都不得逃出 hook；無法確認或建立狀態時仍回傳本次 intercept 的 exit 2 與原 system message，已觀察到 fresh state 時則維持 passthrough 決策，即使 cleanup 失敗也不 crash。malformed JSON 仍靜默回傳 `(0, None)`。

`install_hooks()` 更新既有 owned hook command 時，只有該 entry 的 hooks list 恰好只有這一個 owned hook 才可把 matcher 正規化為目前值；若 entry 同時含 foreign hook，必須保留原 matcher，只原地更新 owned hook 的 command/type/timeout，避免擴張或縮小 foreign hook 的觸發範圍。

**Rejected alternatives:**

- 將 binary 固定為 uv 預設 user tool bin 目錄（`~/.local/bin` 下的 `mycelium`）：在自訂 uv tool bin 目錄（例如 `UV_TOOL_BIN_DIR`）時會失效；此外部 review finding 促成本次改為動態解析。
- `uvx`：hook 每次觸發都重新 resolve，延遲與網路／cache 狀態會進入 session lifecycle 的關鍵路徑。
- 由 hook 尋找 checkout 再 import：重建本 change 要移除的 distribution coupling，且 clean environment 必然失敗。

### D6 — Verify first, unlink second

遷移分兩個不可顛倒的 gate。先在六個 repo-root symlink 仍存在、SKILL_REPO 相容邏輯仍保留時，於「無 yibi-stack checkout」環境從 Git tag 安裝並完成三個 console-script help 與六個 skill invocation smoke tests。只有完整證據通過後，才移除 `skills/pr-cycle-fast`、`skills/pr-control-log`、`skills/pr-retrospective`、`skills/mycelium`、`skills/learn`、`skills/local-port-manager` 及六個 consumer 內不再需要的 resolver 邏輯。

**Rejected alternative:** 先 unlink 再測；issue #222 comments 已記錄兩次 field violation，失敗時會同時失去舊路徑與新路徑，無可用 rollback lane。

## Implementation Contract

**Behavior:**

- 在沒有 yibi-stack checkout 的環境執行 D3 安裝指令後，`mycelium --help`、`pr-orchestrator --help`、`portman --help` 都成功。
- 六個 skill 從任意 cwd 觸發時，只依賴 PATH 中已安裝的 CLI；project-sensitive 操作使用 D4 表格的明確 target，不從 CLI process cwd 猜 project。
- selected skill path 缺少任何實際會呼叫的 console script 時，skill 在執行任何工作前指出缺少者、印 `[FAIL]` 與完整 D3 recorded-tag 指令並非零退出。
- `pr-control-log` 與 `pr-retrospective` 的 bootstrap 先依 D4 三候選鏈解析 plugin resource；plugin install 與 checkout `make install` 任一路徑都可工作，三者皆 miss 才 fail-loud。
- auto-handover 在 install-hooks 時從 PATH 解析 `mycelium` 絕對路徑，以 shell-safe 形式固定寫入 hook command；checkout wrapper 在執行時以 `command -v mycelium` 解析 binary。任一解析找不到 binary 都印 `[FAIL]` 並停止；hook event 不 import checkout 中的 `tasks`，也不呼叫 `uvx`。
- PreCompact 狀態檔的 mtime/unlink/touch 錯誤不得中斷 hook；shared settings entry 的 matcher 不得因 owned hook command 升級而被覆寫。

**Interface / data shape:**

- Console scripts：`mycelium -> tasks.mycelium.cli:cli`、`pr-orchestrator -> tasks.pr_orchestrator.cli:cli`、既有 `portman -> tasks.local_port_manager.cli:cli`。
- Skill preflight：`pr-cycle-fast` 對 `pr-orchestrator`（以及 selected path 若有使用的 `mycelium`）、四個 mycelium-backed skills 對 `mycelium`、`local-port-manager` 對 `portman` 執行 `command -v <script> >/dev/null 2>&1`；stderr 訊息指出缺少的 script，並含 `[FAIL]` 與唯一 recorded-tag install command。
- Project target：mycelium 使用 `--project <slug>`；pr-orchestrator 使用 `--repo-root <absolute-checkout-path>`；portman 依既有 Click signature 使用 `--project` 或明確 positional project。
- Settings hook commands：`<shell-quoted-install-time-resolved-absolute-mycelium-path> hooks pre-compact` 與 `<shell-quoted-install-time-resolved-absolute-mycelium-path> hooks session-start`；command 經 shell parsing 後的第一個 argv 必須等於 install-hooks 當下從 PATH 解析到的絕對路徑，寫入後保持固定。兩者從 stdin 讀 Claude hook JSON，保持現有 matcher、session id、system message、exit status 與 best-effort metrics logging 語意。
- Checkout hook wrappers：以 `command -v mycelium` 解析本次執行使用的 binary；解析失敗時印 `[FAIL]` 並非零退出。

**Failure modes:**

- Git install、entry point import 或 `--help` 失敗 → end-to-end gate 失敗；不得移除任何 symlink 或 resolver 相容邏輯。
- skill 找不到 selected path 實際會呼叫的任何 console script → 指出缺少者 + `[FAIL]` + D3 recorded-tag install command + non-zero exit；不得 fallback 到 checkout/cwd inference。
- bootstrap 三候選都無可讀 script → `[FAIL]` 並指引 plugin install 與 checkout `make install`；不得 hard-depend 單一路徑。
- install-hooks 無法從 PATH 解析 `mycelium` → 印 `[FAIL]` 並停止，不得寫入未解析的 hook command。
- PreCompact 狀態檔發生 race、permission 或其他 `OSError` → 保留已做出的 intercept/passthrough 決策並以 warning 降級；不得拋 traceback。
- checkout wrapper 無法以 `command -v mycelium` 找到 binary，或 hook subcommand 失敗 → surfaced as hook command failure；不得以 `uvx` 或 checkout import 靜默 fallback。
- project target 缺失 → skill 在呼叫 CLI 前 fail-loud；不得使用未帶 project filter 的 fallback query。

**Acceptance criteria:**

- clean environment 無 yibi-stack checkout：Git-tag install 成功、`mycelium --help` 成功、六個 skill 的 installed CLI smoke path 全部成功。
- `scripts/tests/test_packaging.py` 驗證全部三個 entry point 可解析為 Click command；mycelium / pr-orchestrator CLI tests 驗證 `--help`、required-script preflight 與 hook subcommands，auto-handover tests 以名稱含空白的 temp directory 內 fake binary 驗證 install-time absolute-path resolution、shell quoting、missing-binary `[FAIL]`、shared matcher preservation、state-file race/permission failure 與 malformed JSON passthrough。
- issue #222 所列 26 個 `tasks/mycelium/tests` import path 維持 `tasks.mycelium...`，package root 未移動。
- README 的 English / 繁中 install 章節都包含 plugin + D3 CLI two-track，且不含 PyPI install command。
- `make ci` exit 0。

**Scope boundaries:**

- In scope：existing package console scripts、六個 SKILL.md 及其必要 bootstrap、auto-handover install-time-resolved binary boundary、ordered symlink/resolver cleanup、README two-track docs、distribution/CLI/hook/clean-install tests。
- Out of scope：PyPI、獨立 package、package root move、新 dependency、六個 skill 以外的 consumer migration、業務功能 redesign。

## Risks / Trade-offs

- **Git tag 與 plugin 版本不一致** → README 明確分開兩條安裝軌，skill preflight 顯示 tag-pinned command；驗證證據記錄實際 tag。
- **自訂 uv tool bin 目錄或註冊時 PATH 缺 binary** → install-hooks 從 PATH 動態解析，因此支援 `UV_TOOL_BIN_DIR` 等自訂位置；若當下找不到 `mycelium` 就以 `[FAIL]` 停止。寫入的絕對路徑保持固定，直到使用者重新安裝 hooks。
- **checkout wrapper 執行時 PATH 缺 binary** → `command -v mycelium` 失敗後以 `[FAIL]` 停止，不 fallback 到 checkout import 或 `uvx`。
- **pr-orchestrator target 與 mycelium project 語意不同** → 保留既有 `--repo-root` path contract，不新增語意模糊的 alias；testplan 分開驗證。
- **提早移除 symlink 造成全面中斷** → D6 gate 是 tasks.md 的硬前序；失敗時 cleanup task 保持未執行。
- **tests 未進 wheel 使 clean-install 缺陷晚發現** → source-tree unit tests 加上獨立 clean-environment system test，分別驗 entry point 與真正安裝結果。

## Migration Plan

1. 在 symlink 與 resolver lane 完整保留時新增兩個 console scripts、install-time-resolved hook commands 與測試。
2. 將六個 skill 切到 installed command，保留舊 resolver 僅作暫時 rollback lane。
3. 以實際 Git tag 在無 checkout 的乾淨環境執行 testplan：三個 CLI help、六個 invocation path、hook command 與 explicit target assertions。
4. Gate 全綠後才移除六個 repo-root symlink 與這六個 consumer 內的 SKILL_REPO / resolver 邏輯；任何一項失敗都停止在此步之前。
5. 更新 README two-track docs，執行 `make ci`，保存 tag 與結果。

Rollback：若第 3 步失敗，保留 symlink/resolver lane 並修復 CLI 後重跑，不執行 cleanup。若 cleanup 後發現 regression，還原六個 symlink 與 consumer resolver path，再重跑同一 end-to-end gate；不以 PyPI 或 `uvx` 當臨時替代。

## Open Questions

(none；本 change 的 package、entry point、安裝指令、六個 consumers、hook resolution 與 migration ordering 均已定案。)
