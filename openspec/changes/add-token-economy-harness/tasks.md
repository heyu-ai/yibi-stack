# tasks.md — add-token-economy-harness

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。

## Phase 1：Setup

- [x] T001 建立 `tasks/harness_eval/scanners/token_economy.py` 空骨架（import + stub function）
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T002 [P] 在 `tasks/harness_eval/scanners/__init__.py` 匯出 `scan_token_economy`
      — target: `tasks/harness_eval/scanners/__init__.py`

## Phase 2：Core Scanner（P1 — 核心路徑，其他 Story 依賴）

### US-001：always-loaded context 超標警告（P1）

**Story Goal**：always-on proxy 超閾值時 D11 findings 含 WARN + 分數遞減
**Test traceability**: AC-001-1~4 → TE-DT-001, TE-DT-002, TE-DT-003, TE-EG-001
  Verification: `pytest -k "TE_DT_001 or TE_DT_002 or TE_DT_003 or TE_EG_001"`

- [x] T010 [P] [US1] 實作 `_collect_always_on_chars(target_dir)` — 掃描 CLAUDE.md + glob 命中 rules + memory
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T011 [P] [US1] 實作計分邏輯（邊際遞減懲罰，閾值 5000 / 20000 / 25000 / 30000）
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T012 [P] [US1] 確保所有 findings 含 `字元估計（非精準 token 計量）` disclaimer
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T013 [US1] 單元測試 DT-001 / DT-002 / DT-003 / EG-001
      — target: `tasks/harness_eval/tests/test_scanners.py`

## Phase 3：User Stories（P2 → P3）

### US-002：progressive-disclosure 比例（P2）

**Story Goal**：on-demand 比例過低時觸發 WARN
**Test traceability**: AC-002-1~3 → TE-DT-004, TE-DT-005, TE-EG-002
  Verification: `pytest -k "TE_DT_004 or TE_DT_005 or TE_EG_002"`

- [x] T020 [P] [US2] 實作 `_collect_on_demand_chars(target_dir)` — 掃描 skills/ SKILL.md body
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T021 [US2] 計算 ratio 並加入 WARN/OK findings（含數值）
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T022 [US2] 在 extra 暴露 `always_on_chars`, `on_demand_chars`, `total_chars`（list[str]）
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T023 [US2] 單元測試 DT-004 / DT-005 / EG-002
      — target: `tasks/harness_eval/tests/test_scanners.py`

### US-003：CLAUDE.md ↔ rules 冗餘偵測（P2）

**Story Goal**：高詞頻重疊觸發冗餘警告
**Test traceability**: AC-003-1~2 → TE-DT-006, TE-DT-007, TE-EG-003
  Verification: `pytest -k "TE_DT_006 or TE_DT_007 or TE_EG_003"`

- [x] T030 [P] [US3] 實作 `_detect_overlap_words(claude_md_path, rules_dir)` — TF-based 詞頻比對
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T031 [US3] 停用詞過濾（英文 + 中文停用詞列表，硬編碼於 token_economy.py）
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T032 [US3] 重疊詞清單截斷至 ≤ 5 個；寫入 extra["overlap_words"]
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T033 [US3] 單元測試 DT-006 / DT-007 / EG-003
      — target: `tasks/harness_eval/tests/test_scanners.py`

### US-004：effort 相稱性偵測（P2）

**Story Goal**：長 skill 缺 effort frontmatter 時觸發 WARN
**Test traceability**: AC-004-1~3 → TE-DT-008, TE-DT-009, TE-ST-001
  Verification: `pytest -k "TE_DT_008 or TE_DT_009 or TE_ST_001"`

- [x] T040 [P] [US4] 實作 `_check_effort_alignment(skills_dir)` — 掃描 SKILL.md frontmatter + body 長度
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T041 [US4] 寫入 extra["effort_missing_skills"] 清單
      — target: `tasks/harness_eval/scanners/token_economy.py`
- [x] T042 [US4] 單元測試 DT-008 / DT-009
      — target: `tasks/harness_eval/tests/test_scanners.py`

## Phase 4：整合 + SKILL.md 更新

- [x] T050 [P] 在 `service.py` 加入 D11 `_safe_scan(scan_token_economy, target, "D11", "Context / Token Economy", 8)`
      — target: `tasks/harness_eval/service.py`
- [x] T051 整合測試 TE-ST-001（D11 effort WARN 不影響 D4）+ TE-ST-002（run_scan 包含 D11）
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [x] T052 [P] VL 測試 TE-VL-001 + TE-VL-002（score 邊界驗證）
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [x] T053 SMK-001 minimal dir smoke test
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [x] T054 [P] 更新 `skills/harness-eval/SKILL.md`：Step 3 rubric 加入 D11 Context / Token Economy（語意 0–4 分）語意評分子項
      （三子項：always-on 比例、progressive-disclosure 活用、effort 相稱性——對應 design.md「D11 Context / Token Economy（語意 0–4 分）」）
      — target: `skills/harness-eval/SKILL.md`

## Phase 5：Polish & CI

- [x] T060 [P] 補 TE-EG-004 timing test（`time.perf_counter` 驗證 < 0.1s）
      — target: `tasks/harness_eval/tests/test_scanners.py`
- [x] T061 [P] `make ci` 全量通過（ruff + mypy + pytest + pre-commit --all-files）
- [x] T062 對 yibi-stack 自身執行 `harness-eval scan`，確認 D11 findings 出現 always-on WARN
      （3007 行鐵證得到反映）

---

**標記說明**：`[P]` = 可與其他任務平行執行；`[USn]` = 對應 Story；無標記 = 有前序依賴。
