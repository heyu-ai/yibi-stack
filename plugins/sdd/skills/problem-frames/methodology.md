# Problem Frames 方法論（完整版）

> 本檔為 problem-frames skill 的**單一真實來源（owner）**。
> `SKILL.md` 是給 agent 在 context 內快速執行的**壓縮摘要**；當方法論語意改變時，
> 在此檔修訂，再回頭重新摘要 `SKILL.md`——不要把本檔內容整段複製進 `SKILL.md`。

---

## 核心洞見（Michael Jackson, 2001）

> **需求描述的是「世界」，不是「機器」。**

寫規格時最常見的錯誤，是把「機器要做什麼」和「世界要成立什麼」混為一談。
Problem Frames 強迫你把問題拆成三塊，再用一條推導式把它們串起來：

| 符號 | 名稱 | 活在哪裡 | 範例 |
|------|------|----------|------|
| **R** | Requirement（需求）| 問題領域（世界）| 「使用者只看得到自己的帳單」 |
| **S** | Specification（規格）| 機器與世界的介面 | 「API 以 `request.user_id` 過濾查詢」 |
| **W** | World / Domain knowledge（領域假設）| 世界本身的既有規律 | 「`request.user_id` 已由認證中介層驗證且不可偽造」 |

正確性論證（correctness argument）是：

> **S ∧ W ⟹ R**
> （規格 + 領域假設，必須能「推導出」需求成立。）

---

## 為什麼這條式子能箝制 AI 產出

AI 生成最大的亂源，是它會**自動幫你補上沒寫清楚的領域假設 W，而且每次補的都不一樣**。
EARS、Spec Kit、純 Gherkin 那種半形式化規格把句子結構化了
（WHEN… the system SHALL…），但 **W 幾乎都留白**，AI 就在留白處各憑靈感。

Problem Frames 強迫你把 W 顯式寫出來，AI 能自由發揮的縫隙就少了一大半。
這是「事前收斂」——在採樣前先剪掉可抽樣的範圍。

> 但要誠實：Problem Frames 本身**不是**控制 AI 的魔法。它只負責「規格」這一層。
> 真正讓產出可重現的，是「形式化規格 + 確定性 gate + auto-fix loop」整套組合；
> **是 gate 讓形式化的 W／S／R 有東西可咬**。沒接上 gate，再漂亮的 frame 也只是另一種文件。
> 在本 repo，gate 擴充（contract coverage / frame-concern completeness）屬 Phase 2。

---

## Frame 型別與 Frame Concern

Jackson 把問題歸類成幾種固定「frame 型別」，每一種都帶一個固定的 **frame concern**——
也就是「要證明這個解能成立，你必須補上哪段論證」。這等於給填空題，而不是一張白紙。

| Frame 型別 | 何時選 | 受控/被觀察的領域 | Frame Concern（必須補的論證） |
|------------|--------|------------------|------------------------------|
| **Required Behaviour** | 機器需自動維持某個世界狀態，無人下指令 | 受控領域（causal）| 機器行為 ∧ 領域因果律 ⟹ 受控領域持續維持需求狀態 |
| **Commanded Behaviour** | 操作者下命令、機器代為執行 | 操作者 + 受控領域 | 命令事件 ⟹ 機器正確回應，且拒絕會違反安全約束的命令 |
| **Information Display** | 把世界的真實狀態映射到顯示 | 真實世界 + 顯示 | 顯示內容 ⟹ 與真實世界狀態一致（須明寫延遲／取樣假設）|
| **Simple Workpieces** | 使用者透過工具建立／編輯某種工件 | 工件（被編輯物）| 編輯操作序列 ⟹ 工件結構不變式（invariant）始終維持 |
| **Transformation** | 把輸入資料依規則轉成輸出資料 | 輸入領域 + 輸出領域 | 輸入規則 ∧ 對應規則 ⟹ 輸出完全符合需求且無遺漏／無多餘 |

> 以上是 Jackson 原始的 5 種基本 frame。實務上可依領域擴充
> （例如把外部系統互動、合規稽核獨立成新 frame）；擴充時務必同時定義它的 frame concern，
> 否則新 frame 退化成「沒有填空題的白紙」。

### 多 frame 組合（frame composition）

真實功能常是多個 frame 的組合（例如「使用者編輯草稿（Workpieces）並即時看到字數（Display）」）。
做法：先用主導 frame 立骨架，再把次要 frame 當子問題各自補其 frame concern，
最後檢查 frame 之間的**共享現象（shared phenomena）**是否一致（同一份資料兩個 frame 的假設不能互相矛盾）。

---

## Frame Concern 檢查表

每個 frame 完成 R/S/W 後，逐項勾選對應 concern；任何一項打 ✗ 代表論證有洞，須補。

### 通用（所有 frame 都要過）

- [ ] R 只描述世界狀態，不含任何「機器內部怎麼做」的字眼
- [ ] S 只描述機器在「機器↔世界介面」上的可觀察行為（shared phenomena）
- [ ] W 列出所有「不是機器保證、而是世界既有」的假設，且每條都標明「若不成立的後果」
- [ ] S ∧ W ⟹ R 這條推導確實成立（逐條 R 都能由 S 與 W 推出）

### Required Behaviour 額外

- [ ] 領域因果律（W）足以保證機器動作會傳播成需求狀態（不是「機器發出指令」就等於「世界照做」）

### Commanded Behaviour 額外

- [ ] 列出「不該被執行」的命令，並說明 S 如何拒絕（安全 concern）
- [ ] 操作者誤操作／競態下，invariant 仍維持

### Information Display 額外

- [ ] 顯示與真實世界之間的延遲／取樣頻率假設已寫進 W
- [ ] 真實世界不可觀測的部分（W 假設拿不到）已標為 OOS 或顯式 fallback

### Simple Workpieces 額外

- [ ] 工件不變式（invariant）已明列；每個編輯操作後都維持
- [ ] 非法編輯序列（會破壞 invariant）已被 S 拒絕

### Transformation 額外

- [ ] 輸入領域的所有合法值都有對應輸出（完整性）
- [ ] 不產生需求未要求的輸出（無多餘）

---

## Design by Contract 對應（文件化，強制屬 Phase 2）

Bertrand Meyer 的 require / ensure / invariant 是 frame concern 的**執行期化身**：
frame concern 講「要證明什麼」，DBC 講「在 runtime 用什麼擋」。
在本 repo（Python / Pydantic / Click），runtime 合約機制就是 **Pydantic validators**（見 rule 05）。

| DBC 概念 | 來自 frame 的哪裡 | 本 repo 落地（rule 05）| qa-test-design 對應 |
|----------|------------------|----------------------|--------------------|
| **require**（前置條件）| Gherkin GIVEN／W 假設 | `@field_validator`：拒絕非法輸入 | Decision Table 的「條件」欄 |
| **ensure**（後置條件）| Gherkin THEN／R 需求 | 服務層回傳值的後置斷言 + 對應測試 | Decision Table 的「預期結果」欄 |
| **invariant**（不變式）| Workpieces frame concern | `@model_validator(mode="after")`：跨欄位一致性 | State Transition 的「非法轉移被拒」案例 |

> **本次（方法論優先）只做「文件化對應」**：在規格裡寫下 require/ensure/invariant，
> 並指出它將對應到哪個 Pydantic validator／測試。
> **不**建立「合約沒對應測試就 CI fail」的強制 gate——那是 Phase 2（見 SKILL.md 末段）。

---

## Worked Example：「家長只能查看自己孩子的睡眠紀錄」

**模糊需求（輸入）**：家長登入後可以看孩子的睡眠紀錄，但不能看別人家小孩的。

### Step 1 — Frame 分類

主導 frame = **Information Display**（把「孩子的睡眠紀錄」這個世界狀態映射到家長的畫面）；
次要 frame = **Commanded Behaviour**（家長下「查詢」命令）。

### Step 2 — R / S / W 拆解

- **R（需求，世界狀態）**：任一家長 `P` 在畫面上看到的睡眠紀錄集合，
  恰等於「`P` 名下孩子」的睡眠紀錄集合——不多（不含他人孩子）、不少（不漏自己孩子）。
- **S（規格，機器介面行為）**：
  - `GET /sleep-records` MUST 以 `request.parent_id` 過濾，只回傳
    `child.parent_id == request.parent_id` 的紀錄。
  - 查無資料時 MUST 回傳空集合（200），MUST NOT 回傳他人資料或 500。
- **W（領域假設）**：
  - W1：`request.parent_id` 由認證中介層設定，已驗證、不可被請求端偽造。
    （若不成立：任何人可冒充家長 → 需在 S 增加授權檢查，整個 API 設計改變。）
  - W2：`child.parent_id` 外鍵在寫入時即固定，不會在查詢期間被竄改。
    （若不成立：需加查詢期一致性鎖。）

### Step 3 — 正確性論證 S ∧ W ⟹ R

由 S，回傳集合 = `{r | r.child.parent_id == request.parent_id}`。
由 W1，`request.parent_id` 即真正登入的家長 `P`。
由 W2，`child.parent_id` 在查詢期間穩定。
故回傳集合 = `P` 名下孩子的紀錄，恰好 = R。**論證成立。**

### Step 4 — Frame Concern 勾選（Information Display + Commanded）

- [x] 通用四項
- [x] Display：延遲假設——睡眠紀錄可接受最終一致（W 補上「寫入後 ≤1s 可見」）
- [x] Commanded：拒絕命令——未登入請求 MUST 回 401（安全 concern）

### Step 5 — DBC 對應（文件化）

- require：`request.parent_id` 非空且為合法 UUID → `@field_validator`
- ensure：回傳的每筆 `record.child.parent_id == request.parent_id` → 服務層後置斷言 + TC
- invariant：（本例無跨欄位工件不變式）

→ 這份 `problem-frame.md` 接著交給 spectra-amplifier：
W1／W2 直接成為 Step 4 假設表的內容（單一來源，不另行重編；唯一直接傳遞的 leg）；
R／S 成為 Step 1 User Story 與 Gherkin scenario 的骨架；
DBC 對應**經 Gherkin／AC 間接影響** Step 2 qa-test-designer 設計 Decision Table
（qa-test-designer 只收 Gherkin／AC，problem-frame.md 不直接傳入其 dispatch）。

---

## 輸出檔案模板（`problem-frame.md` 骨架，owner）

獨立執行本 skill 時，依此骨架產出 `openspec/changes/<name>/problem-frame.md`。
本節是此骨架的**單一真實來源（owner）**；spectra-amplifier Step 0.5 亦依此骨架產出，
不另行內嵌副本（避免兩處漂移）。

```markdown
# Problem Frame：[feature-name]

## Frame 型別
主導：[Required Behaviour | Commanded Behaviour | Information Display | Simple Workpieces | Transformation]
（組合：[次要 frame，若有]）

## R — 需求（世界狀態）
[只描述世界該成立什麼，不含機器怎麼做]

## S — 規格（機器在介面的可觀察行為）
[機器在「機器↔世界介面」上 MUST / MUST NOT 的行為]

## W — 領域假設
| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | [世界既有、非機器保證的前提] | [後果] |

## 正確性論證（S ∧ W ⟹ R）
[逐條說明 S 加上 W 如何推導出 R 成立]

## Frame Concern 檢查表
- [ ] 通用：R 只描述世界 / S 只描述介面行為 / W 每條標後果 / S∧W⟹R 成立
- [ ] [該 frame 的額外 concern 項目]

## DBC 對應（選填，文件化）
| 合約 | 來源 | 對應 Pydantic validator / 測試 |
|------|------|------------------------------|
| require | GIVEN / W | `@field_validator` ... |
| ensure  | THEN / R  | 後置斷言 + TC ... |
| invariant | Workpieces concern | `@model_validator(mode="after")` ... |
```

---

## 反模式

| 反模式 | 問題 | 正確做法 |
|--------|------|----------|
| R 裡寫機器實作 | 需求綁死實作，失去獨立基線 | R 只描述世界狀態，機器怎麼做留給 S |
| W 留白 | AI 自行補假設、每次不同 → 不可重現 | 顯式列出每條 W，並標「若不成立的後果」|
| 跳過 frame 分類 | 不知道該補哪段 concern，論證有洞 | 先分類 frame，再照其 frame concern 填空 |
| 多 frame 共享現象矛盾 | 同份資料兩個 frame 假設打架 | 組合後檢查 shared phenomena 一致性 |
| W 在 problem-frame 與 Step 4 假設表各寫一份 | W 兩處漂移 | W 以 problem-frame.md 為單一來源，Step 4 衍生／引用 |
