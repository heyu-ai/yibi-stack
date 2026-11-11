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
| `many-important-one-issue` | △ partial | DT / RB | GDRI-DT-001, GDRI-EG-001, GDRI-VL-001 | 區段級機械層鎖定 Step 10b `每個 PR 至多一張`、`標題必須寫明具體模組與問題症狀`、`既有領域標籤`、`WT_ROOT`／`REVIEW_DIR` 與 Step 5 `## Verified Deferred Important`；執行期建票由 lead 依規執行 |
| `nit-only-no-issue` | △ partial | DT | GDRI-DT-001 | 機械層鎖定 Step 5／Step 5c 未實證與 NIT `禁止建立 GitHub issue` 錨點 |
| `no-demotions-no-issue` | △ partial | DT | GDRI-DT-001 | 機械層鎖定無已實證延後項不建票與 Step 10b 條件錨點 |
| `unverified-or-unreachable-no-issue` | △ partial | DT / RB | GDRI-DT-001, GDRI-EG-001 | 區段級機械層鎖定 Step 5 與 Step 5c 各自的 `## Deferred for lack of evidence` 與 `禁止建立 GitHub issue`（單處移除即轉紅） |
| `small-round2-fix-in-place` | △ partial | DT / RB | GDRI-DT-001, GDRI-EG-001 | 區段級機械層鎖定 Step 5c `單一檔案`、`15 行以內`、`不改變公開介面或 Review Contract`、`通過本地與遠端 CI` |
| `active-spectra-change-routes-to-tasks` | △ partial | DT / RB | GDRI-DT-001, GDRI-EG-001 | 區段級機械層鎖定 Step 5c `寫入該 change 的 \`tasks.md\`` 錨點 |
| `pre-merge-issue-creation-forbidden` | △ partial | DT / RB | GDRI-DT-001, GDRI-DT-002, GDRI-EG-001 | 區段級鎖定 Step 5c `禁止執行 \`gh issue create\`` 且禁出現 `gh issue create --repo`、Step 10b `確認 PR 已 \`MERGED\` 後`，並禁止 circuit breaker 合併前建票措辭 |
| `opaque-deferred-title-forbidden` | ✓ | DT / RB | GDRI-DT-001, GDRI-DT-002, GDRI-EG-001, GDRI-VL-001 | 完全機械化：任一區段錨點單處移除或 `'Deferred from review: PR #'`（含單雙引號、`-t`、散文）出現即轉紅 |

---

## TC Table

| TC-ID | Kind | Seam | Test Purpose | Technique | Risk | Expected Result |
| --- | --- | --- | --- | --- | --- | --- |
| GDRI-DT-001 | auto | `check_convergence_contract` | [mech] 四路延後分流與區段級必要條款缺任一即轉紅 | DT | High | 合成契約移除任一四路錨點或區段條款皆回傳對應 `absent` 錯誤 |
| GDRI-DT-002 | auto | `check_convergence_contract` | [mech] 無語意制式標題（含單引號／短旗標）、合併前建票措辭或 Step 5c 呼叫 `gh issue create --repo` 即轉紅 | DT | High | 注入任一禁用字串或 Step 5c 建票指令皆回傳非空失敗清單 |
| GDRI-EG-001 | auto | `check_convergence_contract` | [mech] 真實 `SKILL.md` 於 Step 5／Step 5c／Step 10b 逐一做單處 `replace(clause, "", 1)` 突變與反向注入皆被殺 | RB | High | 每個區段條款單處移除、Step 5c 注入 `gh issue create --repo` 及單引號舊標題突變皆回傳非空錯誤 |
| GDRI-VL-001 | auto | `check_convergence_contract` | [doc] 真實 `SKILL.md` 通過完整四路分流與區段級契約，且對無語意制式標題突變轉紅 | RB | High | 真實檔案回傳 `[]`，插入舊制式標題則回傳 `forbidden string present` |

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
| Demoted findings have a defined destination | `opaque-deferred-title-forbidden` | GDRI-VL-001 | `spec: pr-review-convergence#opaque-deferred-title-forbidden` / `tc: GDRI-VL-001` |
