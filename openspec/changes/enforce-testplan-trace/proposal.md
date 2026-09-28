# Proposal：enforce-testplan-trace

> 版本：v1.0 | 日期：2026-09-25 | 狀態：Draft
> 前置：PR #470（testplan 加入 Test Seams、amplifier-verify Check 4）；對齊 PR #469（red-first gate）

## Why

`spectra-amplifier` Step 2 產出的 `testplan.md` 目前是「寫完就沒人讀的文件」。實測（2026-09-25，
研究文件 `docs/research/2026-09-25-pr-cycle-deep-token-cost.md` 第 4 節）：

- yibi-stack 8 份 testplan 共 220 個 TC，在測試碼找得到 97 個（44%）；ainization-skill 188 個 TC 找得到 112 個（60%）。
  這兩個數字還偏高：`SMK-001` 這類通用 ID 在測試 fixture 裡誤命中、`PRC-*` 被兩個 change 共用、
  skill-trigger-eval 的 SEVAL ID 同名但測的是不同行為。
- `[doc]`／`[manual]` 類 TC 幾乎全數沒有落地。
- financial-registry 實作時改用 `FREG-*` 前綴，testplan 仍是 `REG-*`，16 個 TC 全部脫鉤，沒有任何東西報錯。
- `plugins/sdd/scripts/check_spec_coverage.py` 完全不讀 testplan，但 `plugins/sdd/skills/spectra-amplifier/SKILL.md`
  的「完工標準」寫著「testplan.md 所有 TC 均有對應測試（check_spec_coverage.py 驗證）」，這是不實宣稱。
- CI、pre-commit、Makefile 都沒有呼叫任何 TC 檢查；唯一解析 testplan 的 `amplifier-verify.py` 只檢查 docstring
  標記格式，從不檢查「每個 TC 都有對應測試」。
- TC-ID 有兩套互相衝突的約定：`test-convention.md` 用 `[FEATURE]-[CATEGORY]-[NUM]`（VL／DT／ST…），
  `qa-test-designer.md` 用 `[CAP]-[TECHNIQUE]-[SEQ]`（EP／BVA…）。

PR #470 讓 testplan 宣告「每個 TC 在哪個 seam 測」，但它自己也寫明：Check 4 只檢查結構，**不檢查 TC 有沒有被實作**。
本 change 補上缺的那一段：testplan 與測試之間的雙向、可機械驗證的閉環。

## What Changes

- **明確綁定**：測試 docstring 新增一行 `tc: <TC-ID>`，與既有的 `spec: <cap>#<slug>` 並存。追溯改以這一行為準，
  不再用自由文字比對 TC-ID。
- **新 checker**（sdd plugin 內單一實作，純函式加 CLI）：對 active change 的 testplan 做四項檢查——
  - missing：自動化 TC 在測試碼中沒有任何 `tc:` 引用
  - orphan：`tc:` 引用的 ID 不存在於任何 active 或 archived testplan（抓改名漂移）
  - mismatch：帶 `tc:` 的測試，其 `spec:` slug 與該 TC 列的 Scenario Slug 不一致（擋同名不同義）
  - collision：同一個 TC-ID 出現在兩份 active testplan
- **嚴重度 ratchet**：change 的 tasks.md 尚有未勾選項目時只報 WARN；tasks.md 全部勾選，或在 archive 前，報 FAIL。
- **每個入口都接同一份實作**：pre-commit、CI（commit range）、pr-cycle-deep Step 1.5（`amplifier-verify.py` 呼叫同一函式）、
  pr-cycle-deep Step 11a archive 前。
- **人工驗證不再被丟掉**：`[manual]`／`[doc]` TC 不再展開成 8 欄表格，改為 testplan 的 Manual Verification checklist；
  pr-cycle-deep Step 8 human quick pass 逐項確認，結果以 PR comment 留痕。
- **生成端**：
  - `qa-test-designer` 改為直接寫 testplan.md（增加 Write tool），lead 只收摘要，TC 表不再進出 lead context。
  - TC-ID 統一為單一約定，`test-convention.md` 為唯一 owner。
  - tasks.md 為每組自動化 TC 產生 red-first 任務：先寫帶 `tc:` 的失敗測試，再實作。
- **修正不實宣稱**：`spectra-amplifier/SKILL.md` 完工標準改為指向新 checker。
- **報告模式**：新 checker 提供不改任何檔案的 `--report`，輸出 TC 對應 test nodeid 的現況表；報告模式不是 gate。

## Capabilities

### New Capabilities

- `testplan-trace`: testplan TC 與測試之間的綁定語法、四項雙向檢查、嚴重度 ratchet、各入口接線，以及人工驗證 checklist 的生命週期

### Modified Capabilities

(none)

## Impact

- Affected specs: testplan-trace（新增）
- Affected code:
  - New:
    - plugins/sdd/scripts/check_testplan_trace.py
    - plugins/sdd/scripts/tests/test_check_testplan_trace.py
  - Modified:
    - plugins/sdd/agents/qa-test-designer.md
    - plugins/sdd/references/testplan-template.md
    - plugins/sdd/references/tasks-template.md
    - plugins/sdd/skills/spectra-amplifier/SKILL.md
    - plugins/sdd/skills/spectra-amplifier/test-convention.md
    - plugins/sdd/skills/spectra-amplifier/bdd-trace-convention.md
    - plugins/sdd/scripts/README.md
    - plugins/dev-cycle/skills/pr-cycle-deep/scripts/amplifier-verify.py
    - plugins/dev-cycle/skills/pr-cycle-deep/SKILL.md
    - .pre-commit-config.yaml
    - .github/workflows/ci.yml
- 相依：PR #470 須先 merge（本 change 讀取它新增的 Seam 欄與 testplan 模板結構）。
- Host 專案（例如 yibi-mvp 有 80 份 testplan）透過 sdd plugin 取得 checker，但 pre-commit／CI 接線需各自完成，見 design.md 的開放問題。
