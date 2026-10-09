## Why

`/pr-retro` 系列已有 Promotion Gate G1「這個教訓能被 hook 自動阻擋嗎？」，但 G1 是 agent 自評的散文判斷，也就是用 rule 決定要不要寫 rule。沒有任何機械檢查確認 G1 被誠實套用：`scripts/lint_rule_evidence.py` 只驗「教訓為真」（證據標記），不驗「為什麼沒有機械化」。結果是 `.claude/rules/` 累積約 233k 字元，其中 01、03、13、15、16 每個 session 全量載入（約 84k）；rule 17 自己承認「繼續寫下來等於承認寫下來沒用」，`lint_shell_subshell_exit.py` 就是事後才把 rule 轉成 gate 的實例。

本 change 把舉證責任反轉：新增 rule 段落時，必須指向一個已存在的機械 gate，或明確宣告為何無法機械化。

## What Changes

- 擴充 `scripts/lint_rule_evidence.py`：新增「機械化宣告」檢查。`.claude/rules/*.md` 新增的 `##` / `###` section 必須在 section 內含下列宣告之一：
  - 連結宣告（HTML 註解形式，語法見 design.md）：路徑必須存在，且落在封閉的 gate 目錄清單（`scripts/`、`.claude/hooks/`、`.pre-commit-config.yaml`、`.github/workflows/`、`scripts/tests/`、`tasks/**/tests/`）。指向另一份 rule 或 SKILL.md 不算 gate。
  - 豁免宣告（同為 HTML 註解形式）：reason 為封閉列舉（`judgment`、`no-observable-signal`、`hook-cost`），說明不可為空或佔位字樣。
- 缺宣告與假宣告**一律為 error，不分新檔或既有檔**。原先既有 rule 檔新增 section 缺宣告只 warn（起步期漸進），但人類裁決不接受這個殘餘風險，改為 error。假宣告（dangling link 等）本來就不降級：降級等於教人亂填通過。
- 新增正向對照 fixture（`scripts/tests/fixtures/rule_mechanization/`）：每個「必須被擋下」的壞輸入形狀各一份 committed diff，加一份由真實 rule 檔複製後注入壞 section 的對照；測試同時斷言 production 入口 `main()` 對這些 fixture 回傳非零，防止「入口短路成成功仍全綠」。
- 更新 `plugins/growth/skills/pr-retrospective/SKILL.md` Step 5 的 rule 草稿模板，讓 agent 產出的建議文字自帶宣告欄位；補 anchor 測試。
- 在 `.claude/rules/11-skill-authoring.md`（scoped，非常駐）記錄宣告語法。不在 01/03/13/15/16 新增文字。

## Non-Goals (optional)

- **不回溯補既有 rule**：不要求既有約 233k 字元的 rule 補宣告，也不批次轉成 gate。
- **不驗證 gate 是否真的覆蓋該 rule**：連結只證明目標存在且屬於 gate 類別；「指向的 gate 其實不管這件事」是已知殘留，留給 `harness-weekly-review` 的觸發率量測，不在本 change。
- **不做 mutation check script**：`/pr-review-cycle` 的「每個已修 finding 都有 revert 後轉紅的測試」是另一條線，另案處理。
- **不自動產生 hook**：仍由 `hookify:hookify` 與人類裁決。
- 被否決的方案：把 G1 改寫得更嚴格的散文（仍是 rule 管 rule）；對所有既有 section 一次設為 error（歷史 corpus 爆紅，違反 evidence lint 的漸進原則）；豁免理由開放自由文字無列舉（等於 catch-all，可被隨手填滿）。

## Capabilities

### New Capabilities

- `rule-mechanization-gate`: rule 新增段落的機械化宣告契約，含連結宣告與豁免宣告的語法、合格 gate 目錄的封閉清單、強制語意（缺宣告與假宣告在所有 rule 檔一律 error），以及正向對照 fixture 的覆蓋要求。

### Modified Capabilities

(none)

## Impact

- 前置依賴：`add-retro-evidence-gate`（目前 31/32，其 `retro-evidence-gate` spec 尚未 archive，故本 change 以新 capability 呈現，不寫 delta）。兩者都改同一支 `scripts/lint_rule_evidence.py`，但該 lint 的程式碼早已在 main 上（該 change 只剩一項待人類裁決的 task 未結），本 change 疊在其上、不改變證據標記行為，所以程式碼層沒有合併順序的限制；唯一的順序關係在 spec 層：兩者互不引用，各自獨立 archive 即可。
- Affected specs: `rule-mechanization-gate`（新增）
- Affected code:
  - Modified: `scripts/lint_rule_evidence.py`
  - Modified: `scripts/tests/test_lint_rule_evidence.py`
  - Modified: `plugins/growth/skills/pr-retrospective/SKILL.md`
  - Modified: `.claude/rules/11-skill-authoring.md`
  - Modified: `scripts/tests/test_pr_retrospective_evidence_gate_anchors.py`
  - Modified: `plugins/sdd/scripts/check_testplan_trace.py` 與其測試（順帶修正：repo 位於 `.claude/worktrees/` 內時整個 repo 的測試被略過，每個 TC 被誤判 missing）
  - Modified: 6 個 plugin 的 `package.json` 與 `.claude-plugin/plugin.json`（lockstep 升版）
  - New: `scripts/tests/fixtures/rule_mechanization/`（壞輸入與合格輸入 diff）
  - New: `openspec/changes/add-rule-mechanization-gate/testplan.md`（補寫，`trace: enforced`）
