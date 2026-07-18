## 1. 資料模型與 fixture schema

- [x] 1.1 於 models.py 定義 Pydantic v2 模型（TriggerPromptClass StrEnum: direct/indirect/negative、TriggerPrompt、TriggerEvalFixture、PromptVerdict、SkillEvalResult、EvalReport），並以 validator 強制 negative 的 expect_trigger 恆為 false，實作 spec 的「Trigger evaluation fixture schema」需求。驗證：test_models 覆蓋三軸 StrEnum 值與「negative expect_trigger=true 被拒」。
- [x] 1.2 於 config.py 實作 fixture 載入器：解析 SKILL.md 旁的 trigger_eval.json，檔案缺失時回報明確錯誤，支撐 spec 的「Missing fixture is surfaced」需求的載入面。驗證：test 讀入示範 fixture 成功、對缺檔 skill 抛出可辨識錯誤。

## 2. Judge 介面與 agent backend

- [x] 2.1 於 judges/base.py 定義 Judge 介面（build_manifest 產判斷任務清單、score 將 judgment 映為 PromptVerdict），核心只依賴此介面不 import LLM client，實作 spec 的「Pluggable judge backend」需求。驗證：test_service 以 stub Judge 跑通、確認核心無 LLM import。
- [x] 2.2 於 judges/agent.py 實作 AgentJudge（「Pluggable judge backend」的預設 agent-driven backend）：build_manifest 產出 prompt×skill 任務清單、apply verdicts 映回結果，verdict 數與 manifest 不符時抛 RuntimeError（不補零不截斷）。驗證：test 覆蓋 manifest 產出與 count-mismatch 抛錯。

## 3. 評測核心與 baseline

- [x] 3.1 於 service.py 實作「Deterministic pass-rate scoring」需求：direct/indirect 的 pass=正確觸發、negative 的 pass=正確未觸發，逐類算 pass rate，全程無 LLM 呼叫。驗證：test_service 以 stub judge 驗三類 pass rate 數值正確。
- [x] 3.2 於 service.py + config.py 實作「Baseline regression detection」需求：baseline 讀寫（.runtime/skill_eval_baseline.json）與容忍門檻回歸偵測，回歸時列出 skill 與 class 並使 eval 回非零。驗證：test 覆蓋 rule 09 三態——pass rate 算對、低於 baseline-tolerance 觸發回歸、fixture 缺失 skip。

## 4. CLI

- [x] 4.1 於 cli.py 建 Click group 並註冊 eval 與 baseline subcommand（service 為 deferred import），實作 spec 的「CLI eval and baseline commands」需求；eval 對缺 fixture 的 skill 走「Missing fixture is surfaced」的失敗路徑。驗證：執行 module --help 列出兩個 subcommand（守 rule 08 dead-code trap）+ test_cli 以 stub judge 跑通兩個 subcommand。
- [x] 4.2 建立 __init__.py（一行中文 docstring）與 __main__.py（2 行：import cli + cli()）標準結構。驗證：uv run python -m tasks.skill_eval 可執行且進入 CLI group。

## 5. Agent-driven runbook 與示範 fixture

- [x] 5.1 撰寫 skills/skill-trigger-eval/SKILL.md runbook：說明如何載入 fixture、派 subagent 判斷每個 prompt 是否觸發、將 verdict 回饋給 CLI；frontmatter 含 name/type/scope(project)/description（rule 11）。驗證：markdownlint-cli2 通過 + frontmatter 四欄位齊全。
- [x] 5.2 為一個高風險家族 skill（如 pr-cycle-fast）撰寫示範 trigger_eval.json，含 direct/indirect/negative 三類 prompt，negative 指向會誤搶的 sibling 情境。驗證：該檔被 test_service 當真實 fixture 載入並計分通過（守 rule 09 fixture schema 用真 description）。
- [x] 5.3 於 skills/README.md 對應表格新增 skill-trigger-eval 一列。驗證：表格新增列且分類欄位符合 SKILL.md 的 type。

## 6. 收尾驗證

- [x] 6.1 跑 make ci 全綠且不影響既有 lint_skill_scope.py / lint_skill_overlap.py。驗證：make ci exit 0，既有兩支 lint script 行為不變。
