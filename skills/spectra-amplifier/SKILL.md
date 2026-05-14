---
name: spectra-amplifier
type: know
scope: global
description: >
  Spec Kit 五層深度規格展開 + OpenSpec/Spectra 變更管理框架的融合方法論。
  適用情境：用戶提到「寫 spec」「寫規格」「展開需求」「需求規格」「proposal」
  「openspec」「spectra」「spec kit」「speckit」「五層展開」「深度規格」
  「變更管理」「delta spec」「changes folder」「需求文件結構」時必須觸發。
  也適用於：用戶說「幫我把 user story 展開成完整規格」「把需求寫到可以開發的程度」
  「設計 API 規格」「建立 proposal」「需求變更追蹤」「寫 AC」「寫驗收條件」等場景。
  當用戶貼上功能描述或 User Story 要求產出完整開發規格文件時，必須觸發。
  即使用戶只說「幫我把這個功能描述得更清楚」「怎麼定義完成條件」「拆任務」
  「spec 怎麼寫」「這個需求太模糊了」，也應觸發此 Skill。
---

# Spectra Amplifier — 五層深度規格展開 + 變更管理框架

你是一位資深系統分析師，專精於將模糊需求展開為可開發、可測試、可追蹤的完整規格文件。你融合 Spec Kit 的五層深度展開方法與 OpenSpec/Spectra 的變更管理框架，確保每份規格既有足夠的技術深度，又能追蹤所有歷史變更。

## 核心理念

> **Spec Kit 產出最厚的規格，但完成後即棄；Spectra 有最好的變更管理，但規格內容偏薄。**
> 最佳策略不是換工具，而是把 Spec Kit 的「五層厚度」移植到 Spectra 的框架裡。
> 深度 × 可追蹤 = 真正可靠的規格文件。

## 輸出結構

每個功能的完整規格存放於：

```text
docs/openspec/changes/[feature-name]/
├── proposal.md   # 五層展開完整提案（Layer 1、2、4、5）
├── design.md     # Layer 3：資料模型與 API 設計
├── tasks.md      # 檔案級開發任務拆解（Spec Kit Phase 結構）
└── specs/        # Delta specs（GIVEN/WHEN/THEN + QA 邊界值）
    ├── [feature-name]-core.md
    └── [feature-name]-edge.md
```

> 若 `docs/openspec/` 目錄不存在，先建立它。這個路徑是慣例，可依專案調整。

---

## Effort Level 策略

當前 effort：${CLAUDE_EFFORT}

| Effort | 執行策略 |
|--------|---------|
| high | 完整五層展開；Layer 2 跑全三項 QA 速檢（等價類別 + 邊界值 + 狀態轉移）；Layer 3 必做衝突偵測；tasks.md 含優先序自動推導與 `[PRIORITY-REVIEW]` 提示；specs/ 產出完整邊界值場景 |
| medium | 完整五層展開；Layer 2 依需求選擇 1-2 項 QA 技術；衝突偵測執行；tasks.md 基本 Phase 結構 |
| low | 只做 Layer 1-2，產出 User Stories 與基本 FS；略過 Layer 3 API/資料模型、Layer 4-5 詳細內容 |

> 若 `${CLAUDE_EFFORT}` 未設定或為 `normal`，視為 high。

---

## 五層展開流程

### Layer 1 — User Stories（使用者故事）

**目標**：從模糊描述萃取可操作的使用者故事，強迫釐清需求邊界。

#### 第一步：四元素萃取（Spec Kit 方法）

先從需求描述中識別：

| 元素 | 說明 | 範例 |
|------|------|------|
| **Actors** | 誰在使用這個功能 | 一般用戶、管理員、排程器 |
| **Actions** | 他們能執行哪些操作 | 新增、查詢、刪除、匯出 |
| **Data** | 涉及哪些資料實體 | 帳單記錄、用戶 profile、發票 |
| **Constraints** | 有哪些限制與邊界條件 | 只能看自己的、金額須為正數 |

萃取完畢後，檢查是否有任何歧義點，以 `[NEEDS CLARIFICATION: 問題描述]` 標記。**上限 3 個**。若超過 3 個歧義，代表需求描述尚未成熟，應退回要求補充後再展開。

#### 第二步：撰寫 User Stories

**格式**：

```markdown
### US-NNN：[故事標題]

**Persona**：[角色描述，包含背景與動機]
**Action**：[想完成的操作]
**Outcome**：[預期的結果與價值]

**Acceptance Criteria**：
- AC-NNN-1：[可驗證的條件，使用 Given/When/Then 描述]
- AC-NNN-2：[...]
- AC-NNN-3：[...]
（最少 3 條，每條必須可獨立測試）
```

**防投機規則**：禁止撰寫任何「might need」功能。每條 AC 都必須能追溯到明確的業務需求。沒有 Actor 會用到的功能，不寫進規格。

---

### Layer 2 — 功能規格 + QA 即時檢查

**目標**：將每條 AC 展開為完整的功能規格，立即識別測試邊界。

#### 第一步：AC → 功能規格展開

每條 AC 展開為一條 FS，格式如下：

```markdown
#### FS-NNN：[功能規格標題]

**追溯**：AC-MMM-X（US-MMM）

1. **輸入約束**：MUST 接受 ___；值域為 ___；格式限制為 ___
2. **處理邏輯**：系統 SHALL ___；若 ___ 則 SHALL ___
3. **輸出／副作用**：MUST 回傳 ___；SHALL 觸發 ___；資料庫 SHALL ___
4. **不做什麼**：MUST NOT ___；本規格不負責 ___（原因：___）
5. **錯誤處理**：若 ___ 則 SHALL 回傳 ___（HTTP NNN）並 SHALL 記錄 ___
```

使用 RFC 2119 關鍵字精確描述義務程度：

- `MUST` / `SHALL`：絕對要求
- `SHOULD`：建議但非強制
- `MAY`：可選
- `MUST NOT`：絕對禁止

#### 第二步：QA 即時速檢（三項技術）

每完成一批 FS 後，立即使用 **`qa-test-design` Skill** 的以下三項技術進行速檢：

1. **等價類別**：每個輸入欄位有哪些合法分區、非法分區？各選一個代表值
2. **邊界值分析**：數值、日期、字串長度的邊界是什麼？測試 `min-1, min, max, max+1`
3. **狀態轉移**：功能是否有生命週期狀態（如草稿→審核→發布）？列出所有合法轉移與非法轉移

> 若無狀態轉移，改用 **決策表**（多條件組合）或標註「無狀態，N/A」。

速檢結果轉入 `specs/` 資料夾，以 GIVEN/WHEN/THEN 格式寫出邊界值場景。

---

### Layer 3 — 資料模型 + API

**目標**：定義資料結構與服務介面，確認與既有規格無衝突。

#### 資料模型（輸入 `design.md`）

```markdown
## Entity：[EntityName]

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 主鍵 |
| ... | ... | ... | ... |

**索引**：
- UNIQUE INDEX ON (...)
- INDEX ON (...) — 查詢效能

**關聯**：
- `EntityA` 1:N `EntityB`（FK: entity_b.entity_a_id → entity_a.id）
```

#### API Schema（輸入 `design.md`）

````markdown
## API：[METHOD] /[path]

**Request**：

```json
{
  "field": "型別與說明"
}
```

**Response 200**：

```json
{
  "field": "型別與說明"
}
```

**Error Cases**：

| Code | 原因 | Response Body |
|------|------|---------------|
| 400  | 輸入格式錯誤 | `{ "error": "..." }` |
| 404  | 資源不存在 | `{ "error": "..." }` |

````

#### 衝突偵測

完成 Layer 3 後，使用**衝突偵測檢查表**（見下方）對比 `docs/openspec/specs/` 中的現有規格，識別命名衝突與相依性。若是第一份規格（無既有 specs），標註「baseline，無需衝突檢查」並繼續。

---

### Layer 4 — 假設與約束

**目標**：明確標示所有假設和邊界，防止範疇蔓延。

```markdown
## 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | 用戶已完成身份驗證 | 需加入認證前置步驟，影響 API 設計 |
| A2 | ... | ... |

## 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | 回應時間 < 500ms | 效能 SLA |
| C2 | 資料保留 7 年 | 法規要求 |

## Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 批次匯入 | 第一版只支援單筆 | Phase 2 評估 |
| 多語言 | 目前只需中文 | 國際化時再處理 |
```

每個 Out of Scope 項目都必須附上原因與未來考量，避免日後範疇爭議。

---

### Layer 5 — 可測試性

**目標**：定義「完成」的邊界，確保規格可被驗證。

```markdown
## Done 定義

此功能視為「完成」的條件：
- [ ] 所有 FS-NNN 均已實作
- [ ] 冒煙測試全數通過
- [ ] 監控面板無異常警報
- [ ] 程式碼已 code review 並合併

## 冒煙測試情境（3-5 個）

**ST-001：[正常路徑]**
- GIVEN 系統處於正常狀態，且 [前置條件]
- WHEN 用戶執行 [操作]
- THEN 系統回傳 [預期結果]

**ST-002：[異常路徑]**
- GIVEN [異常前提]
- WHEN 用戶執行 [操作]
- THEN 系統回傳 [錯誤訊息] 且不影響 [既有狀態]

## QA 完整測試建議

使用 **`qa-test-design` Skill** 進行完整測試設計，建議採用技術：
- 高風險路徑 → **風險導向測試**（Risk-Based Testing）
- 多條件邏輯 → **決策表測試**
- 狀態機 → **狀態轉移測試**
```

---

## tasks.md 任務拆解格式

**目標**：依 Layer 1-5 的輸出，拆解為檔案級的可執行開發任務。

採用 **Spec Kit 的 Phase 結構**，優先序依 Layer 1 的四元素自動推導（可事後調整）。

### 優先序自動推導規則

依以下訊號將 User Story 分級，**無需詢問用戶**：

| 訊號 | 分級 | 範例 |
|------|------|------|
| Actor 涉及金流、身份驗證、法規合規 | P1 | 付款、登入、資料保留 |
| Constraint 有 SLA 或截止日期 | P1 | 回應 < 500ms、法規要求 |
| 核心路徑（其他 Story 以此為前提） | P1 | 建立帳戶（其他功能依賴） |
| 中等複雜度，無阻斷性依賴 | P2 | 查詢報表、修改設定 |
| 優化體驗、非核心功能 | P3 | UI 細節、匯出 CSV |

推導完成後，在 `tasks.md` 頂端加一行 `> [PRIORITY-REVIEW]` 提醒用戶確認或調整。

#### tasks.md 格式

```markdown
# tasks.md — [feature-name]

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。
> 如需調整：直接修改各 Phase 中 US 的 (P1/P2/P3) 並重新排序。

## Phase 1：Setup
- [ ] T001 建立目錄結構與基礎設定

## Phase 2：Foundational（阻斷性前置依賴）
- [ ] T002 [P] 建立 Entity model — target: src/models/[name].py
- [ ] T003 [P] 建立 DB migration — target: migrations/[timestamp]_[name].sql

## Phase 3：User Stories（P1 → P2 → P3）

### US-001：[標題]（P1 — Actor 涉及金流）
**Story Goal**：[一句話說明]
**Test Criteria**：FS-001 ~ FS-003 全數通過

- [ ] T010 [P] [US1] 實作 Service 層 — target: src/services/[name]_service.py
- [ ] T011 [US1] 實作 API endpoint（依賴 T010）— target: src/routes/[name].py
- [ ] T012 [P] [US1] 撰寫單元測試 — target: tests/test_[name]_service.py

## Phase 4：Polish & Cross-Cutting Concerns
- [ ] T020 [P] 新增 logging 與監控埋點
- [ ] T021 [P] 更新 API 文件
```

**標記說明**：

- `[P]` = 可與其他 `[P]` 任務平行執行
- `[USn]` = 對應 User Story n
- 無標記 = 有前序依賴，須等待
- `（P1 — 原因）` = 在 Story 標題後標示推導依據，方便 review 時判斷是否合理

---

## 變更管理標記（Delta Markers）

當修改**已存在**的規格文件時（非初次建立），所有變更必須使用 delta 標記：

| 標記 | 用途 | 使用時機 |
|------|------|----------|
| `[ADDED]` | 全新加入的內容 | 新增 FS、新增 Entity 欄位、新增 API |
| `[MODIFIED]` | 修改既有內容 | 變更值域限制、修改處理邏輯、調整 AC |
| `[REMOVED]` | 刪除既有內容 | 保留墓碑（tombstone）並附上原因 |

**初次建立不需標記**。從第二次修訂起，每次變更都加上對應標記。

```markdown
<!-- 範例：修訂 FS-003 -->

#### FS-003：金額驗證 [MODIFIED]
<!-- 原本：金額 > 0 -->
<!-- 修改為：金額 > 0 且 <= 1,000,000（原因：符合法規限額） -->

1. **輸入約束**：MUST 接受正整數；值域為 1 ~ 1,000,000 [MODIFIED]
```

---

## 衝突偵測檢查表

完成 Layer 3 後，逐項確認：

- [ ] **前置確認**：`docs/openspec/specs/` 是否有既有 specs？若無，標註「baseline，無需衝突檢查」並跳過以下項目
- [ ] **Entity 命名**：新 Entity 名稱未與既有 Entity 重複或語意重疊
- [ ] **API endpoint**：新 path 未與既有路由衝突（METHOD + path 組合唯一）
- [ ] **共用資料表**：若修改既有 table，確認所有使用方均已納入考量
- [ ] **Event / Message schema**：事件格式是否向後相容
- [ ] **權限模型**：新功能的存取控制與既有角色定義一致

若有衝突，在 proposal.md 的 Layer 4「假設與約束」中明確記錄解法。

---

## 輸出檔案模板

### `proposal.md` 骨架

```markdown
# Proposal：[feature-name]

> 版本：v1.0 | 日期：[YYYY-MM-DD] | 狀態：Draft / Review / Approved

## Layer 1 — User Stories

[US-001 ~ US-NNN]

## Layer 2 — 功能規格

[FS-001 ~ FS-NNN]

<!-- FS-NNN 放功能規格定義（五維度展開）；Layer 2 QA 速檢產出的邊界值場景另存 specs/。 -->

## Layer 4 — 假設與約束

[假設表、硬性限制表、Out of Scope 表]

## Layer 5 — 可測試性

[Done 定義、冒煙測試、QA 建議]
```

### `design.md` 骨架

```markdown
# Design：[feature-name]

> 版本：v1.0 | 日期：[YYYY-MM-DD]

## Layer 3 — 資料模型

[Entity 定義]

## Layer 3 — API Schema

[API 定義]

## 衝突偵測結果

[通過 / 衝突項目與解法]
```

### `specs/[feature]-core.md` 骨架

```markdown
# Delta Specs：[feature-name]

> 對應規格：`docs/openspec/specs/[feature].md`
> 變更類型：ADDED / MODIFIED

## FS-001：[標題]

**GIVEN** [前置條件]
**WHEN** [觸發操作]
**THEN** [預期結果]

**邊界值測試情境**（來自 Layer 2 QA 速檢）：
- 輸入 = min-1 → 應拒絕（回傳 400）
- 輸入 = min → 應接受
- 輸入 = max → 應接受
- 輸入 = max+1 → 應拒絕（回傳 400）
```

---

## 反模式

| 反模式 | 問題 | 正確做法 |
|--------|------|----------|
| **跳層展開**（直接從描述跳到 Layer 3） | 缺少功能邏輯，資料模型設計錯誤 | 必須完成 Layer 1 和 Layer 2 才能進 Layer 3 |
| **巨型 User Story**（一個 Story 含 5+ 功能） | AC 無法獨立測試，任務拆解失準 | 拆分直到每個 Story 只有 3~5 條 AC |
| **AC 複製貼上當 FS**（沒有真正展開） | 沒有輸入約束、邊界、錯誤處理 | 每條 AC 必須展開為五個維度 |
| **略過 QA 速檢** | 邊界 bug 延遲到開發階段才發現 | Layer 2 完成後立即跑三項速檢 |
| **不做衝突檢查** | 新 API 破壞既有功能 | Layer 3 必須對比既有 specs |
| **OOS 無理由** | 日後範疇爭議無法收斂 | 每個 Out of Scope 項目附原因 + 未來考量 |
| **無標記修訂** | 變更歷史消失，無法追蹤 | 第二次修訂起，每次變更加 delta 標記 |
| **超過 3 個 NEEDS CLARIFICATION** | 需求尚未成熟就強行展開 | 退回補充需求，不要帶著歧義繼續 |
| **事後補 spec**（先寫程式再補文件） | spec 繼承實作的所有假設，失去獨立需求基線 | spec 必須在實作前完成；若已有程式碼，使用 Spectra CLI 整合章節的 Brownfield 逆向工程模式 |

---

## 工作流程摘要（Quick Reference）

```text
需求描述（任意格式）
  │
  ▼ Layer 1
四元素萃取（Actors / Actions / Data / Constraints）
  + User Stories（US-NNN）+ AC（≥3）
  + [NEEDS CLARIFICATION]（≤3）
  │
  ▼ Layer 2
AC → 功能規格（FS-NNN）× 五個維度（RFC 2119）
  + QA 即時速檢（等價類別 / 邊界值 / 狀態轉移）
  → 輸入 specs/*.md
  │
  ▼ Layer 3
資料模型（Entity + 關聯）+ API Schema
  + 衝突偵測（對比既有 openspec）
  → 輸入 design.md
  │
  ▼ Layer 4
假設 + 硬性限制 + Out of Scope（含原因與未來考量）
  → 輸入 proposal.md
  │
  ▼ Layer 5
Done 定義 + 冒煙測試 + QA 技術建議
  → 輸入 proposal.md
  │
  ▼ 輸出
docs/openspec/changes/[feature-name]/
├── proposal.md  （Layer 1, 2, 4, 5）
├── design.md    （Layer 3）
├── tasks.md     （Phase 結構任務拆解）
└── specs/       （GIVEN/WHEN/THEN + QA 邊界值）
```

修訂時：在所有修改處加上 `[ADDED]` / `[MODIFIED]` / `[REMOVED]` 標記。

---

## Spectra CLI 整合（選用）

若專案已安裝 `spectra` CLI 並使用 `spectra-propose` 工作流，本 skill 可作為 spectra-propose 的後處理放大器，填補 artifacts 的規格深度。

### 前置條件

- `spectra` CLI 已安裝（`spectra --version` 可執行）
- Change 已透過 `/spectra-propose <feature>` 建立，artifacts 存在

### 五層展開 ↔ Spectra Artifacts 映射

| 五層展開 | 對應 Spectra Artifact | 動作 |
|---------|----------------------|------|
| Layer 1：User Stories | `proposal.md` 的 Capabilities 區塊 | 為每個 Capability 回填 Persona、完整 AC（≥3），補 `[NEEDS CLARIFICATION]` 歧義標記 |
| Layer 2：功能規格 | `specs/*/spec.md` 的 Requirements | 展開 RFC 2119 五維度 + `FS-NNN` 追溯 ID，跑 QA 速檢，把邊界值補進 Scenarios |
| Layer 3：資料模型 | `design.md` 或 spec 的 `## Data Model` | Brownfield：從 ORM 逆向工程；Greenfield：定義 + `[TBD]` 標記 |
| Layer 4：假設與約束 | `proposal.md` 的 Non-Goals + spec 的 NFR | 補充 Assumptions 表（含「若不成立的影響」）與 Constraints 表 |
| Layer 5：可測試性 | spec 的 Scenarios + `tasks.md` | 補強邊界值、加冒煙測試 GIVEN/WHEN/THEN、填 QA 技術建議 |

### Brownfield vs. Greenfield 判斷

在 Layer 3 和 Layer 5 前先判斷模式：

**Brownfield**（任一符合即是）：

- spec 有 `<!-- @trace` block 含程式碼路徑，或
- 在程式碼庫 grep spec 的 domain 關鍵字（table 名、service 名）有命中

**Greenfield**（以上皆無）：

- 無程式碼存在，spec 是從零定義

| 層 | Brownfield | Greenfield |
|----|-----------|------------|
| Layer 3 資料模型 | 從 ORM model 逆向工程，標注「verify intent」 | 定義 schema，未知欄位標 `[TBD]`，批次 AskUserQuestion |
| Layer 5 邊界值 | grep validator 確認確切值 | 標 `[boundary = TBD]`，批次詢問 |

### 執行流程

```text
/spectra-propose <feature>
  ↓ 建立 proposal.md, specs, design.md, tasks.md
  ↓（Claude 版 Step 11 自動觸發；Gemini 版需手動）
（觸發本 Skill：告知 Claude「請使用 spectra-amplifier skill 展開 <change-name>」）
  ↓ 五層診斷 → 映射填補
  ↓ spectra analyze <name> --json（只看 Critical + Warning）
  ↓ spectra validate "<name>"
/spectra-apply <change-name>
```

### 驗收

```bash
# 填補完成後
spectra analyze <change-name> --json   # 只修 Critical + Warning，最多 2 次
spectra validate "<change-name>"       # 通過才算完成
```

### 與 project-level skill 共存

本 skill 安裝為 user-level（`~/.agents/skills/spectra-amplifier`），作為通用 fallback：

- **有 project-level spectra-amplifier 的專案**（如 yibi-mvp）：project-level 優先，本 skill 不生效
- **沒有 project-level 版的專案**：自動使用本 skill

> 如需讓本 skill 在特定專案生效，確認該專案的 `.claude/skills/` 下沒有同名 skill。
