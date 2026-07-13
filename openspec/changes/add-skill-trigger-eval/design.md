## Context

B1（`scripts/lint_skill_overlap.py`，PR #190 已上線）提供確定性關鍵字重疊靜態偵測，只能示警「description 看起來易混」，無法量測實際觸發行為。rule 11 定義了 direct/indirect/negative 三軸觸發治理紀律，但目前只有人工文字，沒有工具。

既有先例 `tasks/harness_eval/` 採「Python 機械 + agent 語意」分層：scan subcommand 由 Python 產出結構化數字與 semantic_targets，語意評分則由 SKILL.md 派 subagent 完成。本設計沿用同一分層哲學。

計費歸屬已經 context7 查證：透過本機 MiniShell ACP Gateway 驅動的 `claude` 若為訂閱 OAuth 認證，不產生計量 API 費用但消耗 Claude Code 訂閱額度；API key 認證則按 token 計費。hosted CI 上沒有本機 ACP／訂閱登入，只能用 API key。此結論決定了各 judge backend 的成本與適用場景。

## Goals / Non-Goals

**Goals:**

- 提供確定性、可完整單元測試的評測核心（載入 fixture、計分、baseline 比對、報告）。
- judge backend 可插拔；本 change 先實作 agent-driven backend（無需 API key）。
- fixture schema 對映 rule 11 的 direct/indirect/negative 三軸。
- 提供 baseline 比對 + 容忍門檻的回歸偵測。

**Non-Goals:**

- 本 change 不實作 api backend 與 acp backend（Phase 2/3）。
- 不接 CI hard-gate（workflow_dispatch）、不建 scheduler 漂移報告 job。
- 不自動產生 fixture；fixture 由人工 curate。
- 不覆蓋全部 skill；本 change 只附一個高風險家族的示範 fixture。

## Decisions

**D1 — 可插拔 judge backend。** 於 judges/base.py 定義 Judge 介面，確定性核心只依賴此介面。理由：把「用哪個 LLM／哪種認證判斷觸發」與「載入 fixture／計分／比 baseline」解耦。Design A 與 Design B 因此變成同一模組的兩個 backend，run cadence（手動／weekly／monthly）是上層編排選擇，與 backend 無關——不必在 build time 二選一。

**D2 — Phase 1 只做 AgentJudge（Design B）。** 理由：無 API key、成本最低、對映已定案的方案 B，且可用 stub 完整單元測試。api／acp backend 是後續增量。

**D3 — fixture 放 SKILL.md 旁 trigger_eval.json。** 理由：就近維護，跟著 skill 走；新增／修改 skill 時 fixture 同目錄可見。

**D4 — pass rate 分三類統計。** direct/indirect 的 pass = 正確觸發；negative 的 pass = 正確「不」觸發（expect_trigger=false）。三類分開計分，避免把召回與精確度混成單一數字。

**D5 — baseline 存 .runtime/skill_eval_baseline.json（rule 06 config pattern）。** 每個 skill 記三類 pass rate。容忍門檻有預設值，可由 CLI 旗標調整。

**D6 — AgentJudge 兩段式。** build_manifest 產出 prompt×skill 的判斷任務清單（純資料，無 LLM）；apply_verdicts 吃回饋的 verdict 清單算結果。LLM 判斷發生在 agent session（由 SKILL.md 驅動），Python 端無 LLM 依賴，故核心可測。

## Implementation Contract

**Behavior（operator 觀察到什麼）：**

- eval subcommand 載入指定 skill（或全部）的 fixture，取得每個 prompt 的 verdict，印出三類 pass rate 並與 baseline 比對；偵測到回歸時 exit 1。
- baseline subcommand 把當前 pass rate 寫入 baseline 檔。

**Interface / data shape：**

- models.py（Pydantic v2，rule 05）：TriggerPromptClass（StrEnum：direct/indirect/negative）、TriggerPrompt（prompt: str、expect_trigger: bool）、TriggerEvalFixture（skill: str、direct/indirect/negative: list[TriggerPrompt]）、PromptVerdict（prompt: str、cls: TriggerPromptClass、triggered: bool、passed: bool）、SkillEvalResult（每類 pass rate + verdicts）、EvalReport（多 skill 彙整 + 回歸清單）。
- Judge 介面（judges/base.py）：build_manifest(fixtures) 回傳判斷任務清單；score(manifest, verdicts) 回傳 list[PromptVerdict]。AgentJudge 實作之。
- fixture JSON 形狀：頂層物件含 skill 字串與 direct/indirect/negative 三個陣列；每個元素含 prompt 與 expect_trigger 布林（negative 恆為 false）。
- CLI：Click group（rule 08）含 eval 與 baseline 兩個 subcommand，service 為 deferred import。
- baseline JSON 形狀：以 skill 名為 key，值為 direct/indirect/negative 三個浮點 pass rate。

**Failure modes：**

- fixture 檔不存在 → 印 [FAIL] 並 SystemExit(1)。
- fixture schema 不合 → Pydantic ValidationError 攔截 → 印 [FAIL]。
- verdict 數與 manifest 不符 → 抛 RuntimeError（不靜默補零）。
- 偵測到回歸（某類 pass rate < baseline - tolerance）→ eval exit 1 並列出退步的 skill 與類別。

**Acceptance criteria：**

- 執行 module 的 --help 會列出 eval 與 baseline（守 rule 08 dead-code trap）。
- test_models 覆蓋：三軸 StrEnum 值、fixture 驗證、negative 的 expect_trigger 必須為 false。
- test_service 覆蓋三態（rule 09）：stub judge 下 pass rate 計算正確、baseline 比對正確觸發回歸、fixture 缺失時 skip。
- test_cli 覆蓋：eval 與 baseline subcommand 存在且以 stub judge 跑通。
- make ci 全綠，且不影響既有 lint_skill_scope.py / lint_skill_overlap.py。

**Scope boundaries：**

- In scope：確定性核心 + models + judges/base.py + judges/agent.py + CLI + tests + 一個示範 trigger_eval.json + skills/skill-trigger-eval/SKILL.md runbook + skills/README.md index。
- Out of scope：judges/api.py、judges/acp.py、CI workflow、scheduler job、自動 fixture 生成、全 skill 覆蓋。

## Risks / Trade-offs

- **LLM judge 非確定性** → baseline 必須帶容忍門檻，否則回歸偵測會 flaky。本 change 核心因 judge 被 stub 而可穩定測試；真 agent judge 的非確定性延到實際使用（Phase 2 之後）處理。
- **fixture 人工維護成本** → 只做高風險家族示範 fixture，並以 B1（lint_skill_overlap.py）的重疊輸出當「該優先投資 fixture 的清單」。
- **Phase 1 無自主 CI gate** → 只能人跑，接受此取捨以換取零金錢成本與零 Usage Policy 風險。
- **fixture schema 與真 judge 輸入漂移**（rule 09 fixture schema）→ 測試用真實 SKILL.md description 當輸入，避免捏造欄位造成「測試綠但生產壞」。
