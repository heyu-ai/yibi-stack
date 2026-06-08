# tasks.md — add-harness-eval-validation-protocol

> 前置依賴：#140（trace/EFC）、#142（outcome labels）僅影響「真實資料 wiring」（T050），
> 邏輯層（freeze / metric / holdout / guard）可立即實作並以 fixture 驗證。

## Phase 1：Setup（rule 04 module 結構）

- [ ] T001 建立 `tasks/harness_eval/validation/` 套件骨架：`__init__.py`、`__main__.py`
      — target: `tasks/harness_eval/validation/__init__.py`, `__main__.py`
- [ ] T002 [P] `models.py` 定義 `ProtocolSnapshot` / `DataPoint` / `MetricResult`
      — target: `tasks/harness_eval/validation/models.py`

## Phase 2：Core（P1）

### US-001：凍結協定快照（P1，guard 依賴）

**Story Goal**：freeze 產生含確定性 hash 的 snapshot
**Test traceability**: AC-001-1~3 → VAL-DT-001, VAL-DT-002, VAL-DT-003
  Verification: `pytest -k "VAL_DT_001 or VAL_DT_002 or VAL_DT_003"`

- [ ] T010 [P] [US1] 實作 `_compute_protocol_hash` 與 `freeze` service
      — target: `tasks/harness_eval/validation/service.py`
- [ ] T011 [US1] `freeze` 子命令寫出 snapshot（記錄權重、d_repo_scale、metric 定義）
      — target: `tasks/harness_eval/validation/cli.py`
- [ ] T012 [US1] 單元測試 VAL-DT-001 / VAL-DT-002 / VAL-DT-003
      — target: `tasks/harness_eval/validation/tests/test_validation.py`

### US-004：未凍結時拒絕評估（P1，反 post-hoc guard）

**Story Goal**：無 snapshot 時 score/holdout 拒絕
**Test traceability**: AC-004-1~2 → VAL-DT-009, VAL-DT-010
  Verification: `pytest -k "VAL_DT_009 or VAL_DT_010"`

- [ ] T020 [US4] 實作 `_require_frozen_protocol`（無 snapshot 或 hash 不符 → RuntimeError）
      — target: `tasks/harness_eval/validation/service.py`
- [ ] T021 [US4] `score`/`holdout` 進入點先呼叫 guard；非零 exit + 提示 freeze
      — target: `tasks/harness_eval/validation/cli.py`
- [ ] T022 [US4] 單元測試 VAL-DT-009 / VAL-DT-010
      — target: `tasks/harness_eval/validation/tests/test_validation.py`

### US-002：計算 R²/MAE（P1）

**Story Goal**：對資料集回傳 R²/MAE 並標 protocol_hash
**Test traceability**: AC-002-1~3 → VAL-DT-004, VAL-DT-005, VAL-DT-006
  Verification: `pytest -k "VAL_DT_004 or VAL_DT_005 or VAL_DT_006"`

- [ ] T030 [P] [US2] 實作 `_r_squared` / `_mae`（純 stdlib 或輕量 numpy）
      — target: `tasks/harness_eval/validation/service.py`
- [ ] T031 [US2] 實作 CSV/JSONL ingest（malformed 行 skip，`# nosec B112`）
      — target: `tasks/harness_eval/validation/service.py`
- [ ] T032 [US2] `score` 子命令串接 ingest + guard + compute_metrics
      — target: `tasks/harness_eval/validation/cli.py`
- [ ] T033 [US2] 單元測試 VAL-DT-004 / VAL-DT-005 / VAL-DT-006（含完美線性 fixture）
      — target: `tasks/harness_eval/validation/tests/test_validation.py`

## Phase 3：US-003 holdout（P2）

**Story Goal**：只在 holdout 批次計算，空批次報錯
**Test traceability**: AC-003-1~3 → VAL-DT-007, VAL-DT-008, VAL-EG-001
  Verification: `pytest -k "VAL_DT_007 or VAL_DT_008 or VAL_EG_001"`

- [ ] T040 [US3] `compute_metrics` 支援 `holdout_batch` 過濾；空批次 raise ValueError
      — target: `tasks/harness_eval/validation/service.py`
- [ ] T041 [US3] `holdout` 子命令；報告含 batch id 與樣本數
      — target: `tasks/harness_eval/validation/cli.py`
- [ ] T042 [US3] 單元測試 VAL-DT-007 / VAL-DT-008 / VAL-EG-001
      — target: `tasks/harness_eval/validation/tests/test_validation.py`

## Phase 4：真實資料 wiring（blocked-on #140 / #142）

- [ ] T050 [BLOCKED:#140,#142] 把 trace/EFC 分數與 outcome labels 匯出成本模組的 dataset 格式
      — target: 待前置 issue 完成後定義

## Phase 5：文件 + CI

- [ ] T060 [P] 確認三子命令出現在 `--help`（rule 08 dead-code trap）
      `uv run python -m tasks.harness_eval.validation --help`
- [ ] T061 [P] 更新 `skills/harness-eval/SKILL.md` 新增驗證協定使用段落
      （rule 11：spec 與 SKILL.md guard 同步）
      — target: `skills/harness-eval/SKILL.md`
- [ ] T062 SMK-001 / SMK-002 / SMK-003 冒煙測試
      — target: `tasks/harness_eval/validation/tests/test_validation.py`
- [ ] T063 `make ci` 全量通過（ruff + mypy + pytest + pre-commit --all-files）

---

**標記說明**：`[P]` = 可平行；`[USn]` = 對應 Story；`[BLOCKED:#n]` = 待該 issue 完成；
無標記 = 有前序依賴。
