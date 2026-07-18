<!--
[MODIFIED] by spectra-amplifier: Phase structure, pytest -k trace commands, priority labels
[PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。
-->

## Phase 1：Setup

- [x] 1.1 確認 `AgentsDB` DB path 與 `init_db()` 呼叫位置；新增 `.runtime/control-logs/`
  到 `.gitignore`（artifact-not-committed 規格要求）。
  驗證：`grep "control-logs" .gitignore` 有輸出。

## Phase 2：DB 與 Models（P1 阻斷性前置）

- [x] 2.1 [P] 新增 ControlLogCategory 作為 StrEnum 及相關 Pydantic models：在
  `tasks/mycelium/models.py` 加入 7 值 StrEnum、`ControlLogEntry`、`ControlLogSession`。
  驗證：`pytest -k "CTL-DB-001 or CTL-VL-001"` 通過。

- [x] 2.2 [P] 實作 DB schema（兩個 CREATE TABLE IF NOT EXISTS）遵循使用既有 mycelium DB
  不開新 DB 的設計決策：在 `init_db()` 新增 `control_log_entries`（含 entry schema with
  11 audit fields）及 `control_log_sessions`，加三個索引。
  驗證：`pytest -k "CTL-DB-001 or CTL-DB-002"` 通過；`AgentsDB(':memory:').init_db()`
  兩次無 error。

- [x] 2.3 建立 `tasks/mycelium/tests/test_control_log_db.py`（CTL-DB-001~004）。
  驗證：`pytest tasks/mycelium/tests/test_control_log_db.py -v` 全部通過。

## Phase 3：Service 層（P1）

- [x] 3.1 建立 `tasks/mycelium/control_log_service.py`，實作 entry schema with 11 audit
  fields 規格的 `write_control_log()` 與 `read_control_log(pr_number)`。
  Test traceability: AC-001-2, AC-001-3 → CTL-VL-002, CTL-DB-003
  驗證：`pytest -k "CTL-VL-002 or CTL-VL-003 or CTL-VL-004 or CTL-DB-002 or CTL-DB-003"` 通過。

- [x] 3.2 實作 cross-session statistics computation 規格的 `compute_stats(since_days)`：
  autonomy_ratio 分母設計（autonomous_decision / (autonomous_decision + user_requested=1)），
  division by zero 回傳 `None`。
  Test traceability: AC-003-1, AC-003-3 → CTL-ST-014, CTL-DT-001, CTL-DT-003
  驗證：`pytest -k "CTL-ST-014 or CTL-DT-001 or CTL-DT-003 or CTL-DT-005"` 通過。

- [x] 3.3 實作 threshold-based advice generation 規格的 `generate_advice(since_days)`：
  評估 R1~R4，不足 3 筆 entries 不觸發（AC-004-6），無觸發回傳空清單。
  Test traceability: AC-004-1~6 → CTL-DT-002/004/006/008/010/011
  驗證：`pytest -k "CTL-DT-002 or CTL-DT-004 or CTL-DT-006 or CTL-DT-008 or CTL-DT-010"` 通過。

- [x] 3.4 實作 grouping by category or project 規格的 `compute_grouped_stats(since_days, by)`。
  Test traceability: AC-003-4, AC-003-5 → CTL-ST-015, CTL-ST-016
  驗證：`pytest -k "CTL-ST-015 or CTL-ST-016"` 通過。

- [x] 3.5 建立 `tasks/mycelium/tests/test_control_log_service.py`（CTL-ST-001~016,
  CTL-DT-001~011），使用 `db_path=':memory:'`。
  驗證：`pytest tasks/mycelium/tests/test_control_log_service.py -v` 全部通過。

## Phase 4：CLI 擴充（P1）

- [x] 4.1 在 `tasks/mycelium/cli.py` 新增 CLI interface
  (`uv run python -m tasks.mycelium control-log <subcommand>`) Click group；實作
  `add` subcommand（11 欄位，AC-001-4 輸出 `✓ 已寫入 N 筆 entries`）。
  Test traceability: AC-001-4 → CTL-VL-003, CTL-CV-001
  驗證：`pytest -k "CTL-VL-003 or CTL-CV-001"` 通過；`control-log --help` 顯示 add。

- [x] 4.2 實作 `show` subcommand：列印指定 PR 所有 entries 表格。
  驗證：`pytest -k "CTL-CV-002"` 通過。

- [x] 4.3 實作 `stats` subcommand（cross-session statistics computation + grouping by
  category or project + `--json`，滿足 acceptance criteria）。
  驗證：`pytest -k "CTL-CV-003 or CTL-ST-014"` 通過；`--json` 輸出可 `json.loads()` 解析。

- [x] 4.4 實作 `advice` subcommand（threshold-based advice generation，符合 scope
  boundaries 僅 R1~R4，無觸發印 `目前無建議`）。
  驗證：`pytest -k "CTL-DT-001 or CTL-DT-002"` 通過；空 DB 執行輸出 `目前無建議`。

- [x] 4.5 建立 `tasks/mycelium/tests/test_control_log_cli.py`（CTL-CV-001~003）。
  驗證：`pytest tasks/mycelium/tests/test_control_log_cli.py -v` 通過；`make ci` 通過。

## Phase 5：pr-control-log skill（P1）

- [x] 5.1 建立 `plugins/pr-flow/skills/pr-control-log/scripts/bootstrap.sh`（遵循
  Skill 擺放在 plugins/pr-flow/skills/pr-control-log/ 決策），讀取四個環境變數。
  驗證：在 yibi-stack worktree 中無 error 執行，正確輸出 SKILL_REPO / ORIG_PROJECT /
  REAL_WORKDIR / BRANCH。

- [x] 5.2 建立 detect-pr.sh：`gh pr view` 取得 PR number / title / body。
  驗證：已有 PR 的 branch 上執行後 `PR_NUMBER` 正確設定。

- [x] 5.3 建立 SKILL.md 實作 user calibration loop（AC-002-1~2）與 markdown artifact
  output（11 sections 寫到 `.runtime/control-logs/pr-<N>.md`，不 commit，AC-002-3~4），
  遵循 markdown artifact 輸出到 .runtime/control-logs/ 的設計。
  Test traceability: AC-002-1~4 → CTL-ST-004~009, CTL-ST-010~012
  驗證：SKILL.md 通過 markdownlint-cli2；端對端可驗證 SMK-001 與 SMK-002。

## Phase 6：整合與文件（P2）

- [x] 6.1 修改 pr-retrospective SKILL.md：Q5 actions 加「產生 control log」；
  Step 2 inference 加從 `control_log_entries` 讀 evidence 的提示。
  驗證：人工讀取兩處整合點清楚可執行，無歧義。

- [x] 6.2 更新 `skills/README.md` 索引表，加入 `pr-control-log`。
  驗證：`make install` 安裝 skill 不出 exit 1。

## Phase 7：End-to-End Smoke Tests（P1 依賴 Phase 5）

Test traceability: SMK-001 (`smk-write-and-read`), SMK-002 (`smk-stats-advice`)

- [x] 7.1 SMK-001：對本 PR 執行 `control-log add ... && control-log show --pr N`，
  驗證端對端 write-read 流程。
  驗證：`pytest -k "SMK-001"` 或手動 smoke test，DB 有寫入，show 有輸出。

- [x] 7.2 SMK-002：在至少 3 筆 entries 後執行 `stats --since-days 30 --json && advice`，
  驗證統計與建議流程。
  驗證：`pytest -k "SMK-002"` 或手動，stats JSON 可解析，advice 不出錯。
