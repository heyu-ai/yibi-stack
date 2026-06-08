# tasks.md — add-task-demand-normalization

## Phase 1：Setup

- [ ] T001 在 `tasks/harness_eval/models.py` 為 `ScanOutput` 加 `d_repo: float = 1.0` 與
      `size_adjusted_score: float = 0.0`
      — target: `tasks/harness_eval/models.py`

## Phase 2：Core（P1）

### US-002：D_repo 反映 repo 複雜度（P1，其他 Story 依賴）

**Story Goal**：由複雜度訊號算出 ≥1 的單調 D_repo，並暴露組成
**Test traceability**: AC-002-1~3 → TDN-DT-004, TDN-DT-005, TDN-DT-006
  Verification: `pytest -k "TDN_DT_004 or TDN_DT_005 or TDN_DT_006"`

- [ ] T010 [P] [US2] 實作 `_count_source_loc` / `_count_skills` / `_count_hooks` / `_count_rules`
      — target: `tasks/harness_eval/service.py`
- [ ] T011 [US2] 實作 `_compute_d_repo`（log 縮放，保證 ≥ 1.0），回傳 (float, components)
      — target: `tasks/harness_eval/service.py`
- [ ] T012 [US2] 將 `d_repo_components` 寫入 ScanOutput 的 extra/對應欄位
      — target: `tasks/harness_eval/service.py`
- [ ] T013 [US2] 單元測試 TDN-DT-004 / TDN-DT-005 / TDN-DT-006
      — target: `tasks/harness_eval/tests/test_scanners.py`

### US-001：掃描輸出包含規模調整分數（P1）

**Story Goal**：ScanOutput 帶 size_adjusted_score 並標 provisional
**Test traceability**: AC-001-1~3 → TDN-DT-001, TDN-DT-002, TDN-DT-003
  Verification: `pytest -k "TDN_DT_001 or TDN_DT_002 or TDN_DT_003"`

- [ ] T020 [US1] 在 `run_scan()` 末段計算 `size_adjusted_score = round(total / d_repo, 1)`
      並寫入 ScanOutput
      — target: `tasks/harness_eval/service.py`
- [ ] T021 [US1] `cli.py` text 輸出顯示 raw 分 + size_adjusted + `provisional（未校準，見 #143）`
      — target: `tasks/harness_eval/cli.py`
- [ ] T022 [US1] 單元測試 TDN-DT-001 / TDN-DT-002 / TDN-DT-003
      — target: `tasks/harness_eval/tests/test_scanners.py`

## Phase 3：US-003 跨 repo 比較（P2）

**Story Goal**：規模膨脹被抵銷，跨 repo 差距縮小
**Test traceability**: AC-003-1~2 → TDN-DT-007, TDN-DT-008
  Verification: `pytest -k "TDN_DT_007 or TDN_DT_008"`

- [ ] T030 [US3] 單元測試 TDN-DT-007（大 repo size_adjusted 差距 < raw 差距）
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [ ] T031 [US3] 單元測試 TDN-DT-008（d_repo 確定性）
      — target: `tasks/harness_eval/tests/test_scanners.py`

## Phase 4：文件 + CI

- [ ] T040 [P] 更新 `skills/harness-eval/SKILL.md` 報告格式段落，說明 size_adjusted_score
      與其 provisional 性質（rule 11：spec 與 SKILL.md guard 同步）
      — target: `skills/harness-eval/SKILL.md`
- [ ] T041 SMK-001 / SMK-002 / SMK-003 冒煙測試
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [ ] T042 `make ci` 全量通過（ruff + mypy + pytest + pre-commit --all-files）

---

**標記說明**：`[P]` = 可平行；`[USn]` = 對應 Story；無標記 = 有前序依賴。
