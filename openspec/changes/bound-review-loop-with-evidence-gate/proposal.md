## Why

`/pr-cycle-deep` 的 fix → re-review 迴圈在結構上不保證收斂，實際使用時反覆跑多輪才勉強結束，且 review 意見越來越難以理解。三個症狀源自同一個設計缺陷：**迴圈裡的每個累積器都只有入口，沒有預設出口**。

三項可量測的證據：

1. **NIT 是 blocking**。SKILL.md 的 severity 章節寫明「this skill's convention cleans up every actionable NIT before merge」，把過關門檻釘死在最低嚴重度。
2. **審查面每輪不減反增**。Step 7 每輪讓所有 voice 重跑 R1 檢查完整 diff，而 fix 本身就是新程式碼——新的可審面積。迴圈的不動點條件變成「每輪 fix 產生的新 blocking finding < 1 個」，這在無限可生成的 NIT 面前不成立。
3. **沒有輪數上限**。只有 circuit breaker，且要「連續 3 輪未達成全員 LGTM」才觸發。

第 2 點在本 repo 特別致命：統計 2026-06-01 以來的 commit，被改最多的目錄是 `.claude/rules`（33 次）與 pr-cycle-deep 自己的 scripts（21 次）。**這個 repo 的 PR 大多在改「規則」與「review 工具本身」**，也就是說 reviewer 多數時候在審一份描述邊界情況的散文。對散文而言，Critical（logic error / security / data loss）幾乎不可能成立，於是所有 finding 擠向 Important 與 NIT；而「精確度不足」沒有下界——永遠可以再挑一句話說它過度概括、少一個 counter-example、residual note 過期。

同一份 SKILL.md 從 2026-05-10 誕生至今 55 次修改、732 行成長到 1220 行，其中**只有 1 次是真正的簡化**（#135）。這個 change 要修的正是產生該曲線的機制。

## What Changes

1. **證據閘門**：blocking finding 必須附該類型所要求的證據；提不出者降級為非 blocking，但保留原標題／描述／降級理由。
2. **證據形式封閉列舉**：logic/security 收「具體 failure scenario」而非可跑指令（reviewer 只看得到 diff）；「精確度／可能誤導」類無可接受形式，恆降級。
3. **三種執行結果**：重現／未重現／**無效**。「證據跑不起來」不等於「缺陷不存在」，前者降級保留，絕不 drop。
4. **輪數上限**：至多 2 輪，不存在 Round 3。終止由輪數上限無條件保證。
5. **審查面縮限**：Round 2 只審 `baseline..HEAD` 的 fix delta，降低 finding 生成量與成本。
6. **雙軌降級出口**：Important → 每 PR 至多一張 `deferred-from-review` issue；NIT → 留在既有 PR comment，不開票。
7. **BREAKING（對 skill 行為）**：Actionable NIT 不再 blocking。刪除「every actionable NIT before merge」的約定句。
8. **契約檢查器**：以純函式 `check_convergence_contract(text)` 暴露，使負向測試可行。
9. **行數預算**：改動後 SKILL.md 行數必須 ≤ 1220（現況），以機械檢查強制。

## Step 1 — User Stories

> **五尺度自我檢查結果**：本 change 的每個子部分獨立看都是**微尺度**（≤ 4 小時），按規則應「合併或降為 Scenario」。因此「行數預算」不列為 US（它是 DoD，歸 Step 5），最終收斂為 3 個 US，各 4-6 小時、AC 皆 ≤ 7 條、各自單一 Actor 群與單一 Goal。

### US-001：blocking 主張必須可複驗

**Persona**：review voice（codex / agy / claude）與 lead。voice 以 read-only sandbox 執行、被明文禁止探索 repo，只看得到 diff；lead 是唯一擁有 repo 知識、能實際執行指令的角色。
**Action**：voice 對每筆 finding 附上該類型所要求的證據；lead 依證據判定處置。
**Outcome**：擋 merge 的每個理由都能被一條指令複驗，而非只能閱讀論述；提不出證據的意見仍被記錄，但不再擋人。

**Acceptance Criteria**：

- AC-001-1：blocking finding 必須附有效 `Evidence:`；無有效證據者降級為 deferred，且原標題、描述、降級理由逐字保留，不得消失。
- AC-001-2：證據形式依 finding 類型**封閉列舉**；logic/security 收「具體 failure scenario（輸入／預期輸出／實際輸出）」而非可跑指令；「精確度／可能誤導／建議補充」類無可接受形式，恆降級；表中不得有 catch-all 列。
- AC-001-3：驗證成本分層——證據欄位缺漏或格式不符者以結構檢查降級、**不執行任何指令**；Critical 的證據 lead 必驗；Important 選擇性抽驗。
- AC-001-4：執行結果必分三類：重現／未重現／**無效**。無效（指令根本跑不起來）須先嘗試修復一次，修不好則降為 Important 進 deferred，**不得 drop**，**不得記為未重現**。

### US-002：迴圈在有限輪數內離開

**Persona**：PR 作者與 lead。現況要跑很多輪才勉強結束，離開靠的是使用者疲勞而非規則。
**Action**：跑 `/pr-cycle-deep` 完整生命週期。
**Outcome**：迴圈必在 2 輪內離開，出口是 merge 或人類裁決；不存在「再跑一輪看看」的狀態。

**Acceptance Criteria**：

- AC-002-1：迴圈至多 2 輪。Round 1 審完整 diff 並**記錄** baseline head SHA；Round 2 審 `baseline..HEAD` 且僅 Critical 可 blocking；不存在 Round 3。
- AC-002-2：終止僅依賴輪數上限，**不依賴** Round 2 審查面小於 Round 1（兩者為不相交 commit range，非子集，大小無保證）；文件不得含以審查面縮小為終止條件的措辭。
- AC-002-3：Actionable NIT 任何輪次皆不 blocking；SKILL.md 不得含「每個 actionable NIT 都要在 merge 前清掉」的約定句。
- AC-002-4：Round 2 結束仍有未解 Critical → 進入既有 circuit breaker 三選項交人類裁決，不得自動進入第 3 輪。

### US-003：降級的意見有明確去處

**Persona**：維護者。擔心「降級」實質等於「遺失」，也擔心用製造新累積器的方式解決舊累積器。
**Action**：review 迴圈結束後檢視降級清單的去向。
**Outcome**：每筆 finding 都有去處且不重複堆積；issue 流量可控。

**Acceptance Criteria**：

- AC-003-1：降級的 Important → 每個 PR **至多一張**標記 `deferred-from-review` 的批次 issue；降級的 NIT 不開票，倚賴既有的 PR review comment；無降級 Important 時不建立 issue。
- AC-003-2：`plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 行數 ≤ 1220；機械檢查以**字串內容**為錨點而非行號；錨點找不到時必須 `[FAIL]` 而非靜默通過。
- AC-003-3：契約檢查器以純函式 `check_convergence_contract(text) -> list[str]` 暴露，使「錨點消失必須變紅」「空文字不得空洞通過」等負向案例可以合成 fixture 驗證。

## Capabilities

### New Capabilities

- `pr-review-convergence`: `/pr-cycle-deep` 審查迴圈的收斂契約——finding 的證據要求、三種執行結果與降級規則、每輪審查面與 blocking 條件、輪數上限與離開條件、降級出口路由，以及契約自身的機械驗證。

### Modified Capabilities

（無——本 repo 的 openspec 目錄尚無 baseline specs，本 change 為 baseline）

## Step 4 — 假設與約束

### 假設

> **單一來源**：下表**衍生自** `problem-frame.md` 的 W（領域假設），不另行重編。編號沿用 W 編號，「若不成立的影響」沿用該處欄位。修改假設請改 `problem-frame.md`，此處同步。

| # | 假設內容（引自 problem-frame.md W） | 若不成立的影響 |
|---|-----------------------------------|----------------|
| W1 | reviewer 有能力僅憑 diff 導出可執行的證據 | logic/security 類最脆弱。若不成立，該類 finding 實質不再 blocking，閘門退化為「外部 voice 提的 logic bug 都不擋」——與設計意圖相反。減災：改收 failure scenario + 三分法 |
| W2 | 每輪 review summary 持續被貼為 PR comment（既有行為） | 降級的 NIT 將無任何紀錄，「不遺失」不成立 |
| W3 | `pr-flow:issue-triage` 會實際處理 `deferred-from-review` 標籤的 issue | Important 的降級出口成為墳場；製造「有在追蹤」的錯覺 |
| W4 | lead 會遵守「Critical 證據必驗」的約定 | lead 為 LLM，此為 runbook 約定而非機械強制。無效證據得以擋 merge，或真缺陷被誤 drop |
| W5 | 2 輪足以解決多數 PR 的 Critical | circuit breaker 由例外變常態，人類裁決頻率上升。**不影響收斂**——終止由輪數上限無條件保證 |
| W6 | codex / agy 的 read-only sandbox 與 skill-hijack guard 不會為了證據閘門而放寬 | 放寬即重現 agentic 探索失效模式 |
| W7 | PR 作者不會在 Round 2 期間推入與 fix 無關的大型變更 | Round 2 審查面可能大於 Round 1，成本預期不成立。**不影響收斂**——同上 |
| W8 | agentic-hijack 偵測器在新增 `Evidence:` 欄位後仍正常運作 | 非 review 輸出將靜默流入彙整階段 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | reviewer 的 context 僅得為 `guard + prompt-r1.md + diff.patch` | skill-hijack guard 的要求（W6）；放寬即重現 agentic 失效模式 |
| C2 | codex / agy 以 read-only sandbox 執行，無法自行驗證其提出的證據可跑 | 既有 `codex-r1-stage1.sh` 設計；直接決定 logic/security 的證據形式 |
| C3 | `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 行數 ≤ 1220 | 本 change 的自我約束（AC-003-2） |
| C4 | 新增欄位不得破壞 `## Summary\|Findings\|Verdict` 的 agentic-hijack 偵測 | 既有 `codex-r1-stage1.sh` 與 `agy_validate.py` |
| C5 | 錨點比對須以 UTF-8 讀原始位元組 | host rule 13：ASCII 替代會靜默不匹配、不報錯 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| doc / code 分流 rubric | 效果已被證據閘門大部分吸收——閘門一上，doc 上「不夠精確」類自動過不了；且引入 mixed PR 判定灰色地帶與第二套待維護 rubric | 若閘門上線後仍見 doc PR 特有的不收斂，另開 change |
| rules corpus 治理（`/pr-retro` 路由表出口、hot/cold tier） | 不同子系統，回饋源為 `/pr-retro` 而非 review 迴圈 | 本 change 上線後會減少其流入量，屆時重估範圍——可能變小 |
| `/pr-cycle-fast`、`/pr-review-cycle` | 各自獨立的 SKILL.md 與獨立場景 | 若證據閘門在 deep 上被證實有效，再評估移植 |
| golden-transcript eval harness | testplan 指出 21 個 scenario 中 18 個是 LLM 執行期行為、pytest 不可驗證。本 change 先讓契約落地並誠實標示殘餘 | 收斂該殘餘的唯一途徑，優先覆蓋 `critical-evidence-invalid` |
| 以 PATH 上的假 `gh` 自動化 issue 建立的驗證 | 可把兩個 partial 推向 covered，但範圍與成本待評估 | 見 design.md Open Questions |
| 放寬 reviewer sandbox 讓其自驗證據 | 違反 C1／C2，重現 agentic 失效模式 | 不考慮 |

## Step 5 — 完工標準

### Done 定義

- [ ] 3 個 User Stories 的全部 AC 均已實作（AC-001-1~4、AC-002-1~4、AC-003-1~3）
- [ ] `testplan.md` 所有 `[mech]` 類 TC 均有對應測試且通過
- [ ] 所有 `[doc]` 類 TC 均有對應斷言（對真實 SKILL.md）
- [ ] 冒煙測試 SMK-001~003 全數通過
- [ ] **每個必要錨點皆通過 mutation 驗證**（PRC-EG-006）：單點破壞後對應檢查轉紅，一次只改一件事
- [ ] `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 行數 ≤ 1220，且該數字有印給操作者看
- [ ] `make ci` 全綠，且其後 `git diff --name-only` 為空（formatter hook 就地改檔）
- [ ] `spectra validate` 與 `spectra analyze`（Critical + Warning 為 0）通過
- [ ] 程式碼已 code review 並合併

### 冒煙測試情境

#### Scenario: smk-contract-suite-green -- SMK-001 契約套件對真實檔案通過

**GIVEN** repo 已 checkout 且 SKILL.md 為本 change 改動後的版本
**WHEN** 執行 `uv run pytest plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py -q`
**THEN** 系統 MUST 回傳 exit 0
  AND 系統 MUST 收集到至少一個測試（收集到 0 個 MUST 視為失敗，不得視為通過）

#### Scenario: smk-line-budget-reported -- SMK-002 行數在預算內且有回報

**GIVEN** repo 已 checkout
**WHEN** 以 `-s` 執行行數預算測試
**THEN** 系統 MUST 回報實際行數
  AND 該行數 MUST ≤ 1220

#### Scenario: smk-bounded-loop -- SMK-003 一次完整有界迴圈的端到端 dry-run

**GIVEN** 已種入 R1 payload（1 筆有證據 Critical、1 筆無證據 Critical、1 筆 R2 Important、1 筆 NIT）與一個 fix commit
**WHEN** 跑 R1 彙整 → 記錄 baseline SHA → 推 fix → 對 `baseline..HEAD` 跑 R2 → 觀察決策
**THEN** R1 MUST 產生 1 筆 blocking 與 1 筆附理由的 deferred
  AND R2 的審查面 MUST 僅為 fix delta
  AND R2 的 Important MUST 被降級
  AND NIT MUST NOT 於任何輪次擋 merge
  AND 系統 MUST 恰建立 1 張 `deferred-from-review` issue
  AND 系統 MUST NOT 進入第 3 輪

### Traceability Matrix

完整的 21 個 scenario × TC 對照見 `testplan.md`；此處列 US → 代表性 scenario → TC → pytest docstring：

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `evidence-absent-demoted` | PRC-DT-012 | `spec: pr-review-convergence#evidence-absent-demoted` |
| US-001 | `logic-bug-failure-scenario` | PRC-DT-031 | `spec: pr-review-convergence#logic-bug-failure-scenario` |
| US-001 | `precision-finding-always-demoted` | PRC-DT-035, PRC-DT-037 | `spec: pr-review-convergence#precision-finding-always-demoted` |
| US-001 | `critical-evidence-invalid` | PRC-DT-043, PRC-DT-044, PRC-DT-045 | `spec: pr-review-convergence#critical-evidence-invalid` |
| US-002 | `round2-important-demoted` | PRC-DT-019 | `spec: pr-review-convergence#round2-important-demoted` |
| US-002 | `round2-unresolved-critical-adjudicated` | PRC-ST-004 | `spec: pr-review-convergence#round2-unresolved-critical-adjudicated` |
| US-002 | `nit-convention-absent` | PRC-DT-003, PRC-EG-006 | `spec: pr-review-convergence#nit-convention-absent` |
| US-003 | `many-important-one-issue` | PRC-DT-061 | `spec: pr-review-convergence#many-important-one-issue` |
| US-003 | `line-budget-enforced` | PRC-VL-001, PRC-VL-002, PRC-EG-007 | `spec: pr-review-convergence#line-budget-enforced` |
| US-003 | `anchor-absent-fails-loud` | PRC-DT-002, PRC-EG-001, PRC-EG-005 | `spec: pr-review-convergence#anchor-absent-fails-loud` |
| US-002 | `smk-bounded-loop` | SMK-003 | `spec: pr-review-convergence#smk-bounded-loop` |

## Impact

- Affected specs: 新增 `pr-review-convergence`
- Affected code:
  - Modified: `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md`（severity 定義、`prompt-r1.md` 內容規格、Step 5 aggregator 降級與三分法規則、Step 7 輪次契約與 circuit breaker、降級出口路由）
  - New: `plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`（純函式檢查器 + 契約測試）
  - Removed: 無檔案刪除；移除的是 SKILL.md 內的 NIT-blocking 約定與 circuit breaker 舊門檻
- 不影響 `/pr-cycle-fast` 與 `/pr-review-cycle`（各自獨立的 SKILL.md）
- 行數預算（可機械檢查）：改動後 `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 行數必須 **≤ 1220**（現況）。若本 change 讓該檔變長，即代表它用了自己要治的病來治病。
