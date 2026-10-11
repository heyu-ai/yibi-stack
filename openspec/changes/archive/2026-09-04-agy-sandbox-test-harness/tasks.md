## Phase 1: Layer 1 — Permission Flag Contract 靜態測試

**Test traceability**: AC-001-1~3 -> TC AGYS-DT-014~016
  Verification: `uv run pytest plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_agy_scripts.py -k "dt_014 or dt_015 or dt_016" -v`

- [x] 1.1 [P] Implement "Permission flag contract is test-pinned" requirement: 在 `test_agy_scripts.py` 新增 `TestPermissionFlagContract` class，含 `test_agys_dt_014_review_scripts_use_skip_permissions` — parametrize `agy-r1-stage1.sh` 和 `agy-r2.sh`，斷言 agy 呼叫行包含權限繞過旗標且不包含 `--sandbox`。docstring: `spec: agy-sandbox-permission-contract#review-flag-regressed-to-sandbox`。驗證：DT-014 全綠。
- [x] 1.2 [P] 同 class 新增 `test_agys_dt_015_extract_stage_uses_sandbox` — 斷言 `agy-r1-stage2.sh` 的 agy 呼叫行包含 `--sandbox` 且不包含權限繞過旗標。docstring: `spec: agy-sandbox-permission-contract#extract-flag-regressed-to-bypass`。驗證：DT-015 全綠。
- [x] 1.3 [P] 同 class 新增 `test_agys_dt_016_mutual_exclusion` — parametrize 三支腳本，斷言 agy 呼叫行最多出現兩個 flag 之一。docstring: `spec: agy-sandbox-permission-contract#mutual-exclusion-violated`。驗證：DT-016 全綠。
- [x] 1.4 Mutation 驗證：暫改 `agy-r1-stage1.sh` 的 flag -> DT-014 變紅；還原。暫改 `agy-r1-stage2.sh` 的 flag -> DT-015 變紅；還原。兩次 mutation 各自只讓對應測試失敗，還原後全綠。驗證：mutation 前紅後綠。

## Phase 2: Layer 2 — Stub auto-deny 空輸出偵測

**Test traceability**: AC-002-1~2 -> TC AGYS-ST-005~006
  Verification: `uv run pytest plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_agy_scripts.py -k "st_005 or st_006" -v`

- [x] 2.1 在 `test_agy_scripts.py` 新增 `_FAKE_AGY_SANDBOX_DENY` stub script 常數——偵測到 argv 含 `--sandbox` 時：stdout 空、stderr 寫 "no output produced -- a tool required the command permission"、exit 0。驗證：stub 為合法 bash（`bash -n`）。
- [x] 2.2 Implement "Sandbox auto-deny produces detectable failure" requirement: 新增 `TestSandboxAutoDenyDetection` class 的 `test_agys_st_005_stage2_detects_empty_output`——臨時 git repo + precondition files + `_FAKE_AGY_SANDBOX_DENY` stub，執行 `agy-r1-stage2.sh`，斷言 exit non-zero 且 stderr 含 `[FAIL]`。docstring: `spec: agy-sandbox-permission-contract#stub-auto-deny-detected`。驗證：ST-005 全綠。
- [x] 2.3 若 ST-005 揭露 stage2 的現有 guard 不夠（測試失敗），在 `agy-r1-stage2.sh` 補強空輸出 guard（在 `agy_validate.py` 呼叫前加 `[ ! -s "$TMP_JSON" ]` 檢查），使 ST-005 通過。驗證：ST-005 全綠且完整 test suite 無回歸。

## Phase 3: Layer 3 — 版本 probe script + Makefile target

**Test traceability**: AC-003-1~4 -> TC AGYS-VL-001~003, AGYS-EG-001
  Verification: `bash scripts/probe-agy-sandbox.sh`（手動，需 agy auth）

- [x] 3.1 [P] Implement "Version probe script validates sandbox behavior assumptions" requirement: 新增 `scripts/probe-agy-sandbox.sh`——三項 probe：(1) sandbox-file-read；(2) sandbox-command-deny；(3) bypass-full-access。每項印 `[PASS]`/`[FAIL]` + agy 版本。無 auth 時 graceful `[SKIP]`。驗證：`bash -n scripts/probe-agy-sandbox.sh` 語法無誤。
- [x] 3.2 [P] 在 `Makefile` 新增 `probe-agy` target（含 `##` self-documenting 說明）。驗證：`make help` 列出 `probe-agy` 且 `make probe-agy` 可執行。

## Phase 4: 收尾驗證

- [x] 4.1 完整 test suite 回歸——`uv run pytest plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_agy_scripts.py -v` 全通過。驗證：exit 0 + 全 PASSED。(SMK-001)
- [x] 4.2 `make ci` 通過——pre-commit hooks + pytest 全綠。驗證：exit 0。(SMK-002)
