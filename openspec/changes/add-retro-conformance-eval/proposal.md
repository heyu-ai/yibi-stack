## Why

`/pr-retro-hard`（PR #376）已上線 Phase 1：skill runbook、彙整 policy kernel、81 個決定性測試，
並以 shadow 模式出貨（`demotion_applied` 預設 `false`）。

Phase 1 只能鎖住「彙整核心的規則正確」——那是純函式，可被 property test 完全覆蓋。它**不能**
回答唯一真正重要的問題：**voice 是否真的抓得到草稿裡的瑕疵**。後者是 LLM 執行期行為，pytest
驗不到。

同時，`add-retro-evidence-gate` 的假設表 W1 把「假證據標記可繞過 gate」列為其最大殘餘風險，
Out of Scope 寫明 golden-transcript harness 是「收斂 W1 殘餘的唯一途徑，另開」。
`/pr-retro-hard` 的 mob review 補了「有人會挑戰」這一半，但「挑戰是否有效」仍未被量測。

在沒有這個量測之前，`enable_demotion` 不應該從 shadow 轉為預設開啟——否則我們是拿一個
未經驗證的機制去改動 lessons DB 的 tier，而 lessons DB 是下游蒸餾與跨 session recall 的來源。

## What Changes

- 把 `tasks/gate_eval/sunset.py` 的突變驗證核心提升為共用模組 `tasks/_eval_mutation.py`，
  由 `gate_eval` 與新模組共用。這是把重複變成接縫的小型可審 refactor；直接 fork 整個
  `gate_eval` 會製造第三份平行實作（現況已有 `gate_eval` 與 `skill_eval` 兩份同架構、
  零共用程式碼）。行為不變，`gate_eval` 的既有測試即為回歸鎖。

- 新增 `tasks/retro_review_eval/`，以 `tasks/gate_eval/` 為模板。**不可 drop-in 重用其
  `mutation-verify`**：`ConformanceFixture` 綁定 gate 專屬的 factors（severity / evidence /
  round / contract_mapping），與本 skill 的決策面不同，models 是必須替換的那一個檔案。

- 沿用 `gate_eval` 兩個關鍵設計約束：**judge 接縫**（核心不 import 任何 LLM，判斷經
  manifest 產出、agent session 執行、dispositions 回放，兩端以 signature 綁定）與
  **anchor-presence judge 等價物**（讓 mutation-kill 能在 pytest 內決定性地證明，不需 agent
  session）。

- Corpus-derived mutation：從真實 retro draft / review comment / rule draft 的 claim–evidence
  pair 出發，突變運算子由歷史失效歸納（evidence replacement / scope expansion / actor
  inversion / causal substitution）。**必須保留 clean twin**，否則量到的只是「看到可疑句就
  報錯」的傾向。

- 量測拆六項，不只「抓到幾條」：detection recall、class accuracy、target localization、
  settling-check validity、clean-twin false-positive rate、false park rate。

- 定義 shadow pilot 協定（10 次真實 retro）與成本量測協定（paired A/B），並把
  `enable_demotion` 由 shadow 轉為開啟的條件寫成可檢查的 gate。**本 change 只定義協定與
  harness，不執行 pilot**——pilot 需要 10 次真實 retro 的資料，無法在實作階段產生。

## Capabilities

### New Capabilities

- `eval-mutation-core`: 共用的突變驗證原語（套用突變、還原並使快取失效、判定 mutation 是否
  有效、分類汰除處置），與 disposition 語意無關，供多個 eval 模組共用。
- `retro-conformance-eval`: retro mob review 的行為層 conformance eval——corpus-derived
  fixture、突變運算子、judge 接縫、六項量測指標。
- `retro-mob-shadow-pilot`: shadow pilot 與成本量測協定，以及把降級由 shadow 轉為啟用所需
  滿足的條件。

### Modified Capabilities

(none)

## Impact

- Affected specs: eval-mutation-core, retro-conformance-eval, retro-mob-shadow-pilot
- Affected code:
  - New:
    - tasks/_eval_mutation.py
    - tasks/_eval_mutation_tests/test_eval_mutation.py
    - tasks/retro_review_eval/__init__.py
    - tasks/retro_review_eval/__main__.py
    - tasks/retro_review_eval/cli.py
    - tasks/retro_review_eval/models.py
    - tasks/retro_review_eval/judges.py
    - tasks/retro_review_eval/metrics.py
    - tasks/retro_review_eval/pilot.py
    - tasks/retro_review_eval/fixtures/README.md
    - tasks/retro_review_eval/tests/test_models.py
    - tasks/retro_review_eval/tests/test_judges.py
    - tasks/retro_review_eval/tests/test_metrics.py
    - tasks/retro_review_eval/tests/test_pilot.py
    - tasks/retro_review_eval/skill.md
  - Modified:
    - tasks/gate_eval/sunset.py
    - tasks/gate_eval/cli.py
    - plugins/growth/skills/pr-retro-hard/SKILL.md
  - Removed: (none)
- 不註冊任何 pre-commit hook 或 merge 阻擋（沿用 gate_eval 的存活策略：移除成本維持在
  刪一個目錄加一個排程項目）。只有秒級的決定性測試進 CI，其餘為離線 suite。
- 相關 issue：#375（本 change 的來源）、#337（gate_eval 自身的季檢視追蹤）。
