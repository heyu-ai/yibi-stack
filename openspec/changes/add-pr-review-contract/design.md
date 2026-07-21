## Context

`/pr-cycle-deep` 目前已有 finding-level Evidence gate、severity disposition、最多兩次 re-review pass 與 circuit breaker，但缺少 PR-level 的意圖契約。reviewer 依通用 rubric 對完整 diff 找問題，無法區分「本 PR 必須交付」、「明確不做」、「已由人類接受的風險」與「未來工作」。此外，frontmatter 的「全員 LGTM（含 actionable NIT）」、Step 7 的 blocking-set merge gate，以及每個 voice 都要 LGTM 的 convergence wording 彼此不一致；初始 cross-debate R2 仍固定執行。

本 change 的 stakeholder 是 PR author、human reviewer、lead aggregator 與各 review voice。既有 reviewer 仍只看共用 diff 與 prompt，不取得寫入權限；human 保留 scope amendment、risk acceptance 與 disputed finding 的最終裁決權。

## Goals / Non-Goals

**Goals:**

- 讓 deep review 在開始前取得一份可引用、可凍結、可修改的 PR-specific Review Contract。
- 讓每個 PR-specific blocking finding 都能指向明確 merge gate，而不是 reviewer 新增的偏好或 scope。
- 讓 LGTM 只由 contract compliance 與 blocking set 決定，消除 raw voice verdict 的隱性 veto。
- 沒有 blocking candidate 或 blocking dispute 時跳過 cross-debate R2。
- 保留既有 Evidence gate、兩次 re-review pass 上限與人類 circuit breaker，並維持 SKILL.md 1220 行預算。

**Non-Goals:**

- 不修改 `/pr-cycle-fast`、`/pr-review-cycle` 或 `mob-code-review-only`。
- 不新增 GitHub App、status check、PR template repository policy 或 runtime parser；本 change 仍是 skill runbook 加機械 document-conformance test。
- 不允許 Review Contract 覆寫 repo hard baseline、安全或資料完整性要求。
- 不改變 finding 的既有 Evidence forms、severity 定義、deferred issue routing 或最多兩次 re-review pass。
- 不要求每個 Follow-up 建立 issue；只有既有降級 Important routing 維持每 PR 至多一張 issue。

## Decisions

### Review Contract 使用五個固定段落並在 R1 前確認

PR body 必須含 `Goal`、`Non-goals`、`Accepted Residual Risks`、`Acceptance Criteria`、`Follow-ups`。新 PR 由 lead 產生；既有 PR 缺少 contract 時，lead 從 title、body、spec 與 diff 擬出草稿，顯示給 human 一次確認後再啟動 R1。選擇固定 Markdown headings，而不是自由文字推斷，因為 reviewer prompt、human quick pass 與 contract checker 都需要穩定引用面。

替代方案是沿用 `/pr-review-cycle` 的 informational scope check；它只能報 drift，不能界定 merge gate，因此不足以阻止 review scope 增長。

### Contract 凍結且只有 material amendment 會重啟 R1

human 確認後，contract 成為該 review pass 的 frozen snapshot。修改 Goal、Non-goals、Accepted Residual Risks 或 Acceptance Criteria，或加入新的 in-scope behavior，屬 material amendment：lead 更新 PR body、記錄原因並從完整 diff 重啟 R1。拼字、格式、連結與不改變語意的澄清屬 editorial amendment，不重啟 review。

替代方案是完全禁止 review 中修改 contract；這會迫使合理的新資訊變成場外決策，或讓 reviewer 繼續依過期 contract 審查。

### Blocking finding 必須映射到封閉的 merge-gate 來源

PR-specific finding 只有三種 blocking source：違反某個 Acceptance Criterion、違反 repo hard baseline，或揭露未被 human 接受的重大風險。finding 必須在 `Contract mapping:` 欄位引用 source，並通過既有 Evidence gate。Non-goals、accepted boundary 內的 residual risks 與 Follow-ups 一律 non-blocking；reviewer 可以建議 contract amendment，但不能自行修改 scope 或新增 Acceptance Criterion。

repo hard baseline 保留獨立地位，避免 author 透過省略 Acceptance Criterion 或把安全問題列入 Non-goal 來規避既有規則。

### Human 單獨擁有 residual-risk acceptance

每筆 accepted risk 記錄 failure mode/impact、accepted boundary、mitigation、detection/recovery procedure 與 human acceptor。缺少 acceptor 或超出 accepted boundary 的風險仍屬未接受風險。review voice 與 lead 不得代表 human 新增風險接受；repo hard baseline 也不能由本段落豁免。

### Aggregator 的 blocking set 是唯一 LGTM gate

最終結果定義為：所有 Acceptance Criteria 有驗證證據、沒有未授權 scope drift、所有 material risk 已被修正或由 human 在界線內接受，且 Evidence gate 後的 blocking set 為空。raw voice 的 `LGTM`/`NEEDS_CHANGES` 僅是 aggregation input；只有 non-blocking finding 的 `NEEDS_CHANGES` 不得阻止 workflow 前進。

這個決策取代「所有 voice 都必須 LGTM」的語意，並同步修正 frontmatter 與 convergence section，避免 Actionable NIT 重新取得 veto。

### Cross-debate R2 使用 activation gate

所有 active voices 仍執行獨立 R1。lead 先做 contract mapping 與 Evidence structure check；若 candidate blocking set 為空，且 reviewer 對 blocking source、severity 或 disposition 沒有衝突，跳過 cross-debate R2並直接產生 aggregate。存在至少一筆 candidate blocking finding，或 reviewer 對同一 finding 的 blocking consequence 有衝突時，才執行 R2。

這保留 cross-model debate 在高價值爭議上的作用，同時移除「乾淨 R1 仍固定付費」的成本。re-review pass 的兩次上限不變；每次 pass 都重新套用同一 activation gate。

### Mechanical checker 同時保護必要規則與已知矛盾

`check_convergence_contract(text)` 增加五段 headings、frozen contract、`Contract mapping:`、human acceptor、blocking-set LGTM 與 conditional R2 的必要錨點；並禁止現有已知矛盾，包括中文「全員 LGTM（含 actionable NIT）」與任何把 unanimous voice verdict 當 merge gate 的既有 wording。測試以真實 SKILL.md、合成缺欄 fixture、forbidden wording mutation 與 R2 gate mutation 驗證。

checker 仍只證明 runbook document conformance，不宣稱能驗證未來 LLM 一定遵守。SKILL.md 維持不超過 1220 行；implementation 必須透過壓縮或取代矛盾／重複文字騰出空間，而不是提高預算。

## Implementation Contract

### Observable behavior

1. `/pr-cycle-deep` 在 reviewer detection 後、任何 defect review 前，顯示並要求 human 確認五段 Review Contract；缺段落時不啟動 R1。
2. R1 prompt 的 Critical/Important finding 具備 `Contract mapping:`，只接受 `AC-<id>`、`repo baseline: <reference>` 或 `unaccepted risk: <description>` 三類來源。
3. Aggregator 將落在 Non-goals、accepted boundary 或 Follow-ups 的 finding 移到 non-blocking output，保留理由；repo hard baseline finding 不受這些段落豁免。
4. R1 candidate blocking set 為空且無 blocking dispute 時，workflow 明確輸出 `R2 skipped: no contract-blocking candidate or dispute`，然後進入 aggregation。
5. candidate blocking set 非空或有 blocking dispute 時，workflow 執行既有 R2 cross-debate。
6. 最終 LGTM 由 contract compliance 加 blocking set 為空決定；voice verdict 不具獨立 veto。
7. material contract amendment 更新 PR body 並重啟 full-diff R1；editorial amendment 繼續目前 pass。

### Interface and data shape

PR body 使用以下固定 headings：

- `## Review Contract`
- `### Goal`
- `### Non-goals`
- `### Accepted Residual Risks`
- `### Acceptance Criteria`
- `### Follow-ups`

finding 格式在既有 `Evidence:` 前後加入 `Contract mapping:`。Accepted Residual Risk 的每一項必須含 `Failure mode / impact`、`Accepted boundary`、`Mitigation`、`Detection / recovery`、`Accepted by`。Follow-up 明示 non-blocking。

### Failure modes

- Contract 缺段落或 Acceptance Criteria 空白：停止在 pre-review contract gate，顯示缺失欄位，不啟動 reviewer。
- Accepted Residual Risk 缺 `Accepted by`：視為 unaccepted risk，不得當作 waiver。
- finding 缺合法 `Contract mapping:`：移入 deferred/non-blocking，保留原文與原因；repo baseline 類必須提供可定位 reference。
- material amendment 未由 human 確認：沿用 frozen snapshot，停止新增 scope 的 review，等待裁決。
- checker 發現必要錨點缺失、forbidden unanimous wording 或超過 1220 行：測試失敗，不得提交為完成。

### Acceptance and verification

- `uv run pytest plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py -q` 通過且收集到測試。
- checker 對真實 SKILL.md 回傳空 failure list。
- 移除任一 Review Contract heading、conditional R2 anchor 或 blocking-set LGTM anchor 時，對應 mutation test 轉紅。
- 插入「全員 LGTM（含 actionable NIT）」或等價既有 unanimous gate wording 時，forbidden test 轉紅。
- `wc -l plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 結果不超過 1220。
- `spectra analyze add-pr-review-contract` 與 `spectra validate add-pr-review-contract` 無 Critical/Warning。

### Scope boundaries

In scope 僅包含 deep skill runbook、其 convergence checker/tests 與本 change artifacts。Out of scope 包含其他 PR skills、GitHub policy automation、runtime PR-body parser、review model selection、Evidence form redesign 與 deferred issue policy改寫。

## Risks / Trade-offs

- [Human confirmation 增加一次前置互動] → 對既有 PR 由 lead 自動擬稿，只要求一次確認；相較固定 R2 與 scope creep，成本可預期且較低。
- [Author 可能把缺陷包裝成 Non-goal 或 accepted risk] → repo hard baseline 不可被 contract 覆寫，accepted risk 必須具界線、mitigation、recovery 與 human acceptor。
- [Conditional R2 可能漏掉跨模型互相啟發的新 finding] → 所有 voice 仍執行獨立 R1；只有在沒有 candidate blocker 與 dispute 時省略 debate，且 human quick pass 保留。
- [String checker 無法理解所有語意等價矛盾] → 保護已知 wording、必要 section anchors 與 mutation fixtures，並在文件中誠實標示只驗證 conformance。
- [1220 行預算使實作需要刪減舊說明] → 優先取代矛盾與重複 wording，不刪除安全 guard、Evidence forms 或 troubleshooting 的實際操作資訊。

## Migration Plan

此 change 無資料遷移。上線後只影響新啟動的 `/pr-cycle-deep` session；已進行中的 session 可沿用原 frozen context。若 conditional R2 造成不可接受的漏檢，可回退 SKILL.md 與 checker commit，既有 PR 與 review artifacts 不需轉換。
