## Why

`/pr-cycle-deep` 的 Evidence gate（決定一筆 finding 是 blocking 還是 deferred）不是程式，是
`plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 裡的散文，由 lead agent 在執行期閱讀後施行。
既有測試守不到它：`plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`
只斷言 runbook 裡的錨點字串在場且承重，兩支 validator 腳本分別處理 agy 輸出的靜默失敗與 TC
覆蓋率，都不碰 disposition 判定。

這個缺口是既知的，而且已經被寫下來過：`openspec/changes/add-pr-review-contract/testplan.md`
的可測性前提表明寫 `[doc]` 類測試「證明 runbook 有明文寫這條規則，沒證明 lead 會不會遵守」，
其 Missing Coverage 段落建議新增 golden-eval harness（種入 review payload、比對期望的
contract-compliance 判定，以手動或 nightly 執行而非進 pre-commit），並要求在它存在之前，
testplan 必須明講契約測試全綠只代表文件符合性。該建議至今未實作。

現在做的理由：gate 的 disposition 矩陣宣稱「每一格都有定義、無歧義」，這是一個可證偽的宣稱，
而且證偽它不需要真實 PR、diff 或外部 reviewer——Step 5 的輸入（R1/R2 文字加 Review Contract）
完全可以合成，成本是一個工作天。缺口每多存在一天，就多一段時間無法分辨「gate 有在運作」與
「gate 是儀式」。

## What Changes

- 新增 gate conformance eval：以合成 finding fixture 驅動 lead agent 執行 SKILL.md Step 5 的
  disposition 判定，比對預先標註的正解。fixture 逐格對應 disposition 矩陣，每筆只變動一個因子。
- 新增守恆檢查（本 change 相對既有建議的第一項增量）：斷言每一筆輸入 finding 都出現在輸出、
  恰好一次、標題與描述逐字保留。被靜默丟棄的 finding 是 gate 自身的 fail-open，且不可見，
  因此優先序高於 disposition 正確性。
- 以多次執行的分佈取代單次布林結果（第二項增量）：受測系統是 LLM，單次結果無資訊量。
  跨次不一致本身即為結論——一個判定不穩定的 gate 不是 gate，與其平均準確率無關。
- 新增 eval 自身的有效性驗證與 sunset 協議（第三項增量）：每筆 fixture 綁定一個對 SKILL.md 的
  單一變更（mutation），該變更必須使該 fixture 由綠轉紅；殺不死的 fixture 沒有資訊量，予以移除。
  suite 層級設定預先承諾的 sunset 觸發條件與檢視排程，避免 harness 因自身存在而永久存在。
- 沿用 `tasks/skill_eval` 既有形狀（fixture 模型、agent judge backend、逐類計分、baseline
  regression 比對），不重造 harness 骨架。

## Capabilities

### New Capabilities

- `review-gate-conformance-eval`: 以合成 finding fixture 驗證 lead agent 對 Evidence gate
  disposition 矩陣的符合度，涵蓋 fixture schema、守恆檢查、多次執行分佈與穩定度判定、
  以及執行入口與退出碼契約。
- `eval-fixture-sunset`: eval 自身的有效性度量與退場協議，涵蓋 fixture 層級的 mutation
  存活判定與 prune 規則、suite 層級的 sunset 觸發條件與檢視排程、以及移除程序。

### Modified Capabilities

(none)

## Impact

- Affected specs: `review-gate-conformance-eval`（新增）、`eval-fixture-sunset`（新增）
- Affected code:
  - New:
    - tasks/gate_eval/__init__.py
    - tasks/gate_eval/__main__.py
    - tasks/gate_eval/cli.py
    - tasks/gate_eval/models.py
    - tasks/gate_eval/service.py
    - tasks/gate_eval/sunset.py
    - tasks/gate_eval/fixtures/oracle.yaml
    - tasks/gate_eval/fixtures/findings/
    - tasks/gate_eval/tests/test_models.py
    - tasks/gate_eval/tests/test_service.py
    - tasks/gate_eval/tests/test_sunset.py
  - Modified:
    - openspec/changes/add-pr-review-contract/testplan.md（Missing Coverage 段落補上本 change 的指向）
  - Removed: (none)
- 不進 pre-commit 與 CI 阻擋路徑：eval 需呼叫 agent，成本與延遲不適合每次 commit；
  以獨立入口手動或排程執行，這同時讓 sunset 時的移除成本維持在刪一個目錄加一個排程項目。
- 既有 `tasks/skill_eval` 不修改；本 change 僅沿用其設計形狀，兩者的 fixture 語意不同
  （trigger 布林 vs disposition 列舉），不共用資料模型。
