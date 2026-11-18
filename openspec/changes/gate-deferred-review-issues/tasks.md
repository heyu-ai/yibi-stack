# Tasks: gate-deferred-review-issues

- [x] 1.1 更新 `openspec/changes/gate-deferred-review-issues/specs/pr-review-convergence/spec.md`，定義非阻擋項目的四路分流、合併後建票與具名標題契約。
- [x] 1.2 更新 `plugins/dev-cycle/skills/pr-cycle-deep/SKILL.md` 的 Step 5（分離 `## Deferred for lack of evidence` 與 `## Verified Deferred Important`）、Step 5c（四路過濾與單檔 15 行內小修結清、Spectra `tasks.md` 承接、合併前禁建票）及 Step 10b（確認 `MERGED` 後建立具名 issue）。
- [x] 1.3 更新 `plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`（新增 `GDRI-DT-001`、`GDRI-DT-002`、`GDRI-EG-001`、`GDRI-VL-001`、區段級檢查及 `REQUIRED_ANCHORS`／`FORBIDDEN_STRINGS`）並執行 pytest、`check_testplan_trace.py --strict` 與 pre-commit 確認全綠。
