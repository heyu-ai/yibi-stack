# add-pr-review-contract — Test Plan

> Generated for the `add-pr-review-contract` change (extracted from PR #305).
> Source: `openspec/changes/add-pr-review-contract/specs/pr-review-contract/`
> Test convention: host `.claude/rules/09-test-conventions.md`（MODULE 前綴 `PRC`）。`SMK` 冒煙測試前綴
> **非** rule 09 的 category（DT/ST/EG/CV/VL），為沿用前身 `bound-review-loop-with-evidence-gate`
> 的本地 2-part 擴充（`SMK-00N`），僅用於「對真實檔案跑一次」的冒煙層，刻意保留以與前身對齊。
> Mechanical checker: `plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`

---

## 可測性前提（讀 TC 表之前必讀）

pytest 唯一能斷言的表面是 **`pr-cycle-deep/SKILL.md` 這份文件**，以及純函式
`check_convergence_contract(text)`。本 change 的 spec（`pr-review-contract`）**幾乎全部**描述
**aggregator / lead（讀 runbook 的 LLM）在執行期的行為**——contract 凍結、blocking 映射、
human risk 認領、LGTM 判定、conditional R2——這些 **pytest 無法驗證**。因此每個 TC 的
Test Purpose 都帶前綴，讀者不得把 doc-contract 的 PASS 誤讀為行為證明：

| 前綴 | 意義 | 證明了什麼 | 沒證明什麼 |
|------|------|-----------|-----------|
| `[mech]` | 對純函式餵合成 fixture | 檢查器本身正確且會對壞輸入變紅 | — |
| `[doc]` | 對真實 SKILL.md 斷言錨點在場 | runbook **有明文寫**這條規則 | lead 會不會遵守 |

### 本 change 相對前身（`bound-review-loop-with-evidence-gate`）新增了什麼

本 change 只**新增 3 個 parametrized 測試**（`PRC-DT-005/006/007`）與一批新的
`REQUIRED_ANCHORS`（Review Contract 五段標題 + 契約決策錨點）、`FORBIDDEN_STRINGS`
（舊的「全員 LGTM／強制 R2」措辭）。`PRC-VL-*` / `PRC-EG-*` / `PRC-DT-001~004` / `SMK-*`
沿用前身，但因錨點清單擴充，`PRC-DT-001`（齊備通過）與 `PRC-EG-006`（逐一錨點 mutation）
**現在額外覆蓋了新增的契約錨點**——移除任一新錨點會使檢查器變紅。

### Unicode 讀取要求（cf. host rule 13 AP2 unicode handling）

所有錨點比對 **MUST** 以 `Path.read_text(encoding="utf-8")` 讀原始 UTF-8（此為 Python 層讀取慣例；
rule 13 AP2 講的是 bash 層 command-string 的 unicode 折疊，同一「shell 會弄壞 unicode」家族但非同一條）。錨點含
`每個 PR 至多一張` 等全形／CJK 字元；用 shell `echo` 轉換或 ASCII 替代會**靜默不匹配**、
不報錯，導致整批檢查 no-op。

---

## Coverage Analysis

> `Covered` 欄刻意不叫 `Status`——本表是給人讀的覆蓋摘要，非 amplifier 的機械 coverage gate。

| Scenario slug | Covered | Technique | TC-ID(s) | Notes |
|--------------|---------|-----------|---------|-------|
| `complete-contract-starts-review` | △ partial | DT | PRC-DT-005 | 錨點在場（五段標題）為機械層；「凍結後啟動 R1」為執行期行為，不可測 |
| `missing-contract-section-blocks-reviewer-launch` | ✓ | DT / RB | PRC-DT-005, PRC-EG-006 | 移除任一標題錨點使檢查器變紅。**真實檔案** coverage 來自 EG-006（對真實 SKILL.md mutation）與 SMK-001；DT-005 為 `[mech]`，只對合成 fixture 斷言 |
| `acceptance-criterion-violation-can-block` | △ partial | DT | PRC-DT-006 | `Contract mapping:` 錨點在場為機械層；映射到 AC 後 blocking 為執行期行為 |
| `missing-mapping-is-non-blocking` | △ partial | DT | PRC-DT-006 | `blocking set is the sole LGTM gate` 錨點在場為機械層；實際降級為執行期行為 |
| `repository-baseline-remains-enforceable` | △ partial | DT | PRC-DT-006 | doc 層；baseline 不可被 contract 豁免屬 lead 判斷 |
| `non-goal-suggestion-is-deferred` | △ partial | DT | PRC-DT-006 | doc 層；scope 內建議 non-blocking 屬執行期 |
| `follow-up-does-not-block` | △ partial | DT | PRC-DT-006 | doc 層；同上 |
| `risk-inside-accepted-boundary-is-non-blocking` | △ partial | DT / RB | PRC-DT-006, PRC-EG-006 | 五個 residual-risk 欄位 label（Failure mode/impact、Accepted boundary、Mitigation、Detection/recovery、Accepted by）**現皆為 REQUIRED_ANCHORS，機械層守住 label 在場**；「風險落在 boundary 內即 non-blocking」的認領判斷仍為執行期 |
| `missing-acceptor-leaves-risk-unaccepted` | △ partial | DT / RB | PRC-DT-006, PRC-EG-006 | `Accepted by:` 等五欄 label 機械層守住；「缺 acceptor 視為未接受」的判斷為執行期 |
| `non-blocking-needs-changes-does-not-veto-merge` | △ partial | DT | PRC-DT-006 | `blocking set is the sole LGTM gate` 錨點在場為機械層；raw verdict 無否決權屬執行期 |
| `blocking-set-prevents-lgtm` | △ partial | DT | PRC-DT-006 | doc 層；同上 |
| `clean-round-1-skips-cross-debate` | △ partial | DT | PRC-DT-006 | `R2 skipped: no contract-blocking candidate or dispute` 字串在場為機械層；「skip Step 4、直接 aggregate」的執行期半為 doc-only |
| `candidate-blocker-activates-cross-debate` | △ partial | DT | PRC-DT-006 | conditional-R2 錨點在場為機械層；實際啟動為執行期 |
| `blocking-disagreement-activates-cross-debate` | △ partial | DT | PRC-DT-006 | doc 層；同上 |
| `material-amendment-restarts-review` | △ partial | DT | PRC-DT-006 | `material amendment` 字串在場為機械層；「restart full-diff R1」的執行期半為 doc-only |
| `editorial-correction-keeps-current-pass` | △ partial | DT | PRC-DT-006 | `editorial amendment` 字串在場為機械層；「keep current pass」的執行期半為 doc-only |
| `required-heading-mutation-fails` | ✓ | DT / RB | PRC-DT-005, PRC-EG-006 | 完全機械化。真實檔案 coverage 由 EG-006 提供；DT-005 為合成 fixture |
| `unanimous-wording-mutation-fails` | ✓ | DT | PRC-DT-007 | 完全機械化：5 個已知語意變體（含 CJK）任一出現即變紅 |
| `conditional-r2-mutation-fails` | ✓ | DT | PRC-DT-006 | 完全機械化：7 個契約決策錨點任一缺失即變紅 |

Legend: ✓ covered · △ partial · ✗ missing

**partial 列的共同缺口（只講一次）**：全部描述 aggregator / lead 的執行期行為。pytest 能證明
runbook **有規定**（doc-contract），但**不能證明 agent 在任意未來 PR 上會遵守**。此殘餘以
pytest **不可消除**——要收斂需 golden-transcript eval harness（見 Missing Coverage）。

---

## TC Table

> TC Table 無 `Scenario Slug` 欄（沿用前身慣例）；slug↔TC 對照見下方 Traceability Matrix。

| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|-------------|-------|-----------|----------------|
| PRC-DT-005 | [mech] Review Contract 五段標題缺任一 → 檢查器變紅（對合成 fixture，非真實檔案；真實檔案由 EG-006/SMK-001 兜底） | DT | High | 純函式（`_fixture(900)` 合成字串，不讀真實 SKILL.md） | parametrize 6 個標題，各自從 fixture 移除後呼叫檢查器 | `## Review Contract`、`### Goal`、`### Non-goals`、`### Accepted Residual Risks`、`### Acceptance Criteria`、`### Follow-ups` | 每個標題移除後，失敗訊息含該標題與 `absent`；絕不 `[]` |
| PRC-DT-006 | [mech] 契約決策錨點缺任一 → 檢查器變紅（**跨 5 個 requirement**：見 Traceability Matrix 逐錨點對照） | DT | High | 純函式（合成 fixture，不讀真實檔案） | parametrize 7 個錨點，各自移除後呼叫 | `frozen Review Contract`、`Contract mapping:`、`Accepted by:`、`blocking set is the sole LGTM gate`、`R2 skipped: no contract-blocking candidate or dispute`、`material amendment`、`editorial amendment` | 每個錨點移除後失敗並指名 + `absent` |
| PRC-DT-007 | [mech] 舊「全員 LGTM／強制 R2」措辭出現 → 變紅 | DT | High | 純函式 | parametrize 5 個已知語意變體，各自附加到 fixture 後呼叫 | `全員 LGTM（含 actionable NIT）`、`all voices LGTM`、`All voices LGTM`、`Every active voice's latest round outputs …`、`Want to skip R2 and run only R1 \| Not allowed` | 每個變體都觸發 `forbidden string present` |
| PRC-DT-001 | [mech] 必要錨點齊備（含新增契約錨點）→ 通過 | DT | High | 純函式 | 構造含全部必要錨點、無禁字、在預算內的 fixture | 全部 `REQUIRED_ANCHORS` | 回傳 `[]` |
| PRC-DT-002 | [mech] 必要錨點缺失 → 大聲失敗，絕不「沒東西可查」 | DT | High | 純函式 | 從 fixture 移除 `baseline..HEAD`；呼叫 | 移除該錨點 | 失敗訊息含缺失錨點與 `absent`；不得為 `[]`、不得 skip |
| PRC-EG-006 | [mech] 對每個必要錨點做 mutation（含新增契約錨點，guard 須有能力變紅） | RB | High | 真實 SKILL.md + 純函式 | 每個必要錨點：複製真實文字、只刪該錨點、斷言檢查器現在指名它；先斷言錨點確實在場（stale 則大聲失敗） | N 個必要錨點 | N/N 突變體被殺；存活 = 該錨點實際未被檢查 |
| PRC-VL-001 | [mech] 行數預算上界（1220）接受 | BVA | Med | 純函式 | 構造正好 1220 行、錨點齊備 | 1220 行 | 回傳 `[]` |
| PRC-VL-002 | [mech] 行數預算 +1（1221）拒絕，訊息含實際值與預算 | BVA | Med | 純函式 | 構造 1221 行、錨點齊備 | 1221 行 | 非空失敗；恰有一則同時含 `1221` 與 `1220` |
| SMK-001 | [mech] 契約測試套件對真實 SKILL.md 通過 | RB | High | repo 已 checkout | 跑 `test_convergence_contract.py` | 真實檔案 | exit 0；測試有被收集 |
| SMK-002 | [mech] 真實 SKILL.md 行數被回報且在預算內 | RB | High | repo 已 checkout | 以 `-s` 跑行數測試，讀回報數字 | 真實檔案 | 回報數 ≤ 1220，且印給操作者看 |

---

## Missing Coverage

19 個 scenario slug **無一完全未覆蓋**——每個至少有一個 doc-contract 或機械 TC。但下列
**執行期義務**目前僅由 doc 層釘住，pytest 不可證：

- **contract 凍結後才啟動 R1、material amendment 重啟 full-diff R1**——`PRC-DT-005/006`（`[mech]`，
  對合成 fixture）與 `PRC-EG-006`（對真實檔案 mutation）只證**錨點字串在場於 runbook**，無法證
  lead 真的凍結／重啟。執行期半屬 doc-only。
- **blocking 映射到 AC / repo baseline / 未接受風險的實際分類**、**human risk 認領**、
  **conditional R2 的實際啟動與否**——全部為 aggregator / lead 執行期行為。

**建議**：新增 `tests/fixtures/transcripts/` golden-eval harness（種入 review payload →
期望的 contract-compliance 判定），以 `[manual]`／nightly gate 執行，而非放進 pre-commit。
在它存在之前，testplan **必須明講**：契約測試套件全綠只證明**文件符合性**，不證明
agent 遵守。

---

## Redundant TCs

| TC-ID | 與哪個重複 | 建議動作 |
|-------|-----------|---------|
| PRC-DT-006 的 `conditional-r2` 錨點 | PRC-DT-007 的 forbidden 措辭 | 兩者從相反方向鎖同一條 R2 規則（一個要求新錨點在場、一個要求舊措辭缺席），皆保留：正反雙鎖正是重點 |

---

## Traceability Matrix

三個帶 `spec:` docstring trace 的 TC（amplifier 傳性鉤子）：

| Requirement | Scenario slug | TC-ID | pytest docstring `spec:` trace |
|----|--------------|-------|-----------------|
| Deep review requires a confirmed Review Contract | `missing-contract-section-blocks-reviewer-launch` | PRC-DT-005 | `spec: pr-review-contract#missing-contract-section-blocks-reviewer-launch` |
| Cross-debate Round 2 is conditional | `conditional-r2-mutation-fails` | PRC-DT-006 | `spec: pr-review-contract#conditional-r2-mutation-fails` |
| Mechanical conformance checks protect the Review Contract | `unanimous-wording-mutation-fails` | PRC-DT-007 | `spec: pr-review-contract#unanimous-wording-mutation-fails` |

**PRC-DT-006 逐錨點 → requirement 對照**（DT-006 parametrize 7 錨點，跨 5 個 requirement；docstring 只帶
單一 `conditional-r2-mutation-fails` trace 作為 amplifier 鉤子，以下列出實際覆蓋以免被隱藏）：

- `frozen Review Contract` → Deep review requires a confirmed Review Contract
- `Contract mapping:` → Blocking findings map to a closed set
- `Accepted by:`（＋4 欄位 label，真實檔案由 PRC-EG-006 兜底）→ Residual-risk acceptance belongs to a human
- `blocking set is the sole LGTM gate` → LGTM depends on contract compliance and the blocking set
- `R2 skipped: no contract-blocking candidate or dispute` → Cross-debate Round 2 is conditional
- `material amendment` / `editorial amendment` → Contract amendments preserve review integrity
- （另 PRC-EG-006 對每個錨點於真實檔案 mutation，覆蓋 `required-heading-mutation-fails`，屬機械層無 per-scenario trace）
