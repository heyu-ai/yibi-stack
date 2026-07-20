## Why

`/pr-cycle-deep` 已用證據閘門與兩輪上限約束 re-review，但 reviewer 仍缺少 PR-specific 的意圖、範圍與風險契約；同時 workflow 對每個 voice 的 LGTM 與固定 R2 debate 仍有隱性依賴，造成沒有 blocking finding 時仍可能延長 review。

## What Changes

- 在 deep review 開始前，要求 PR body 具備 `Goal`、`Non-goals`、`Accepted Residual Risks`、`Acceptance Criteria`、`Follow-ups` 五段 Review Contract，並由人類確認後凍結。
- 規範 PR-specific blocking finding 必須對應 Acceptance Criterion、repo hard baseline，或尚未接受的重大風險，且仍須通過既有 Evidence gate。
- 規範 Non-goals、界線內的 accepted risks 與 Follow-ups 為 non-blocking；reviewer 只能建議修改 contract，不能自行擴張 scope 或新增 merge gate。
- 將最終 LGTM 定義統一為 contract compliance 且 blocking set 為空，不再要求所有 raw reviewer verdict 一致。
- 加入 R2 activation gate：R1 只有在存在 evidenced blocking finding、blocking severity 爭議或 reviewer 對 blocking consequence 有衝突時才進入 cross-debate；否則直接結束 mob debate。
- 擴充 convergence contract checker 與測試，防止「全員 LGTM／NIT 也要 LGTM」等義規則重新出現，並驗證 Review Contract 與 conditional R2 的必要錨點。

## Capabilities

### New Capabilities

- `pr-review-contract`: 定義 `/pr-cycle-deep` 的 PR-specific review contract、blocking finding 映射、human-owned risk acceptance、contract amendment、LGTM 與 R2 activation 規則。

### Modified Capabilities

（無）

## Impact

- Affected specs: 新增 `pr-review-contract`
- Affected code:
  - Modified: `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md`
  - Modified: `plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py`
  - New: `openspec/changes/add-pr-review-contract/specs/pr-review-contract/spec.md`
  - New: `openspec/changes/add-pr-review-contract/design.md`
  - New: `openspec/changes/add-pr-review-contract/tasks.md`
  - New: `openspec/changes/add-pr-review-contract/testplan.md`
  - Removed: 無

## Follow-ups（不阻擋本 PR merge）

- **extract-r1.md schema 需帶 `contract_mapping` / `evidence` 欄位**：本 change 讓
  `Contract mapping:` 與 `Evidence:` 成為 aggregation gate 的必要輸入，但外部 voice（Codex/agy）的
  Stage-2 萃取 schema（`prompts/extract-r1.md`）目前不帶這兩欄，compact 化後 gate 看不到所依賴的欄位
  （lead 讀 raw 可暫時緩衝）。此 gap 非本 PR 引入（#305 即存在）且落在 8 檔 diff 之外，追蹤為獨立 issue。
- **「Round 1/Round 2」命名重載**：cross-debate 輪次與 bounded re-review pass 共用同一詞，建議在
  Step 7 補一句釐清（非功能性矛盾，Step 7 表格已可辨別）。
