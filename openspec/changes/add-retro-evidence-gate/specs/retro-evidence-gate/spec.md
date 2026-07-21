# Spec：retro-evidence-gate

> capability 契約：`/pr-retro` 產出「加 rule / hook」action item 的寫入前證據分級與 commit-time 機械強制。
> 詞彙與模式沿用姊妹 capability `pr-review-convergence`（證據形式封閉列舉、三種執行結果、降級不丟、純函式檢查器），作用於不相交子系統（retro 寫入路徑，非 review 迴圈）。

## ADDED Requirements

### Requirement: 每個「加 rule/hook」action item 寫入前必須分級

`/pr-retro` Step 5 產出的每個「新增 rule」或「新增 hook」action item，在任何寫入 always-loaded 面（`.claude/rules/*.md`、`CLAUDE.md`）或註冊 hook 之前，MUST 被歸入且僅歸入以下三層之一：Tier 1（Probed，可機械實測的可證偽宣稱）、Tier 2（Incident-cited，有真實事件佐證但不易廉價重跑）、Tier 3（Subjective，主觀／單一次發生／無可接受證據形式）。分級 MUST 在既有 Promotion Gate（G1/G2/G3）之**上游**發生：未完成分級的 action item MUST NOT 進入 Promotion Gate。

分級的依據 MUST 是「此宣稱有無可接受的證據形式」，而非來源信任度分數（`--source`）。來源分數 MUST NOT 單獨作為升級到 Tier 1 或 Tier 2 的理由。

#### Scenario: 未分級的 action item 被擋在 Promotion Gate 之外

- **WHEN** 一個「新增 rule」action item 尚未被歸入任一 tier
- **THEN** 系統 MUST NOT 對它執行 Promotion Gate G1/G2/G3
  - **AND** 系統 MUST 先要求對它抽出可證偽宣稱並分級

#### Scenario: 高來源分數不等於已驗證

- **WHEN** 一條 lesson 的 `--source` 為 user-stated（分數 8-9）但其技術宣稱無任何 probe 或事件佐證
- **THEN** 系統 MUST NOT 因來源分數高而歸為 Tier 1 或 Tier 2
  - **AND** 系統 MUST 依「有無可接受證據形式」歸為 Tier 3

### Requirement: 證據形式依 lesson 類型封閉列舉且無 catch-all

Evidence Gate MUST 明列各類 lesson 可接受的證據形式，且該表為**封閉列舉**——未列出的類型無可接受形式，MUST 恆歸 Tier 3。表中 MUST NOT 出現 `other` / `etc.` / catch-all 列。最後一列（主觀／可能誤導／建議補充）MUST 標明「無可接受證據形式，恆 park」。

#### Scenario: 主觀類 lesson 無可接受證據形式

- **WHEN** 一條 lesson 的內容為「這條規則的措辭可以更精確 / 建議補充說明」這類無法證偽的主張
- **THEN** 系統 MUST 將其歸為 Tier 3
  - **AND** 系統 MUST NOT 為其提供任何可接受的證據形式繞道

##### Example: 證據形式表（封閉列舉）

- **GIVEN** 以下 lesson 類型與其唯一可接受證據形式：
- **WHEN** 對照分級
- **THEN** 對照結果 MUST 為：

| lesson 類型 | 可接受證據形式 | Tier |
| --- | --- | --- |
| bash 反模式 / hook 攔截 pattern | 正/負樣本 `echo … \| script` 顯示攔/放行如預期 | 1 |
| `paths:` / frontmatter / CLI flag 行為宣稱 | `claude -p` 拋棄式 repo 探針或 failing→passing test 的輸出 | 1 |
| 工具輸出欄位 / 版本相依行為 | 目標平台實跑一次的輸出（CLI 宣稱須附工具版本） | 1 |
| 真實事件教訓（不易廉價重跑） | PR/issue 連結 + 貼原文 quote（雙端 verify） | 2 |
| 精確度 / 可能誤導 / 建議補充 / 品味 | 無可接受形式 | 3（恆 park） |

### Requirement: Tier 1 probe 必有三種執行結果且無效不等於不成立

Tier 1 action item 的 probe 執行 MUST 產生且僅產生三種結果之一，且三者處置相異：（a）跑了、宣稱重現 → 可寫入；（b）跑了、宣稱不成立 → 不得寫入，記錄「未重現」；（c）**根本跑不起來（證據無效）** → 宣稱狀態未知，MUST 先嘗試修復一次，修不好則降級為 Tier 3 進 park，MUST NOT drop，MUST NOT 記為「未重現」。

「證據無效」與「宣稱不成立」MUST 被分開處置——系統 MUST NOT 因 probe 跑不起來而將 lesson 當成已否證而丟棄。

#### Scenario: probe 跑不起來時降級保留而非丟棄

- **WHEN** 一個 Tier 1 action item 的 probe 因指令錯誤而無法執行，且修復一次仍失敗
- **THEN** 系統 MUST 將其降級為 Tier 3 並 park
  - **AND** 系統 MUST NOT 將其記為「未重現」
  - **AND** 系統 MUST NOT 丟棄其標題與描述

#### Scenario: probe 顯示宣稱不成立則不寫入

- **WHEN** 一個 Tier 1 action item 的 probe 成功執行且顯示宣稱不成立
- **THEN** 系統 MUST NOT 將該 rule/hook 寫入
  - **AND** 系統 MUST 記錄「未重現」而非 park

### Requirement: 驗證成本分層

Evidence Gate MUST 以成本分層執行，使多數淘汰發生在零成本的結構檢查：（a）結構檢查——action item 是否已分級、Tier 1/2 是否附證據欄位——MUST 不執行任何指令即可判定；（b）便宜 probe（正/負樣本、failing→passing test 等秒級操作）MUST 於互動式 retro 當場執行；（c）昂貴 probe（如 `claude -p` 拋棄式 repo 探針）MUST 改派 subagent 執行，或降級為 Tier 2 要求貼出 PR 階段已產生的證據。互動式 retro session MUST NOT 被單一昂貴 probe 阻塞。

#### Scenario: 昂貴 probe 不阻塞互動 session

- **WHEN** 一個 Tier 1 action item 需要 `claude -p` 拋棄式 repo 探針才能驗證
- **THEN** 系統 MUST 改派 subagent 執行該 probe，或降級為 Tier 2 要求 PR 階段證據
  - **AND** 系統 MUST NOT 在互動式 retro 主流程中同步等待該 probe

### Requirement: Tier 3 park 與 recurrence 升級契約

Tier 3 action item MUST NOT 寫入任何 always-loaded 面（`.claude/rules/*`、`CLAUDE.md`）或註冊為 hook。Tier 3 MUST 被 park 到既有 mycelium typed-lessons store，以 `confidence ≤ 4` 且狀態 `parked` 記錄，MUST NOT 新增獨立檔案面。

recurrence 升級 MUST 遵循：同類 friction 於後續 retro 再現時 recurrence +1；recurrence ≥ 2 時該候選 MUST「解除 park」重新進入 Evidence Gate；解除 park **僅**使其重新受評，MUST 仍通過 Tier 1 或 Tier 2 證據要求才得寫入。recurrence MUST NOT 單獨構成寫入理由。

#### Scenario: Tier 3 不碰 always-loaded 面

- **WHEN** 一個 action item 被歸為 Tier 3
- **THEN** 系統 MUST NOT 將其寫入 `.claude/rules/*` 或 `CLAUDE.md`
  - **AND** 系統 MUST 將其 park 到 typed-lessons（confidence ≤ 4、狀態 parked）

#### Scenario: recurrence 達標僅解除 park 而不自動寫入

- **WHEN** 一個 parked 候選的 recurrence 由 1 增至 2
- **THEN** 系統 MUST 讓它重新進入 Evidence Gate 受評
  - **AND** 系統 MUST NOT 僅因 recurrence ≥ 2 就將其寫入 always-loaded 面
  - **AND** 系統 MUST 要求其通過 Tier 1 或 Tier 2 證據後才寫入

### Requirement: commit-time lint 分層強制且以純函式暴露

MUST 存在一個 pre-commit lint，對 git-staged diff 檢查證據標記，且其檢查邏輯 MUST 以純函式 `check_rule_evidence(diff_text) -> list[str]` 暴露（回傳失敗訊息清單，空清單代表通過），使負向案例可用合成 fixture 驗證而非只對真實檔案斷言。

強制分層 MUST 為：（a）新增 `.claude/rules/NN-*.md` 檔，或 settings.json 新註冊的 hook 及其 script，缺證據標記 → MUST 以非零 exit 擋 commit；（b）既有 rule 檔新增 section 缺證據標記 → 初期 MUST 為 warn-only（pre-commit 設 `verbose: true` 使警告可見）。lint 接受的證據標記 MUST 包含結構化形式（`<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`）與既有 prose 慣例（`Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`）擇一。

錨點策略 MUST 遵循既有教訓：若 lint 因錨點字串過時而找不到目標，MUST `[FAIL]` 而非靜默通過；錨點比對 MUST 以 UTF-8 讀原始位元組。

#### Scenario: 新 rule 檔缺證據標記擋 commit

- **WHEN** git-staged diff 含一個新增的 `.claude/rules/17-foo.md` 檔且無任何證據標記
- **THEN** `check_rule_evidence` MUST 回傳非空失敗訊息清單
  - **AND** pre-commit hook MUST 以非零 exit 擋下 commit

#### Scenario: 既有檔新增 section 缺標記僅警告

- **WHEN** git-staged diff 在既有 `.claude/rules/13-bash-anti-patterns.md` 新增一個無證據標記的 `##` section
- **THEN** lint MUST 發出可見的 `[WARN]` 而非擋 commit

#### Scenario: 純函式對空輸入不空洞通過

- **WHEN** 以錨點缺失的合成 fixture 呼叫 `check_rule_evidence`
- **THEN** 該函式 MUST 回傳非空失敗訊息清單（MUST NOT 因找不到錨點而回傳空清單）

### Requirement: 本 change 自我約束——always-loaded 面淨增為零

本 change 完成後，`.claude/rules/` 目錄下**每 session 全量載入**（frontmatter 無 `paths:` key）的檔案總行數，相對本 change 前 MUST 淨增 0 行；規範內容 MUST 寫入 rule 11（`skills/**` 觸發載入，非全量），或若新增 section 則其自身 MUST 帶 Tier 1 證據標記。此約束 MUST 以機械檢查強制，且檢查 MUST 以字串內容為錨點、找不到時 `[FAIL]`。

#### Scenario: 治臃腫的 change 不得自己讓 always-loaded 面變肥

- **WHEN** 驗證本 change 對 always-loaded rule 面的影響
- **THEN** 全量載入檔案的總行數淨增 MUST 為 0
  - **AND** 該數字 MUST 被機械檢查印出供操作者檢視
