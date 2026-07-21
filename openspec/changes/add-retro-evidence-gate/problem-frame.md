# Problem Frame：add-retro-evidence-gate

## Frame 型別

主導：**Commanded Behaviour**（retro agent 下「寫入這條 rule / 註冊這個 hook」命令，機器代為執行，並**拒絕**會違反安全約束的命令）
組合：**Simple Workpieces**（`.claude/rules/` + `CLAUDE.md` 的 always-loaded 面是被編輯的工件，帶不變式「只含有證據支撐的內容」）

> 為何不是 Transformation：本問題的核心不是「輸入資料轉輸出資料的完整無多餘」，而是「操作者命令中哪些該被拒絕」與「工件不變式如何在每次編輯後維持」——命令拒絕（Commanded）與工件不變式（Workpieces）才是主導 concern。

## R — 需求（世界狀態）

- **R1**：任一時刻，always-loaded 面（`.claude/rules/*.md` 中 frontmatter 無 `paths:` key 者、`CLAUDE.md`）與所有已註冊 hook 的內容，皆為「有證據支撐」（Tier 1 已 probe，或 Tier 2 有事件佐證）——不多（不含未驗證的主觀／單次內容）。
- **R2**：主觀／單一次發生／無可接受證據形式的教訓（Tier 3）不出現在 always-loaded 面或 hook。
- **R3**：一條教訓的 probe「跑不起來」時，不被當作「已否證」而丟棄；其標題與描述被保留在可再評估之處。
- **R4**：重現型教訓（recurrence ≥ 2）能被重新評估，但其寫入 always-loaded 面**仍**以「有證據支撐」為前提——重現次數本身不使它進入 always-loaded 面。
- **R5**：本 change 自身不使 always-loaded 面淨增（治臃腫的變更不得自己變肥）。

## S — 規格（機器在介面的可觀察行為）

- **S1**（分級 gate）：`/pr-retro` Step 5 對每個「加 rule/hook」action item，MUST 在既有 Promotion Gate 之上游先歸入 Tier 1/2/3；未分級者 MUST NOT 進入 Promotion Gate。分級依「有無可接受證據形式」，MUST NOT 單以 `--source` 分數升級。
- **S2**（證據形式封閉列舉）：Step 5.0 MUST 明列各 lesson 類型的可接受證據形式為封閉列舉，無 catch-all；最後一列（主觀類）MUST 標「無可接受形式，恆 park」。
- **S3**（三分法）：Tier 1 probe 的執行結果 MUST 為重現／未重現／無效之一；「無效」MUST 先修一次，修不好 MUST 降 Tier 3 park，MUST NOT drop、MUST NOT 記為「未重現」。
- **S4**（成本分層）：結構檢查 MUST 零指令即可判定；秒級 probe MUST 當場跑；昂貴 probe MUST 派 subagent 或降 Tier 2；互動 session MUST NOT 被單一昂貴 probe 阻塞。
- **S5**（park 與升級）：Tier 3 MUST park 到 typed-lessons（confidence ≤ 4、parked），MUST NOT 寫 always-loaded 面；recurrence ≥ 2 MUST 只「解除 park」重評，MUST 仍要求 Tier 1/2 證據才寫入。
- **S6**（commit-time lint）：pre-commit lint MUST 以純函式 `check_rule_evidence(diff_text) -> list[str]` 暴露；新 rule 檔／新 hook 缺證據標記 MUST 非零 exit 擋 commit；既有檔新 section 缺標記 MUST warn-only（`verbose: true`）；錨點缺失 MUST `[FAIL]` 而非略過。
- **S7**（自我約束）：機械檢查 MUST 確認本 change 對 always-loaded 面的淨增行數為 0，且該數字 MUST 被印出。

## W — 領域假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | retro agent 會誠實執行分級與 probe（lint 只能驗「有無證據標記」，無法驗「標記是否誠實」——為 runbook 約定，非機械強制）| gate 最大假設風險：agent 可對主觀教訓貼假的 `<!-- verified: probe -->` 繞過。減災：封閉列舉縮小誤判空間、mob review 抽查證據真偽、三分法使「無效證據」難偽裝成重現。殘餘由 golden-transcript harness 收斂（OOS）|
| W2 | mycelium typed-lessons store 可寫入，且 `parked` 狀態被既有回顧流程消費 | park 成無人看的墳場，R3 的「保留」淪為形式。減災：recurrence 使重現者主動浮出；複用既有 mycelium 流程而非新建清單 |
| W3 | pre-commit hook 實際被執行（未被 `git commit --no-verify` 或 CI 略過）| S6 的機械層失效，只剩 S1 doc gate。減災：`make ci` 於 CI 端 `--all-files` 重跑（既有機制）|
| W4 | 「always-loaded」判定（frontmatter 無 `paths:` key）穩定，且 lint 能正確辨識新 rule 檔 vs 既有檔新 section | 自我約束（S7）與分層強制（S6）誤判。減災：以 diff hunk 新 heading 為錨點 + 合成 fixture 覆蓋「編輯既有 section 不誤觸發」|
| W5 | `claude -p` 拋棄式 repo 探針在維護者環境可用（Tier 1 昂貴 probe 路徑）| 昂貴 probe 無法當場或派 subagent 執行。減災：S4 允許降 Tier 2 要求 PR 階段已產生的證據 |
| W6 | 姊妹 change `bound-review-loop-with-evidence-gate` 已上線且持續運作，減少低品質 rule 於 PR review 階段流入 | retro gate 需獨力承擔更大流量，但**不影響正確性**——S1/S6 的把關與 review-loop gate 是否運作無關。此假設只影響「本 change 可以較小」的範圍判斷 |

> W 為 Step 4 假設表的**單一來源**；proposal.md Step 4 只衍生／引用，不另行重編。

## 正確性論證（S ∧ W ⟹ R）

- **R1（always-loaded 只含證據內容）**：由 S1，每個 action item 寫入前先分級且未分級不得寫；由 S2，主觀類無可接受證據形式而恆 Tier 3；由 S5，Tier 3 不寫 always-loaded 面；由 S6，繞過 S1 直接寫檔者於 commit 時被 lint 擋（新檔/新 hook）或警示（既有檔新 section）。故寫入 always-loaded 面者皆帶證據標記 = R1。（殘餘：W1 不成立時假標記可繞過 S1/S6——這是 R1 的已知洞，明列於 W1。）
- **R2（Tier 3 不進 always-loaded）**：S2 使主觀類恆 Tier 3 + S5 使 Tier 3 只 park，直接推出。
- **R3（無效 ≠ 丟棄）**：S3 的三分法把「無效」與「未重現」分離並給無效者保守去處（降 Tier 3 park），直接推出。
- **R4（重現可重評但仍受證據約束）**：S5 明訂 recurrence ≥ 2 只解除 park、仍要求 Tier 1/2，直接推出。
- **R5（本 change 不使面變肥）**：S7 機械檢查淨增 = 0，直接推出。

論證成立（R1 帶 W1 的已知殘餘）。

## Frame Concern 檢查表

### 通用（所有 frame）

- [x] R 只描述世界狀態（always-loaded 面的內容性質），不含機器實作字眼
- [x] S 只描述機器在「retro/commit ↔ rules corpus」介面上的可觀察行為（分級、擋 commit、park、印數字）
- [x] W 每條標明「若不成立的後果」
- [x] S ∧ W ⟹ R 逐條成立（見上，R1 帶已知殘餘）

### Commanded Behaviour 額外

- [x] **列出「不該被執行」的命令，並說明 S 如何拒絕（安全 concern）**：命令「把 Tier 3 主觀教訓寫入 always-loaded 面」MUST 被拒絕——S1 在上游不讓它進 Promotion Gate、S5 強制 park、S6 於 commit 端擋新檔/新 hook。命令「因 recurrence ≥ 2 就寫入未驗證教訓」MUST 被拒絕——S5 要求仍過 Tier 1/2。
- [x] **操作者誤操作／競態下 invariant 仍維持**：agent 略過 Step 5.0 直接 Edit 寫 rule 檔（誤操作）→ S6 commit-time lint 為第二道防線；`--no-verify` 繞過（競態/刻意）→ W3 的 CI `--all-files` 重跑補上。

### Simple Workpieces 額外

- [x] **工件不變式已明列**：always-loaded 面的不變式 = 「每個 section / hook 皆帶證據標記（Tier 1/2）」（= R1）。
- [x] **非法編輯序列被 S 拒絕**：寫入無標記新 rule 檔 / 新 hook（非法編輯）被 S6 以非零 exit 拒絕；既有檔新 section 無標記於起步期 warn（漸進，過渡風險明列於 design Risks）。

## DBC 對應（文件化）

| 合約 | 來源 | 對應落地 / 測試 |
|------|------|----------------|
| require（前置）| GIVEN action item 已分級 / W1 誠實分級 | `check_rule_evidence` 對「無證據標記的新 rule 檔」回傳非空清單（拒絕非法輸入） |
| ensure（後置）| THEN 寫入者皆帶證據標記 / R1 | lint 對 staged diff 的後置斷言 + `test_lint_rule_evidence.py` TC |
| invariant（不變式）| Workpieces concern：always-loaded 面只含證據內容 | 自我約束檢查（S7）淨增 = 0 + 純函式對「錨點缺失／空輸入」必回非空清單 |

> 本 change 無 Pydantic model（產物為 SKILL.md / rule 段落 / lint script）；DBC 以純函式檢查器與測試落地，非 `@field_validator`。
