# gate-deferred-review-issues — Test Plan

> trace: enforced
> Source: `openspec/changes/gate-deferred-review-issues/specs/pr-review-convergence/spec.md`
> Mechanical checker: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`

---

## Test Seams

| Seam | Public interface |
| --- | --- |
| `check_convergence_contract` | `check_convergence_contract(text: str) -> list[str]`（`test_convergence_contract.py` 純函式入口） |

---

## Coverage Analysis

| Scenario slug | Covered | Technique | TC-ID(s) | Notes |
| --- | --- | --- | --- | --- |
| `many-important-one-issue` | △ partial | DT / RB | GDRI-DT-001, GDRI-EG-001 | 機械層鎖定 `每個 PR 至多一張`、`## Verified Deferred Important`、`標題必須寫明具體模組與問題症狀`；執行期建票由 lead 依規執行 |
| `nit-only-no-issue` | △ partial | DT | GDRI-DT-001 | 機械層鎖定未實證與 NIT 禁止建票錨點 |
| `no-demotions-no-issue` | △ partial | DT | GDRI-DT-001 | 機械層鎖定無已實證延後項不建票錨點 |
| `unverified-or-unreachable-no-issue` | △ partial | DT | GDRI-DT-001 | 機械層鎖定 `禁止建立 GitHub issue` 與區段分離錨點 |
| `small-round2-fix-in-place` | △ partial | DT | GDRI-DT-001 | 機械層鎖定 `15 行以內` 當場結清不開第 3 輪錨點 |
| `active-spectra-change-routes-to-tasks` | △ partial | DT | GDRI-DT-001 | 機械層鎖定 `寫入該 change 的 \`tasks.md\`` 錨點 |
| `pre-merge-issue-creation-forbidden` | △ partial | DT | GDRI-DT-001, GDRI-DT-002 | 正向鎖定 `確認 PR 已 \`MERGED\` 後`、反向禁止 circuit breaker 同樣建票措辭 |
| `opaque-deferred-title-forbidden` | ✓ | DT / RB | GDRI-DT-001, GDRI-DT-002, GDRI-EG-001, GDRI-VL-001 | 完全機械化：任一四路錨點移除或舊 `--title "Deferred from review: PR #` 出現即轉紅 |

---

## TC Table

| TC-ID | Kind | Seam | Test Purpose | Technique | Risk | Expected Result |
| --- | --- | --- | --- | --- | --- | --- |
| GDRI-DT-001 | auto | `check_convergence_contract` | [mech] 四路延後分流 6 個必要錨點缺任一即轉紅 | DT | High | 逐一移除 6 個新錨點皆回傳含該錨點與 `absent` 的錯誤 |
| GDRI-DT-002 | auto | `check_convergence_contract` | [mech] 舊制式無語意標題與合併前強制建票措辭出現即轉紅 | DT | High | 附加任一禁用字串皆回傳 `forbidden string present` |
| GDRI-EG-001 | auto | `check_convergence_contract` | [mech] 真實 `SKILL.md` 逐一移除四路分流錨點皆被殺 | RB | High | 6 個新錨點於真實檔案逐一突變皆使檢查器回傳非空錯誤 |
| GDRI-VL-001 | auto | `check_convergence_contract` | [doc] 真實 `SKILL.md` 通過完整四路分流契約且對舊標題突變轉紅 | RB | High | 真實檔案回傳 `[]`，插入舊制式標題則回傳 `forbidden string present` |

---

## Manual Verification

（無手動驗證項目，文件契約層全數由 pytest 自動驗證。）

---

## Traceability Matrix

| Requirement | Scenario slug | TC-ID | pytest docstring trace |
| --- | --- | --- | --- |
| Demoted findings have a defined destination | `opaque-deferred-title-forbidden` | GDRI-DT-001 | `spec: pr-review-convergence#opaque-deferred-title-forbidden` / `tc: GDRI-DT-001` |
| Demoted findings have a defined destination | `pre-merge-issue-creation-forbidden` | GDRI-DT-002 | `spec: pr-review-convergence#pre-merge-issue-creation-forbidden` / `tc: GDRI-DT-002` |
| Demoted findings have a defined destination | `many-important-one-issue` | GDRI-EG-001 | `spec: pr-review-convergence#many-important-one-issue` / `tc: GDRI-EG-001` |
| Demoted findings have a defined destination | `unverified-or-unreachable-no-issue` | GDRI-VL-001 | `spec: pr-review-convergence#unverified-or-unreachable-no-issue` / `tc: GDRI-VL-001` |
