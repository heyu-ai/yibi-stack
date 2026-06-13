# EFC 論文 → harness-eval 設計與實驗參考筆記

> 論文：*Scaling Laws for Agent Harnesses via Effective Feedback Compute*（arXiv 2605.29682v1，Zhang et al., HIT）
> 對象：本 repo 的 `harness-eval` skill（`skills/harness-eval/SKILL.md` + `tasks/harness_eval/`）
> 日期：2026-06-03
> 性質：方法論參考筆記，不改任何 scanner 程式碼
> 姊妹文件：`docs/harness-eval-effectiveness-review.md`（既有的有效性檢驗報告）

## 0. Provenance Caveat（先講清楚）

arXiv ID `2605.29682` 為**未來日期**（2026-05），且引用**虛構模型**（DeepSeek-V4-Flash、
gpt-5.4-nano）。不論其是否為真實發表的實證結果，本筆記只把它當作**方法論框架參考**
（EFC 因子分解、task-demand 正規化、matched-budget 介入、R²/MAE 驗證協定），
**不**把它當作可引用的實證權威。下文所有「論文宣稱的數字」僅用於說明框架形狀，
不作為本 repo 決策的證據基礎。

## 1. TL;DR

`harness-eval` 目前 D1–D11 全部是**靜態 repo 設定掃描**——CLAUDE.md 是否存在、hooks 是否
註冊、always-on context 是否夠小。論文的整個論點卻是 **runtime trajectory 品質**：harness
能多有效率地把 raw budget 轉成「durable、task-sufficient」的 feedback。

> 論文一句話結論：harness scaling「取決於 raw budget 被轉換成持久、足夠任務所需的 feedback
> 的效率，而非花了多少 compute」。
> 對映到本 repo：`harness-eval` 量得到「結構齊不齊」，量不到「跑起來有沒有效率」——
> 這正是 `docs/harness-eval-effectiveness-review.md` 早已點名的同一個缺口的延伸。

因此本筆記分兩軌：**Track A 設計改善**（把論文概念折進現有評分），與
**Track B 資料收集／實驗**（新增 runtime trace 收集，並用論文的驗證協定檢驗
「harness-eval 分數是否真能預測 agent 成功率」）。

## 2. 論文摘要（場景 / 方法 / 結論）

### 2.1 場景（三層任務 + 七種 harness）

- **三層任務**（oracle 取用度遞減）：
  1. Synthetic 可控（Needle Lookup / State Tracking / Rule Filter，有隱藏狀態與確定答案）
  2. Semi-realistic 可執行（HumanEval 式 code completion + unit-test feedback）
  3. 真實 benchmark 子集（HumanEval、Terminal-Bench 2.0、SWE-bench Verified）
- **七種 harness family H0–H6**：H0 Direct Answer、H1 Checklist Verify、H2 Routed Tools、
  H3 Stateful Memory、H4 High Budget Noisy、H5 Closed Loop、H6 Deep Closed Loop。

### 2.2 方法（核心指標）

- **EFC（Effective Feedback Compute）**：每個 feedback event 算
  `EFC_t = κ · I_t · V_t · R_t · M_t`（κ=10），run-level 加總 `EFC(τ) = Σ EFC_t`。
  四個 [0,1] 因子：**Informativeness（揭露任務相關資訊）**、**Validity（有可靠證據支持）**、
  **Non-redundant Relevance（針對 active subgoal 且不重複）**、**Memory update（改變 plan/state
  並影響後續決策）**。乘積式 → 任一因子=0 則整個 event 貢獻=0（天然 zero-gate）。
- **三變體**：Oracle-EFC（用隱藏狀態，只限 synthetic）／Estimated-EFC（只用 trace 可見特徵
  的 logistic 模型，無需 oracle）／NRS-EFC（Nonredundant Stable，對重複/不穩定訊號加重折扣）。
- **Task demand 正規化**：`D_task = L · H_tool · S_state · (1+N_obs) · (1−V_oracle)`
  （L 最少步數、H_tool 工具選擇熵、S_state 狀態追蹤需求、N_obs 觀察雜訊、V_oracle verifier 可見度）。
- **Harness 效率**：`η = EFC / C_raw`（raw budget 轉成 EFC 的效率）。
- **Scaling 模型**：power-law 失敗率 `E(z) = E_∞ + A·z^(−α)`；以 **R²** 與 **MAE** 評估。

### 2.3 Estimated-EFC 的 9 個 trace 可見特徵 φ(e_t)

這是 Track B 最關鍵的可借用清單——**不需 oracle、純從 trajectory 抽得**：

| 符號 | 特徵 | 含意 |
|---|---|---|
| c_t | checker fired | 是否觸發了驗證 |
| h_t | checker scope | 驗證涵蓋廣度 |
| z_t | tool-result reference | tool 結果是否被後續引用 |
| p_t | plan update | trajectory 計畫是否改變 |
| m_t | memory retention | 資訊是否被保留 |
| a_t | repeated-error avoidance | 是否避開重複錯誤 |
| q_t | observation consistency | 訊號是否穩定 |
| Δ_t | subgoal progress | 是否有可量測推進 |
| ρ_t | trace position | event 在 trajectory 中的位置 |

### 2.4 結論（框架形狀，數字僅供參考）

- task-demand-normalized EFC 大勝 raw-compute baseline（論文宣稱 Oracle-EFC/D_task R²=0.99，
  vs raw tokens R²=0.33）。
- **Matched-budget 介入**：兩組 trajectory 在 token / tool-call / wall-clock / operation /
  raw-cost **完全相同**（mean delta 0.000%），只差 feedback 品質（noisy-redundant vs
  targeted-valid-nonredundant），成功率從 0.27 升到 0.90——把「feedback 品質」與「花費」分離。
- Estimated-EFC 在無 oracle 下仍能還原多數訊號；NRS-EFC 在混合真實 trace 上有效，raw compute
  幾乎零或負 R²。

## 3. 核心對映表（EFC ↔ harness-eval）

| 論文概念 | harness-eval 現況（檔案） | 可借用方向 |
|---|---|---|
| EFC = I·V·R·M（乘積式 zero-gate） | 靜態 D1–D11，無 trace 維度 | 新增 trace-quality 維度（Track B） |
| Informativeness I_t | 無 | tool call 是否揭露 task-relevant 資訊 |
| Validity V_t | D8 trust（`scanners/security.py`）部分相關 | 觀察是否被 checker 驗證 / 來源可靠 |
| Non-redundant Relevance R_t | D7 overlap、D11 redundancy（`rules.py`/`token_economy.py`） | 重複動作去重訊號 |
| Memory update M_t | D1 CLAUDE.md、handover/mycelium | feedback 是否真的改變 plan/state |
| 9 個 trace 特徵 φ(e_t) | `_audit_log.sh`、PostToolUse `duration_ms` | 從 transcript 收集的實驗欄位 |
| Task demand D_task | 絕對分數（`service.py` 聚合） | 用 repo 複雜度正規化，跨 repo 可比 |
| η = EFC / C_raw | D11 字元數估計（`token_economy.py`） | 「有用 context / 總 budget」效率比 |
| Matched-budget 介入 | Cases 1–26 bash fixtures（`13-bash-anti-patterns.md`） | 同任務、兩種 harness config 的 A/B |
| NRS gate `(1+0.35·A_t)` | AP audit log 重複 block | 懲罰重複失敗嘗試 |
| power-law + R²/MAE 驗證 | 無 outcome 資料 | 驗證分數是否真能預測成功率 |

## 4. Track A — 設計改善（折進現有評分，標明對應 scanner）

### A1. Task-demand 正規化（low-effort, medium-impact）

現況：D1–D11 加總為絕對分數，5-file 小 repo 與 500-file 大 repo 直接比不公平
（`docs/harness-eval-effectiveness-review.md` 已點名「加總式 /123 獎勵東西多而非剛好」）。

借用 `D_task` 的精神，定義一個 repo-level 複雜度因子 `D_repo`（LOC、skill 數、hook 數、
rule 數的函數），在 `tasks/harness_eval/service.py` 聚合層輸出
`normalized_score = total / D_repo`。**只動聚合層，不動個別 scanner。**

### A2. D11 改用 η 效率框架（low-effort, medium-impact）

現況：D11 對 always-on 字元數做絕對門檻計分（≤5000 +3、≥20000 扣分）。

借用 `η = EFC/C_raw`：把 D11 的 progressive-disclosure ratio（on-demand / total）明確定位為
「**有用且可漸進揭露的 context 對總 budget 的效率比**」，並在報告文案中以 η 語意呈現。
這強化 `scanners/token_economy.py` 既有的比值，而非新增掃描邏輯。

### A3. NRS 重複失敗訊號（medium-effort, medium-impact）

借用 NRS 的 `(1+0.35·A_t)` 重複懲罰：把 `.claude/hooks/_audit_log.sh` 記錄的**重複 AP block**
視為 harness 低效訊號——若同一個 AP1/AP2 pattern 在 audit log 反覆觸發，代表 hooks 沒能
「教會」agent，harness 的回饋迴路是低效的。可作為 D2（Hooks & 自動化）的一個 penalty 子項。

### A4. 乘積式 zero-gate 通則化（low-effort, doc-only）

論文 `EFC = I·V·R·M` 的乘積結構讓任一因子=0 即整體=0。harness-eval **已經**在兩處用了此模式：
D5（無 meaningful assertion → 整個 D5 語意分=0）與 D3（wildcard allow → 直接 FAIL）。
建議把它寫成一條明列的**設計原則**（「critical 子項缺失 → 該維度乘積歸零」），
供未來新增維度沿用，避免回到純加總式的「東西多就高分」。此項純文件，不改碼。

## 5. Track B — 資料收集與實驗（重點軌）

### B1. Transcript trace 收集器（high-effort, high-impact）

新增模組草案 `tasks/harness_eval/trace/`：解析 Claude Code session JSONL transcript，
逐 event 抽出 §2.3 的 9 個 φ(e_t) 特徵，計算 **Estimated-EFC**（無需 oracle）。
依 rule 04 module 結構（models / service / cli），event 欄位對齊論文標註：
action type、observation type、tool name、checker result、memory update、references to
earlier observations。輸出寫入 SQLite（rule 07 DB pattern），供後續 R²/MAE 分析。

### B2. Matched-budget 資料集（medium-effort, high-impact）

**重用既有的 Cases 1–26 bash anti-pattern fixtures** 當 matched-budget 實驗素材：
每個 case = 一個「任務」；兩種 harness config（AP hooks **on** vs **off**）= 固定 budget、
只變 feedback 品質。量測 proxy：AP hook 是否降低重複失敗嘗試數 / permission prompt 次數。
這是論文 matched-budget 介入在本 repo 最低成本的對應——素材已存在，只缺一支跑兩種 config 的腳本。

### B3. Outcome proxy labels（medium-effort, high-impact）

每個 session 收集三個代理成功指標：CI 的 PASS/WARN/FAIL、permission prompt 次數、
AP block 次數。這些是「agent 成功率」的可觀察 proxy，作為 R²/MAE 驗證的 ground-truth label。
資料來源：`_audit_log.sh`（block 事件）+ CI 結果 + transcript。

### B4. R²/MAE 驗證協定（medium-effort, high-impact）

借用論文的 **prospective holdout** 防 post-hoc 調參：先**凍結** metric 定義
（harness-eval 各維度權重、正規化因子），再跨 N 個 repo 蒐集 `(D-score, outcome)` 配對，
以 R²/MAE 檢驗「harness-eval 分數是否真能預測 agent 成功率」。
holdout 批次的 repo 與評估樣本都必須是未見過的。**這是把 harness-eval 從「專家直覺評分」
升級成「可證偽的預測模型」的關鍵一步**——目前完全沒有 outcome 資料去驗證任何維度的有效性。

## 6. 優先順序清單（impact × effort）

沿用 harness-eval 自身的 TODO 格式 `[track, effort, impact]`：

- `[B4-validate, medium-effort, high-impact]` 先建 outcome proxy + R²/MAE 驗證協定
  （沒有它，下面所有改善都無法證明有效）
- `[B2-matched, medium-effort, high-impact]` 用 Cases 1–26 跑 AP hooks on/off 的 matched-budget A/B
- `[B1-trace, high-effort, high-impact]` transcript φ(e_t) 收集器 MVP（Estimated-EFC）
- `[B3-labels, medium-effort, high-impact]` 接 `_audit_log.sh` + CI 收 outcome label
- `[A1-norm, low-effort, medium-impact]` `D_repo` 正規化分數（service.py 聚合層）
- `[A4-zerogate, low-effort, doc-only]` 乘積式 zero-gate 寫成設計原則
- `[A2-eta, low-effort, medium-impact]` D11 報告文案改用 η 效率比語意
- `[A3-nrs, medium-effort, medium-impact]` audit log 重複 block → D2 penalty 子項

**建議順序**：先 B4（驗證地基）→ B2/B3（最便宜的真資料）→ A 軌（便宜的設計微調）→ B1（最重的收集器）。
理由與論文一致：先有「能不能預測成功率」的量尺，才知道哪個維度值得投資。

## 7. References

- 論文：*Scaling Laws for Agent Harnesses via Effective Feedback Compute*，arXiv 2605.29682v1，
  Zhang, Wang, Xu, Zhu, Che（HIT）。
- 本 repo 對應檔：
  - `skills/harness-eval/SKILL.md`（D1–D11 評分方法論）
  - `tasks/harness_eval/scanners/*.py`（11 個維度掃描器）、`service.py`（聚合）、`models.py`
  - `tasks/harness_eval/scanners/token_economy.py`（D11，η 借用點）
  - `tasks/harness_eval/scanners/security.py`（D8，V_t 借用點）
  - `openspec/changes/enhance-d5-behavior-harness/`（D5 zero-gate 先例）
  - `openspec/changes/add-token-economy-harness/`（D11 門檻）
  - `.claude/hooks/bash-ap1-inline-check.sh`、`bash-ap2-check.py`、`_audit_log.sh`（Cases 1–26、audit log）
  - `.claude/rules/13-bash-anti-patterns.md`（Cases 1–26 來源）
  - `docs/harness-eval-effectiveness-review.md`（既有有效性檢驗，token-economy 缺口先例）
