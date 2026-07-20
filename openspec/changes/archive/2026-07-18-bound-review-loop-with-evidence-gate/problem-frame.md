# Problem Frame：bound-review-loop-with-evidence-gate

## Frame 型別

主導：**Transformation**（輸入領域＝各 voice 提出的 finding 串流；輸出領域＝每筆 finding 的
處置（blocking / deferred）與該輪的 merge 決策。核心 concern 是「完整性」與「無多餘」——
這正是「只進不出」的反面：每筆 finding 都必須有去處，且機器不得無中生有）

組合（次要 frame，各自補其 concern）：

- **Required Behaviour** — 機器須自動維持「review 迴圈到達終端狀態」，無人下指令。
- **Commanded Behaviour** — merge 為受安全約束的命令；circuit breaker 將裁決權交還操作者。

**共享現象一致性檢查**：三個 frame 共享 `BlockingSet` 這份資料。Transformation 產生它、
Required Behaviour 以「它為空」作為終止條件之一、Commanded Behaviour 以「它為空」作為
merge 命令的守衛。三者對 `BlockingSet` 的假設一致：它在 `BlockingSetComputed` 後不再變動，
且同一輪內唯一。無矛盾。

## R — 需求（世界狀態）

- **R1（安全）**：帶有可證實缺陷的 PR 不會被 merge。
- **R2（活性 / 收斂）**：不帶可證實缺陷的 PR 在有限輪數內被 merge，或被轉交人類裁決；
  不存在使用者必須靠疲勞才能離開的狀態。
- **R3（不遺失）**：每一筆被提出的 finding 都有明確去處——擋下 merge、或留有可查的紀錄；
  沒有任何 finding 無聲消失。
- **R4（可複驗）**：擋下 merge 的每個理由，第三方都能以一條指令複驗其真偽，而非只能閱讀論述。

## S — 規格（機器在介面的可觀察行為）

- **S1**：機器 MUST 對每筆收到的 finding 指派恰好一個處置——blocking 或 deferred。
- **S2**：機器 MUST 將 `Evidence:` 欄位缺漏或格式不符的 finding 指派為 deferred，且 MUST NOT
  為此執行任何指令（結構檢查）。
- **S3**：機器 MUST 將 severity 為 Actionable NIT 的 finding 指派為 deferred，與其證據有無無關。
- **S4**：機器 MUST 將 Round 2 中 severity 非 Critical 的 finding 指派為 deferred。
- **S5**：機器 MUST NOT 進入第 3 輪 review。
- **S6**：BlockingSet 非空時，機器 MUST NOT 授權 merge。
- **S7**：Round 2 結束且 BlockingSet 非空時，機器 MUST 將裁決轉交操作者（circuit breaker 三選項）。
- **S8**：機器 MUST 對每筆 deferred finding 輸出其原標題、描述與降級理由。
- **S9**：機器 MUST 執行每筆 Critical finding 的證據指令，並 MUST 將結果分為三類：
  **重現**（留在 blocking）、**未重現**（自 blocking 移除並記錄）、
  **無效**（指令無法執行）——無效者 MUST NOT 與未重現同等處置，MUST 降級為 Important 進 deferred。
- **S10**：機器 MUST 對降級的 Important 建立至多一張標記 `deferred-from-review` 的 issue；
  MUST NOT 為 Actionable NIT 建立 issue。
- **S11**：機器 MUST 於 Round 1 記錄 baseline head SHA，並 MUST 將 Round 2 的審查面界定為
  該 baseline 之後的 commit range。

## W — 領域假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | reviewer 有能力僅憑 diff 導出可執行的證據指令 | 各證據類型強度不同：doc 事實錯誤與命名一致性可純由 diff 導出；test gap 的 mutation 描述可導出；**logic / security bug 的 repro 最脆弱**。若不成立，該類 finding 實質不再 blocking，閘門退化為「外部 voice 提的 logic bug 都不擋」——與設計意圖相反。S9 的三分法與「logic bug 改收 failure scenario」即為對此假設的減災 |
| W2 | 每輪 review summary 持續被貼為 PR comment（既有行為） | 降級的 NIT 將無任何紀錄，R3 不成立 |
| W3 | `pr-flow:issue-triage` 會實際處理 `deferred-from-review` 標籤的 issue | Important 的降級出口成為墳場；R3 表面成立而實質不成立，且製造「有在追蹤」的錯覺 |
| W4 | lead 會遵守「Critical 證據必跑」的約定 | lead 為 LLM，此為 runbook 約定而非機械強制。若不成立，無效證據得以擋 merge（R4 不成立），或真缺陷被誤 drop（R1 不成立） |
| W5 | 2 輪足以解決多數 PR 的 Critical | circuit breaker 由例外路徑變為常態路徑，人類裁決頻率上升。**注意：此假設不影響 R2**——終止由 S5 無條件保證 |
| W6 | codex / agy 的 read-only sandbox 與 skill-hijack guard 不會為了證據閘門而放寬 | 放寬即重現 agentic 探索失效模式（reviewer 讀 node_modules、跑 build、產出無結論海量輸出），R4 與 R1 一併失效 |
| W7 | PR 作者不會在 Round 2 期間持續推入與 fix 無關的大型變更 | Round 2 的審查面可能大於 Round 1，使「Round 2 成本低於 Round 1」的預期不成立。**注意：此假設不影響 R2**——終止不依賴審查面大小 |
| W8 | 三個 voice 的輸出格式偵測器（缺 review 標題即 `[FAIL]`）在新增 `Evidence:` 欄位後仍正常運作 | 新欄位若破壞既有 agentic-hijack 偵測，非 review 輸出將靜默流入彙整階段 |

## 正確性論證（S ∧ W ⟹ R）

**R2（活性 / 收斂）⟸ S5，無條件。** 這是本設計最強的一條，且值得明白寫出它的強度來源：
終止**不依賴任何 W**。S5 是硬上限——不存在第 3 輪，因此迴圈必於 Round 2 結束時離開，
出口為 merge（S6 的守衛為空）或人類裁決（S7）。W5（2 輪夠用）與 W7（審查面不膨脹）
若不成立，只會使 circuit breaker 變頻繁或成本上升，**不會使迴圈不終止**。

> **反面對照（修正一項先前的錯誤宣稱）**：R2 **不是**由「審查面嚴格遞減」推出的。
> Round 1 的審查面為 `base..baseline`，Round 2 為 `baseline..HEAD`——這兩個 commit range
> **不相交，並非子集關係**，且 Round 2 的行數不保證小於 Round 1（W7 不成立時反而更大）。
> 審查面縮限（S11）的作用是降低 finding 生成量與成本，是效率與品質性質，**不是終止的證明**。
> 把兩者混為一談，會讓人誤以為 W7 不成立時收斂保證就失效——實際上不會。

**R1（安全）⟸ S6 ∧ S9 ∧ W4。** S6 保證 BlockingSet 非空時不 merge。S9 保證留在 BlockingSet
的 Critical 都經實際執行且重現，因此「可證實缺陷」確實擋住了 merge。W4 是這條的弱點：
S9 的執行為 runbook 約定，lead 若跳過，未經證實的 finding 會擋 merge（傷 R4）或
真缺陷被誤 drop（傷 R1）。S9 的三分法把「無效」與「未重現」分開，正是為了避免
「指令跑不起來」被當成「缺陷不存在」而誤 drop——該分法直接支撐 R1。

**R3（不遺失）⟸ S1 ∧ S8 ∧ S10 ∧ W2 ∧ W3。** S1 保證每筆 finding 恰有一個處置（Transformation
的完整性 concern），S8 保證 deferred 者仍帶完整內容與理由，故機器層面無遺失。跨出機器之後
則依賴世界：NIT 靠 W2（PR comment 存在），Important 靠 W3（有人做 triage）。
兩條 W 皆為「世界既有、非機器保證」，故列於 W 而非 S。

**R4（可複驗）⟸ S2 ∧ S9 ∧ W1。** S2 使無證據者無法進入 blocking，S9 使 Critical 的證據
被實際執行過，故每個擋 merge 的理由都已被複驗至少一次。W1 是這條的前提也是其最大風險：
reviewer 若寫不出可執行指令，R4 表面達成（blocking 的都有證據）而實質縮水
（真缺陷因寫不出指令而未進 blocking）。

## Frame Concern 檢查表

**通用（所有 frame）**：

- [x] R 只描述世界狀態，不含任何「機器內部怎麼做」的字眼 —— R1~R4 皆以 PR、finding、
      人的可複驗性描述，未提及 aggregator、prompt 欄位或輪次實作
- [x] S 只描述機器在「機器↔世界介面」上的可觀察行為 —— S1~S11 皆為處置指派、
      merge 授權與否、輸出內容、是否執行指令等外部可觀察事件
- [x] W 列出所有「不是機器保證、而是世界既有」的假設，且每條都標明「若不成立的後果」
      —— W1~W8 共 8 條，每條皆有後果欄
- [x] S ∧ W ⟹ R 這條推導確實成立 —— R1~R4 逐條推導如上，且明確標出各條所依賴的 W

**Transformation 額外**：

- [x] 輸入領域的所有合法值都有對應輸出（完整性）—— S1 保證每筆 finding 恰有一個處置；
      Severity × Evidence 有無 × 輪次的組合皆已由 S2 / S3 / S4 / S9 覆蓋，無落空格
- [x] 不產生需求未要求的輸出（無多餘）—— S10 限制 issue 至多一張且 NIT 不建；
      機器不得無中生有 finding；deferred 不轉為新的 blocking

**Required Behaviour 額外**：

- [x] 領域因果律（W）足以保證機器動作會傳播成需求狀態 —— **本條特別成立**：終止由 S5
      無條件保證，不依賴任何 W 的因果傳播。此為刻意的設計選擇（見上方論證的反面對照）

**Commanded Behaviour 額外**：

- [x] 列出「不該被執行」的命令，並說明 S 如何拒絕 —— 不該執行的命令為
      「BlockingSet 非空時 merge」，由 S6 拒絕；以及「進入第 3 輪」，由 S5 拒絕
- [x] 操作者誤操作／競態下，invariant 仍維持 —— PR 於 review 期間被 out-of-band merge 或
      關閉：既有 SKILL.md 已有 PR status recheck 決策表，維持不變；作者於 Round 2 期間
      推入新 commit：由 S11 界定的 range 自然涵蓋，且 W7 記錄其成本影響

## DBC 對應（選填，文件化）

本 change 的產物為 SKILL.md runbook 與其驗證測試，**無 Pydantic model**，故 require / ensure
以測試而非 validator 落地。

| 合約 | 來源 | 對應 Pydantic validator / 測試 |
|------|------|------------------------------|
| require | W1（reviewer 產得出證據）、W8（偵測器仍運作） | 無 runtime validator；W1 於 Step 2 testplan 以「無證據 finding 必降級」的 TC 覆蓋 |
| ensure | R2 / S5（不存在第 3 輪）、R3 / S1（每筆 finding 有處置） | `test_convergence_contract.py`：輪數契約明文存在、NIT 約定句已移除 |
| invariant | Transformation 完整性（每筆 finding 恰一處置）、`ReviewRound` 的 RoundNumber ≤ 2 | `test_convergence_contract.py`：行數預算、證據分類表五類齊備、circuit breaker 舊門檻已移除 |
