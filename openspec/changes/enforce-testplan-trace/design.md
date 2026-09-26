## Context

`spectra-amplifier` Step 2 由 `qa-test-designer` 產生 `testplan.md`。實測顯示 testplan 與測試碼之間沒有任何可機械驗證的連結
（proposal 的 Why 段有完整數字）。現況的三個結構性原因：

1. **沒有綁定語法**：測試只有 `spec: <cap>#<slug>` 指向 Gherkin scenario，沒有任何欄位指向 TC-ID。過去的「命中率」是用 TC-ID
   字串去 grep 測試碼算出來的，通用 ID（例如 `SMK-001`）會在 fixture 裡誤命中。
2. **沒有結構化的 TC 類別**：`[mech]`／`[doc]`／`[manual]` 只是寫在 Coverage 表 Notes 欄的自由文字，程式無法區分哪些 TC 應該有自動化測試。
3. **沒有任何入口在檢查**：`check_spec_coverage.py` 不讀 testplan；`amplifier-verify.py` 只在手動跑 `/pr-cycle-deep` 時執行，
   而且只檢查 docstring 格式；CI、pre-commit 都沒有接。

限制條件：

- sdd 與 dev-cycle 是兩個分開安裝的 plugin，彼此不能 import 對方的 Python 模組。
- Host 專案已有大量舊 testplan（yibi-mvp 80 份、ainization-skill 5 份），新規則不能讓它們一上線就全部轉紅。
- PR #470 為 testplan 加入 `## Test Seams` 表與 TC 表的 `Seam` 欄；本 change 在其模板結構之上延伸，須等 #470 merge。
- 會改檔的檢查不能當 gate（repo 慣例）。

## Goals / Non-Goals

**Goals:**

- 每一個自動化 TC 都能機械地確認「有沒有測試綁定它」，而且綁定是明確宣告，不是字串巧合。
- 測試改名、TC 改名造成的脫鉤會被抓到，不再靜默。
- 同一個 TC-ID 被兩份 testplan 使用、或同名 TC 綁到不同 scenario，會被抓到。
- 人工驗證項目有明確的生命週期：列出、在 human quick pass 逐項確認、留痕。
- change 宣稱完成時（tasks.md 全勾）或 archive 前，未綁定的自動化 TC 會阻擋。
- 同一份檢查邏輯接到 pre-commit、CI、pr-cycle-deep Step 1.5、Step 11a。
- testplan 的產生不再讓整張 TC 表進出 lead context。

**Non-Goals:**

- 語意層面驗證「測試真的測了 TC 描述的行為」。這仍靠 review；PR #469 已在 R1 prompt 加入測試品質的 evidence 形式。
- 回溯修補 archived testplan，或替既有 active change 自動補 `tc:`。
- 非 Python 測試（例如 Flutter／Dart、TypeScript）的綁定解析。本 change 只解析 Python 測試的 docstring。
- 修改外部 spectra CLI 或 `/spectra-apply`。
- 讓報告模式回寫 testplan。

## Decisions

### 以 docstring 的 tc 行作為唯一綁定語法

測試函式（含 class method）的 docstring 內，一行 `tc: <TC-ID>[, <TC-ID>...]` 宣告它實作了哪些 TC；與既有的 `spec: <cap>#<slug>` 行並存。
解析用 Python `ast` 讀取 docstring，不用 regex 掃整個檔案，避免 fixture 字串、註解、測試資料裡出現的 ID 被誤判為綁定。

- 否決：沿用 TC-ID 自由文字 grep。這正是命中率虛高（44%／60% 都偏高）的原因。
- 否決：用 pytest marker（`@pytest.mark.tc("X")`）。需要在每個 host 專案註冊 marker，而 docstring 慣例已存在（`spec:`），延伸成本最低。

### TC 表新增 Kind 欄取代自由文字標記

testplan 模板的 TC 表新增 `Kind` 欄，值只能是 `auto` 或 `manual`。`auto` 表示應有自動化測試綁定；`manual` 表示由人工驗證，
這類 TC 不進 TC 表，改列在 `## Manual Verification` checklist（見下一個決策）。沒有 `Kind` 欄的舊 testplan 一律視為 legacy（只 WARN）。

- 否決：解析 Notes 欄的 `[mech]` 自由文字。格式不固定，而且是寫在 Coverage 表而非 TC 表。

### 人工驗證改為 Manual Verification checklist

`[manual]`／`[doc]` 類不再展開成 8 欄 TC。testplan 新增 `## Manual Verification` 區段，每項為
`- [ ] MV-NNN <可觀察的驗證敘述>（scenario: <slug>）`。pr-cycle-deep Step 8 human quick pass 把未勾選項目列給人類逐項確認，
確認結果以 PR comment 留痕，並由 lead 把對應項目改為 `- [x]`。strict 模式下仍有未勾選的 MV 項目即 FAIL。

- 否決：維持 8 欄表格。實測這類 TC 幾乎全數沒有落地，展開成表格只增加產生成本，沒有任何人執行它。

### 以 testplan 內的 trace 宣告做前向式 opt-in

新模板在 testplan 開頭加入一行 `trace: enforced`。只有帶此宣告的 testplan 會套用 FAIL ratchet；沒有宣告的舊 testplan
所有 finding 永遠只是 WARN。`spectra-amplifier` 產生的新 testplan 一律帶此宣告。

- 否決：在 checker 內維護舊 change 的豁免清單。清單會被複製到每個 host 專案、只增不減，且過去 lessons 顯示豁免形狀一旦能寫得比對照寬，就會被繞過。
- 否決：一上線即對所有 testplan FAIL。會讓 yibi-mvp 80 份舊 testplan 全部轉紅，逼人大量補 `tc:` 或關掉 gate。

### 嚴重度 ratchet 依 tasks.md 完成度與 strict 旗標決定

對帶 `trace: enforced` 的 testplan：change 的 tasks.md 仍有未勾選項目 → finding 為 WARN；tasks.md 全部勾選（至少一項），
或呼叫端傳入 `--strict` → finding 為 FAIL。Step 11a archive 前一律以 `--strict` 呼叫。

- 否決：永遠 FAIL。開發中（先寫 testplan、測試尚未寫）會持續紅燈，red-first 流程無法運作。

### checker 放在 sdd plugin，amplifier-verify 以子程序呼叫

新 checker `check_testplan_trace.py` 放在 sdd plugin 的 scripts，是唯一實作。dev-cycle 的 `amplifier-verify.py` 不 import 它，
而是以子程序呼叫，用與 `spectra-amplifier` 相同的方式解析 sdd plugin 根目錄（installed_plugins.json 的 installPath，
開發時 fallback 到 repo 內 plugins/sdd）。偵測到 spectra change 但找不到 checker 時，amplifier-verify 以 exit 2 fail-closed。

- 否決：把 checker 放在 dev-cycle。host 專案的 pre-commit 只裝 sdd 時就用不到。
- 否決：在 amplifier-verify 內複製一份解析邏輯。兩份實作一定會漂移。

### TC-ID 格式以 test-convention 為唯一 owner

`qa-test-designer` 不再自訂 `[CAP]-[TECHNIQUE]-[SEQ]`，改為遵循 Convention Detection 選出的約定（host 的
`.claude/rules/09-test-conventions.md`，否則 plugin 的 `test-convention.md`）。Technique（EP／BVA／DT…）只寫在 TC 表的 Technique 欄，不進 TC-ID。

### qa-test-designer 直接寫 testplan 檔

`qa-test-designer` 取得 Write tool，把 testplan.md 直接寫到呼叫端指定的路徑，只回傳摘要（TC 數、auto／manual 數、Coverage 缺口數、檔案路徑）。
lead 以 `check_testplan_trace.py --report --change <name>` 驗證檔案可解析，不再讀入整張 TC 表。

### tasks.md 產生 red-first 測試任務

`spectra-amplifier` 產生 tasks.md 時，每個 User Story 下第一個任務固定是「撰寫帶 tc 綁定的失敗測試」，列出該 US 的 auto TC-ID；
實作任務排在其後。與 PR #469 的 red-first gate 對齊。

### 報告模式不回寫任何檔案

`--report` 輸出每個 TC 對應的 test nodeid（`path::Class::func`）與狀態，只寫 stdout；exit code 永遠為 0（除非設定錯誤）。
它是給人看的現況，不是 gate。

## Implementation Contract

**CLI**：`python3 <sdd-root>/scripts/check_testplan_trace.py [--repo-root <path>] [--openspec-dir <path>] [--change <name>] [--tests-dir <path> ...] [--strict] [--report]`

- `--repo-root` 預設為 cwd 的 git toplevel；`--openspec-dir` 預設為 `openspec`（相對於 repo root，host 專案例如 yibi-mvp 放在 `docs/` 下時可覆寫）；active change 為 `<openspec-dir>/changes/<name>/`（排除 `archive/`），archived 為 `<openspec-dir>/changes/archive/*/`。
- TC 表的辨識：表頭第一欄為 `TC-ID`，且表頭含 `Test Purpose` 或 `Expected Result`（排除只有 TC-ID 的冗餘表等其他表格）。TC 對 scenario slug 的映射取自所有同時含 slug 欄與 TC-ID 欄的表（Coverage Analysis、Traceability Matrix、以及帶 `Scenario Slug` 欄的 TC 表）。
- `--change` 未指定時檢查所有帶 testplan.md 的 active change。
- `--tests-dir` 可重複；未指定時掃描 repo 內所有 `test_*.py` 與 `*_test.py`（排除 `.venv`、`node_modules`、`.git`）。

**Finding 類型**（每行一筆，stdout，格式 `[<SEVERITY>] <kind>: <change> <TC-ID> -- <detail>`）：

| kind | 條件 |
| --- | --- |
| missing | auto TC 沒有任何測試的 docstring 以 tc 行綁定它 |
| orphan | 測試 docstring 的 tc 行引用了任何 active 或 archived testplan 都不存在的 ID |
| mismatch | 測試綁定了某 TC，但該測試的 spec slug 不在 Coverage 表中對應此 TC 的 scenario slug 集合內；測試有 tc 行卻沒有 spec 行也屬此類 |
| collision | 某 active testplan 定義的 TC-ID 也出現在另一份 active 或 archived testplan |
| manual-open | strict 模式下 Manual Verification 仍有未勾選項目 |

**嚴重度**：非 enforced testplan 的所有 finding 為 WARN；enforced testplan 依 ratchet 決策為 WARN 或 FAIL；orphan 與 collision 不隸屬單一
enforced change 時一律 WARN。

**Exit code**：`0` = 無 FAIL（可能有 WARN）；`1` = 至少一筆 FAIL；`2` = 設定錯誤（repo root 不存在、指定的 change 不存在、enforced testplan 無法解析出 TC 表）。legacy testplan 無法解析時只報 `unparsable` WARN，避免舊格式讓 gate 一上線就轉紅。
stderr 只放 `[FAIL]` 設定錯誤與診斷訊息。

**純函式核心**：`check_trace(testplans, bindings, tasks_state, strict) -> list[Finding]` 不做 I/O，供測試以合成資料驗證每一種 finding 與負向對照。

**接線**：

- pre-commit：新 hook 以非 strict 模式執行，`verbose: true`，影響檔案為 testplan.md、tasks.md 或 Python 測試時觸發。
- CI：`.github/workflows/ci.yml` 以非 strict 模式執行全 repo。
- pr-cycle-deep Step 1.5：`amplifier-verify.py` 呼叫 checker，FAIL 併入 MUST findings、WARN 併入 SHOULD findings。
- pr-cycle-deep Step 11a：archive 前以 `--strict --change <name>` 執行，exit 1 即停止 archive。

**驗收**：

- 單元測試對每一種 finding 各有正向與負向案例，並以 mutation 驗證（拿掉任一判斷，至少一個測試轉紅）。
- 對真實 repo 以 `--report` 執行，對既有 4 個 active change 只產生 WARN、exit 0。
- 在真實 testplan 的副本注入一個改名的 tc 綁定，checker 報出 orphan 與 missing。

**範圍**：in scope 為上述 checker、模板、agent、amplifier SKILL.md、pr-cycle-deep 接線、pre-commit 與 CI；out of scope 見 Non-Goals。

## Risks / Trade-offs

- [Risk] 作者可以刪掉 `trace: enforced` 來躲避 FAIL → 刪除會出現在 diff 中，且 orphan／mismatch 仍會以 WARN 報出；pr-cycle-deep review 可見。
- [Risk] Python 以外的測試無法綁定，host 專案（例如 Flutter）的 auto TC 會全部報 missing → 非 Python 專案不在 testplan 加 `trace: enforced`，只取得 WARN；列為後續 change。
- [Risk] 依 tasks.md 勾選判斷「完成」，作者可能提早全勾 → 那正是應該要 FAIL 的時點，提早全勾只會讓 gate 更早生效。
- [Risk] pre-commit 全 repo 掃描測試檔的成本 → 只解析 docstring（ast），yibi-stack 規模預估在數秒內；實作時量測並記錄。
- [Trade-off] mismatch 只比對 slug 層級，同一 scenario 下的「同名不同義」仍擋不住 → 語意驗證屬 Non-Goals，由 review 處理。

## Open Questions

- 既有 4 個 active change 是否要回填 tc 綁定並加上 `trace: enforced`（本 change 不做，需使用者決定）。
- Host 專案接線方式：由 `sdd:setup` 自動加入 pre-commit hook，或只在 README 文件化（本 change 只文件化，自動化需使用者決定）。
