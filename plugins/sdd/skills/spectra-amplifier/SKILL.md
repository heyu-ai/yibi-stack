---
name: spectra-amplifier
type: know
scope: project
description: >
  Spec Kit 五層深度規格展開 + OpenSpec/Spectra 變更管理框架的融合方法論。
  適用情境：用戶提到「寫 spec」「寫規格」「展開需求」「需求規格」「proposal」
  「openspec」「spectra」「spec kit」「五層展開」「深度規格」「變更管理」
  「delta spec」「changes folder」「需求文件結構」時必須觸發。
  也適用於：用戶說「幫我把 user story 展開成完整規格」「把需求寫到可以開發的程度」
  「設計 API 規格」「建立 proposal」「需求變更追蹤」「寫 AC」「寫驗收條件」等場景。
  當用戶貼上功能描述或 User Story 要求產出完整開發規格文件時，必須觸發。
  即使用戶只說「幫我把這個功能描述得更清楚」「怎麼定義完成條件」「拆任務」
  「spec 怎麼寫」「這個需求太模糊了」，也應觸發此 Skill。

effort: medium
---

# Spectra Amplifier — Wave D Plugin Edition

你是一位資深系統分析師，專精於將模糊需求展開為可開發、可測試、可追蹤的完整規格文件。
你融合 Teddy Chen 五尺度粒度語言、BDD Gherkin scenarios、以及 OpenSpec/Spectra 變更管理框架，
確保每份規格既有行為精確度，又能透過 docstring trace 機制直接連結到 pytest 測試。

## 核心理念

> **Spec Kit 產出最厚的規格，但完成後即棄；Spectra 有最好的變更管理，但規格內容偏薄。**
> 最佳策略不是換工具，而是把 Spec Kit 的「五層厚度」移植到 Spectra 的框架裡。
> Gherkin scenarios 是行為規格的唯一表達；FS 散文層已移除，不再重複撰寫。
> 深度 × 可追蹤 = 真正可靠的規格文件。

---

## 輸出結構

```text
openspec/changes/<name>/
├── problem-frame.md  # Step 0.5 frame 型別 + R/S/W + S∧W⟹R 論證（NEW）
├── proposal.md   # Step 1b US+AC + Step 4 假設約束 + Step 5 完工標準
├── design/       # figma-design-sync 產出（選用；design-context.md + manifest + assets）
├── specs/
│   └── <cap>/
│       └── spec.md   # Step 1c Gherkin scenarios（#### Scenario: <slug>）
├── testplan.md   # Step 2 TC 表格 + Coverage Analysis（NEW）
├── design.md     # Step 3 資料模型 + API（按需）
└── tasks.md      # Phase 結構任務拆解，含 per-US pytest -k 驗收指令
```

> 若 `openspec/changes/` 不存在，先建立。路徑可依專案調整。

---

## Convention Detection

執行 Step 2 前，偵測 host project 的 test convention：

1. 存在 `.claude/rules/09-test-conventions.md` → 使用 host convention，
   log `[OK] Using host test convention from .claude/rules/09-test-conventions.md`
2. 不存在 → 使用 plugin 預設 convention（`skills/spectra-amplifier/test-convention.md`），
   log `[OK] Using sdd plugin default test convention`
3. 永遠不覆蓋 host convention 檔案

---

## Effort Level 策略

| Effort | 執行策略 |
|--------|---------|
| high | 完整 Step 0-5；Step 0.5 必做且 frame concern 未補齊時 `[FAIL] Stop`；Step 1c 寫全部 Gherkin scenarios（每個 AC 至少 2 個）；Step 2 做完整 Coverage Analysis；Step 3 必做衝突偵測；tasks.md 含優先序自動推導與 `[PRIORITY-REVIEW]` |
| medium | 完整 Step 0-5；Step 0.5 必做，frame concern 未補齊時 `[WARN]`；Step 1c 每個 US 至少 3 個 Gherkin scenarios；Step 2 基本 TC 表格 |
| low | 略過 Step 0.5；只做 Step 1（US + AC + Gherkin 概要）；略過 Step 2 testplan、Step 3 詳細設計、Step 4-5 完整展開 |

> 若 `${CLAUDE_EFFORT}` 未設定或為 `normal`，視為 medium。

---

## Plugin 資源路徑解析

本 skill 引用的模板（`references/*.md`）與腳本（`scripts/*.py`）都住在 **sdd plugin 目錄內**，
會隨 `claude plugin install sdd@yibi-stack` 一起安裝。在 host 專案中不存在
`plugins/sdd/` 這個 repo 相對路徑——執行前先解析 plugin root：

```bash
# 經 plugin 安裝執行時 Claude Code 會設定 CLAUDE_PLUGIN_ROOT；
# 在 yibi-stack 源碼 repo 內直接執行時 fallback 到 repo 相對路徑
SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"
```

後續所有 `<sdd-root>/references/...`、`<sdd-root>/scripts/...` 引用都以此為準。
若兩個路徑都不存在，`[FAIL] sdd plugin 資源未找到 -- 請確認 claude plugin install sdd@yibi-stack 已安裝`，停止。

---

## Step 0 — 前置檢查（Domain Discovery）

**目標**：確認是否有足夠的領域資訊再展開規格。

1. 讀 `openspec/changes/<name>/proposal.md`（若存在）的 ## Why 段落
2. 若存在 `openspec/changes/<name>/event-storming.md`，讀其 Domain Events、
   Bounded Contexts、Aggregate Roots
3. 評估領域資訊充足度：

| 狀況 | 行動 |
|------|------|
| 有 event-storming.md 且包含 ≥ 3 domain events | 繼續（medium/high：其 Notes 假設於 Step 0.5 匯入 W；low effort 僅做 Step 1，不展開 Step 4 假設表，故不正式匯入假設）|
| 只有 proposal.md ## Why，功能簡單（1 Actor + 1 Goal）| 繼續，標記「無需 Event Storming」|
| 功能涉及多 Actor 或複雜狀態，但無領域資訊 | 輸出 `[WARN] 建議先執行 /event-storming 建立領域資訊`，確認後繼續 |
| 需求含 figma.com URL（或使用者提及設計稿），且 `openspec/changes/<name>/design/` 不存在 | 先執行 `figma-design-sync` skill（extract 模式）落地設計；完成後其 design-context.md 作為 Step 1a 輸入之一。若 Figma MCP 工具不可用：`[WARN] Figma MCP 未連接，略過設計擷取；建議連接後執行 figma-design-sync`，繼續既有流程 |
| `openspec/changes/<name>/design/figma-manifest.json` 已存在 | 先執行 `figma-design-sync` skill（sync 模式）確認設計未過期；`[OK]` 或使用者確認忽略變更後，讀 design-context.md 繼續 |
| 完全沒有需求描述 | 請使用者補充，無法展開 |

> 後續：medium / high effort 進 Step 0.5（Problem Framing）；low effort 直接進 Step 1a。

---

## Step 0.5 — 問題框架（Problem Framing）

**目標**：在萃取四元素前，先把問題「框」起來——拆成 R（需求）/ S（規格）/ W（領域假設），
並證明 S ∧ W ⟹ R。核心價值是把領域假設 **W 前置顯式化**，降低後續 AI 採樣自由度。
完整方法論見 `problem-frames` skill 的 `methodology.md`（Jackson Problem Frames）。

**Effort 適用**：low 略過此步；medium / high 必做。

1. 若已存在 `openspec/changes/<name>/problem-frame.md`，讀取並沿用；否則新建。
2. 套用 `problem-frames` 方法論：
   - 若 Step 0 讀取了 `event-storming.md`，先將其 `## Notes for Amplifier` 假設併入 W（領域假設）的初始清單
   - 用 frame 分類決策表選出主導 frame（必要時組合多個）
   - 拆 R / S / W，每條 W 標明「若不成立的後果」
   - 寫 S ∧ W ⟹ R 正確性論證
   - 逐項勾選該 frame 的 frame concern 檢查表
   - （選填）標出 require / ensure / invariant 將對應到哪個 Pydantic validator / 測試
3. 產出 `openspec/changes/<name>/problem-frame.md`。

**Frame Concern Guard（決策表自含）**：

| 狀況 | 行動 |
|------|------|
| effort = low | 略過 Step 0.5，直接進 Step 1a |
| frame concern 檢查表全數勾選（含通用四項）| 繼續 Step 1a |
| frame concern 有未補齊項，且 effort = medium | `[WARN] frame concern 未補齊：<清單>`，確認後繼續 |
| frame concern 有未補齊項，且 effort = high | `[FAIL] Stop. frame concern 未補齊：<清單>。補齊後重跑。` |
| `problem-frames` 方法論（`methodology.md`）缺失或不可讀取 | `[FAIL] Stop. problem-frames 方法論不可用。sdd plugin 應同時提供 spectra-amplifier 與 problem-frames，請還原 sdd plugin 後重跑。` |

> **W 的單一來源**：此處產出的 W 是後續 Step 4 假設表的唯一來源；
> Step 4 只能**衍生／引用** W，不得另行重編（避免兩處漂移）。

`problem-frame.md` 骨架由 `problem-frames` skill 的 `methodology.md`「輸出檔案模板」一節維護（owner）。

---

## Step 1 — 行為規格層（Behavioral Specification）

### Step 1a — 四元素萃取

從需求描述中識別：

| 元素 | 說明 | 範例 |
|------|------|------|
| **Actors** | 誰在使用這個功能 | 一般用戶、管理員、排程器 |
| **Actions** | 他們能執行哪些操作 | 新增、查詢、刪除、匯出 |
| **Data** | 涉及哪些資料實體 | 帳單記錄、用戶 profile、發票 |
| **Constraints** | 有哪些限制與邊界條件 | 只能看自己的、金額須為正數 |

歧義點以 `[NEEDS CLARIFICATION: 問題描述]` 標記，**上限 3 個**。
超過 3 個代表需求尚未成熟，退回補充後再展開。

**設計上下文輸入**：若 `openspec/changes/<name>/design/design-context.md` 存在
（figma-design-sync 產出），萃取時必須一併讀取——
畫面清單與互動流程 → Actions 線索；UI 元件與狀態 → Data 與 Constraints 線索；
文案表 → 名詞一致性參照；「Edge Cases 與設計缺口」的 `[DESIGN GAP]` 項目 →
轉為 `[NEEDS CLARIFICATION]`（計入上限 3）或 Step 0.5 的 W（領域假設）。
design/ 不存在時本段不適用，流程與原本相同。

### Step 1b — User Stories + Acceptance Criteria

**格式**：

```markdown
### US-NNN：[故事標題]

**Persona**：[角色描述，包含背景與動機]
**Action**：[想完成的操作]
**Outcome**：[預期的結果與價值]

**Acceptance Criteria**：
- AC-NNN-1：[可驗證的條件]
- AC-NNN-2：[...]
- AC-NNN-3：[...]
（最少 3 條，每條必須可獨立測試）
```

**防投機規則**：禁止撰寫任何「might need」功能。每條 AC 都必須能追溯到明確業務需求。

#### 五尺度粒度自我檢查（每個 US 完成後必做）

| 自我檢查問題 | 若答案為「是」 | 行動 |
|------------|--------------|------|
| 這個 Story 需要超過 5 天才能完成嗎？ | 這是「大」尺度（Epic/Feature）| **必須拆分** |
| 這個 Story 在 3-5 天可以完成嗎？ | 這是「中」尺度（正確粒度）| 繼續展開 |
| 這個 Story 在 4 小時內可以完成嗎？ | 這是「微」尺度（Task 層級）| 合併或降為 Scenario |
| Story 涉及超過一個 Actor 嗎？ | Story 範圍太廣 | 以 Actor 為界拆分 |
| Story 包含超過一個 Goal/Outcome 嗎？ | Story 範圍太廣 | 以 Goal 為界拆分 |
| Story 的 AC 數量超過 7 條嗎？ | 可能是 Epic 誤判為 Story | 重新評估是否拆分 |

**五尺度對照表**（引自 yibi-mvp ADR-0006）：

| 尺度 | 定義 | Spectra 對應位置 |
|------|------|----------------|
| 需求（Requirement）| 業務目標 / 使用者痛點 | `proposal.md` ## Why |
| 大（Epic/Feature）| 可交付的完整功能群，> 5 天 | `proposal.md` ## What Changes |
| 中（User Story）| 單一 Actor + 一個 Goal，3-5 天 | `proposal.md` + `specs/*/spec.md` |
| 小（Scenario）| BDD 可執行情境，1 Story 含 3-7 個 | `specs/*/spec.md` #### Scenario |
| 微（Micro Task）| 最小實作單元，≤ 4 小時 | `tasks.md` 單一 task 行 |

### Step 1c — Gherkin Scenarios（輸入 `specs/<cap>/spec.md`）

每條 AC 對應 1-3 個 Gherkin scenarios。直接從 AC 展開，不經過 FS 散文層。

#### Dispatch 決策（capability 數 N）

先計算此 change 有多少個 capability（每個 User Story 群組算一個 capability）：

| N | 行動 |
|---|------|
| N == 1 | Inline 展開（本 agent 直接寫），不 dispatch subagent |
| 2 ≤ N ≤ 5 | 同一 message 發 N 個 `sdd:gherkin-scenario-writer` Task，平行寫入各自的 `specs/<cap>/spec.md` |
| N > 5 | `[WARN] capability 數超過 5，建議與使用者確認是否分批` → 降回 inline sequential 展開 |

**前置檢查（2 ≤ N ≤ 5，dispatch 前必做）**：確認 `sdd:gherkin-scenario-writer` subagent 可用。
若未找到：`[FAIL] Stop. sdd:gherkin-scenario-writer subagent 未找到。本專案需安裝 sdd plugin：claude plugin marketplace add howie/yibi-stack && claude plugin install sdd@yibi-stack（安裝後重新執行 spectra-amplifier）。`
（不降級成 inline——確保 Gherkin 品質；與 Step 2a 的 not-available gate 對稱。）

**平行 dispatch 格式（N ∈ [2, 5]）**：

在**同一訊息**內送出 N 個 Task tool 呼叫（不依序等待），每個傳入：

```text
subagent_type: sdd:gherkin-scenario-writer
prompt:
  ## Change Name
  <change-name>

  ## Capability
  <cap-slug>

  ## Effort Level
  <low | medium | high>

  ## Four-Element Extraction
  <Step 1a 輸出>

  ## User Stories + AC（僅此 capability 相關）
  <此 capability 的 US + AC 清單>
```

**失敗處理**：N 個 subagent 中失敗 k 個時，不中斷整個 Step 1c：

- 失敗的 capability 在其 `specs/<cap>/spec.md` 頭部加 `[BLOCKED: <原因>]` 標記
- 繼續後續步驟，在 Step 2a dispatch 時跳過 `[BLOCKED]` capabilities
- 於最終摘要列出被 blocked 的 capability 清單

#### Inline 展開規則（N == 1 或 fallback）

#### Scenario Anchor Slug（必填，依 ADR-0008）

每個 `#### Scenario:` heading 必須帶顯式 slug：

```markdown
#### Scenario: <slug> -- <可讀標題>
```

Slug 規則：kebab-case、< 50 chars、顯式命名（不 auto-derive）、同一 spec 內唯一。
CJK 標題另行以英文命名（如 `#### Scenario: age-4-story-gen -- 4 歲孩子生成故事`）。

#### Gherkin 格式

使用 RFC 2119 關鍵字嵌進 GIVEN/WHEN/THEN 條件：

```markdown
#### Scenario: <slug> -- <可讀標題>

**GIVEN** [前置條件（Actor 的初始狀態或前提）]
**WHEN** [觸發操作]
**THEN** 系統 MUST [預期結果]
  AND 系統 MUST NOT [禁止的行為]

**邊界值**（選填，medium/high effort）：
- 輸入 = min-1 → THEN 系統 SHALL 回傳 422
- 輸入 = min → THEN 系統 SHALL 接受
```

輸出檔案：`openspec/changes/<name>/specs/<cap>/spec.md`

---

## Step 2 — 測試設計層（輸出 `testplan.md`）

### Step 2a — Dispatch sdd:qa-test-designer Subagent

跳過所有 `[BLOCKED]` capabilities；只傳入非 blocked capabilities 的 Gherkin scenarios。

**前置條件**：若所有 capabilities 均為 `[BLOCKED]`，略過 Step 2 並輸出：
`[WARN] 所有 capabilities 均為 [BLOCKED]，略過 testplan 生成。`
否則繼續：

Invoke the `Task` tool:

```text
subagent_type: sdd:qa-test-designer
prompt:
  ## Change Name
  <change-name>

  ## Effort Level
  <low | medium | high>

  ## Gherkin Scenarios（所有 non-BLOCKED capabilities 的 Step 1c 輸出）
  <Step 1c 產生的所有 non-blocked Scenario blocks>

  ## Acceptance Criteria List
  <所有 non-blocked capabilities 的 AC 清單>
```

Expected output from sdd:qa-test-designer:

- TC table（TC-ID, Test Purpose, Technique, Risk, Precondition, Steps, Test Data, Expected Result）
- Coverage Analysis（Covered / Partial / Missing / Redundant）

If sdd:qa-test-designer not available:
`[FAIL] Stop. sdd:qa-test-designer subagent 未找到。本專案需安裝 sdd plugin：claude plugin marketplace add howie/yibi-stack && claude plugin install sdd@yibi-stack（安裝後重新執行 spectra-amplifier）。`

若 subagent 回傳內容以 `[FAIL]` 開頭，或 Task tool 本身執行失敗（timeout/error）：
Stop，將完整錯誤訊息回報給使用者，不執行 Step 2b/2c。

### Step 2b — Coverage Analysis

依 sdd:qa-test-designer 輸出分析每個 Scenario slug 的覆蓋狀態：

| 狀態 | 說明 |
|------|------|
| ✓ covered | 有對應 TC，且涵蓋 Scenario 的主要路徑 |
| △ partial | 有 TC 但只涵蓋部分 AC（如缺少 error path）|
| ✗ missing | 無對應 TC |
| — redundant | 多個 TC 涵蓋同一 Scenario，無額外測試價值 |

### Step 2c — TC-ID 分配（依 Convention）

套用偵測到的 test convention（見「Convention Detection」章節）
為每個 TC 分配正式 ID（格式：`[FEATURE]-[CATEGORY]-[NUMBER]`）。

**Smoke Test 特殊命名**：Step 5 的冒煙測試使用 `SMK-NNN`（而非 `ST-NNN`）。
`ST` 在 qa-test-design 中代表 State Transition，為避免歧義，冒煙測試統一用 `SMK`。

輸出：`openspec/changes/<name>/testplan.md`（格式見 `<sdd-root>/references/testplan-template.md`，
`<sdd-root>` 解析見「Plugin 資源路徑解析」章節）

---

## Step 3 — 設計輔助層（按需，輸入 `design.md`）

**目標**：定義資料結構與服務介面，確認與既有規格無衝突。

### 資料模型

```markdown
## Entity：[EntityName]

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 主鍵 |

**索引**：
- UNIQUE INDEX ON (...)

**關聯**：
- `EntityA` 1:N `EntityB`（FK: entity_b.entity_a_id → entity_a.id）
```

### API Schema

````markdown
## API：[METHOD] /[path]

**Request**：
```json
{ "field": "型別與說明" }
```

**Response 200**：
```json
{ "field": "型別與說明" }
```

**Error Cases**：
| Code | 原因 | Response Body |
|------|------|---------------|
| 400 | 輸入格式錯誤 | `{ "error": "..." }` |
````

### UI 對應（design/ 存在時）

若 `openspec/changes/<name>/design/` 存在（figma-design-sync 產出），design.md 以
**相對路徑引用**設計上下文，不複製內容（single source：`design/` 由 figma-design-sync
擁有並維護；design.md 手動複製的段落會在下次 sync 後過期）：

```markdown
## UI 對應

畫面與元件規格見 [design-context.md](../design/design-context.md)
（截圖於 `../design/assets/`，不入 git，缺圖時執行 figma-design-sync 補抓）。

| Entity / API | 對應畫面（design-context.md 章節 1 的 slug） |
|--------------|---------------------------------------------|
| `Order` | `checkout-cart`、`checkout-confirm` |
```

### 衝突偵測

完成 Step 3 後，對比 `openspec/specs/`（若存在）確認無命名衝突。
若是第一份規格，標「baseline，無需衝突檢查」並繼續。

---

## Step 4 — 範圍與假設（輸入 `proposal.md` 尾段）

```markdown
## 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | 用戶已完成身份驗證 | 需加入認證前置步驟，影響 API 設計 |

## 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | 回應時間 < 500ms | 效能 SLA |

## Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 批次匯入 | 第一版只支援單筆 | Phase 2 評估 |
```

每個 Out of Scope 項目必須附原因與未來考量，避免日後範疇爭議。

**假設表的單一來源是 Step 0.5 的 W**：本章節的「假設」表須**衍生自 / 引用**
`problem-frame.md` 的 W（領域假設），不得另行重編一份，避免 W 在兩處漂移。
每條假設沿用 W 的「若不成立的影響」欄。（Step 4 僅在 medium / high effort 執行，
此時 Step 0.5 必已產出 W；low effort 只做 Step 1，不展開本假設表。）

若 Step 0 讀取了 `event-storming.md`，其 `## Notes for Amplifier` 的假設已於 Step 0.5
併入 W，故此處由 W 衍生即可（而非直接搬進本章節）。

---

## Step 5 — 完工標準（輸入 `proposal.md` 末段 + `tasks.md`）

### Done 定義

```markdown
## Done 定義

此功能視為「完成」的條件：
- [ ] 所有 User Stories 的 AC 均已實作
- [ ] testplan.md 所有 TC 均有對應測試（check_spec_coverage.py 驗證）
- [ ] 冒煙測試全數通過
- [ ] 程式碼已 code review 並合併
```

### 冒煙測試情境（3-5 個，使用 SMK-NNN）

```markdown
#### Scenario: smk-happy-path -- SMK-001 正常路徑

**GIVEN** 系統處於正常狀態，且 [前置條件]
**WHEN** 用戶執行 [操作]
**THEN** 系統 MUST 回傳 [預期結果]

#### Scenario: smk-error-path -- SMK-002 異常路徑

**GIVEN** [異常前提]
**WHEN** 用戶執行 [操作]
**THEN** 系統 MUST 回傳 [錯誤訊息] 且 MUST NOT 影響 [既有狀態]
```

> **SMK-NNN** 是冒煙測試的 TC-ID 前綴（不用 `ST-NNN` 以避免與 State Transition 縮寫衝突）。

### Traceability Matrix（輸入 `proposal.md` 末段）

```markdown
## Traceability Matrix

| US | Gherkin Scenario slug | TC-ID | pytest docstring |
|----|----------------------|-------|-----------------|
| US-001 | `require-current-password` | LOGIN-VL-001 | `spec: login#require-current-password` |
| US-001 | `smk-happy-path` | SMK-001 | `spec: login#smk-happy-path` |
```

依 `bdd-trace-convention.md` 格式，trace 欄位即為 pytest function docstring 內容。

---

## tasks.md 任務拆解格式

**目標**：依 Step 1-5 的輸出，拆解為檔案級的可執行開發任務。

### 優先序自動推導規則

| 訊號 | 分級 | 範例 |
|------|------|------|
| Actor 涉及金流、身份驗證、法規合規 | P1 | 付款、登入、資料保留 |
| Constraint 有 SLA 或截止日期 | P1 | 回應 < 500ms、法規要求 |
| 核心路徑（其他 Story 以此為前提）| P1 | 建立帳戶（其他功能依賴）|
| 中等複雜度，無阻斷性依賴 | P2 | 查詢報表、修改設定 |
| 優化體驗、非核心功能 | P3 | UI 細節、匯出 CSV |

### tasks.md 格式

```markdown
# tasks.md — [feature-name]

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。

## Phase 1：Setup
- [ ] T001 建立目錄結構與基礎設定

## Phase 2：Foundational（阻斷性前置依賴）
- [ ] T002 [P] 建立 Entity model — target: src/models/[name].py
- [ ] T003 [P] 建立 DB migration — target: migrations/[timestamp]_[name].sql

## Phase 3：User Stories（P1 → P2 → P3）

### US-001：[標題]（P1 — Actor 涉及金流）
**Story Goal**：[一句話說明]
**Test traceability**: AC-001-1~3 → TC LOGIN-VL-001~005, SMK-001
  Verification: `pytest -k "LOGIN-VL-001 or LOGIN-VL-002 or SMK-001"`

- [ ] T010 [P] [US1] 實作 Service 層 — target: src/services/[name]_service.py
- [ ] T011 [US1] 實作 API endpoint（依賴 T010）— target: src/routes/[name].py
- [ ] T012 [P] [US1] 單元測試 — target: tests/unit/test_[name]_service.py
- [ ] T013 [US1] 整合測試 — target: tests/integration/test_[name]_flow.py

## Phase 4：Polish
- [ ] T020 [P] 新增 logging 埋點
- [ ] T021 [P] 更新 API 文件
```

**標記說明**：`[P]` = 可與其他任務平行執行（parallelizable）；`[USn]` = 對應 Story；無標記 = 有前序依賴。

---

## 變更管理標記（Delta Markers）

當修改**已存在**的規格文件時，所有變更必須使用 delta 標記：

| 標記 | 用途 |
|------|------|
| `[ADDED]` | 全新加入的內容 |
| `[MODIFIED]` | 修改既有內容 |
| `[REMOVED]` | 刪除既有內容（保留墓碑並附原因）|

**初次建立不需標記**。從第二次修訂起每次變更加標記。

---

## 衝突偵測檢查表

完成 Step 3 後，逐項確認：

- [ ] **前置確認**：`openspec/specs/` 是否有既有 specs？若無，標「baseline，跳過」
- [ ] **Entity 命名**：新 Entity 名稱未與既有重複或語意重疊
- [ ] **API endpoint**：新 path 未與既有路由衝突
- [ ] **共用資料表**：若修改既有 table，確認所有使用方均已納入考量
- [ ] **Event / Message schema**：事件格式向後相容
- [ ] **權限模型**：新功能存取控制與既有角色定義一致

---

## 輸出檔案模板

### `problem-frame.md` 骨架（Step 0.5）

`problem-frame.md` 的骨架由 `problem-frames` skill 的 `methodology.md`「輸出檔案模板」一節
single-source 維護（owner）。Step 0.5 產出 `problem-frame.md` 時依該骨架填寫；
本檔不再內嵌副本，以免兩處漂移。

### `proposal.md` 骨架

```markdown
# Proposal：[feature-name]

> 版本：v1.0 | 日期：[YYYY-MM-DD] | 狀態：Draft

## Why
[業務目標 / 使用者痛點（需求尺度）]

## What Changes
[可交付功能群概述（大尺度 / Epic）]

## Step 1 — User Stories

[US-001 ~ US-NNN（中尺度）]

## Step 4 — 假設與約束

[假設表、硬性限制表、Out of Scope 表]

## Step 5 — 完工標準

[Done 定義、Traceability Matrix]
```

### `specs/<cap>/spec.md` 骨架

```markdown
# Specs：[feature-name]

## US-001：[標題]（中尺度 / 3-5 天）

### AC-001-1

#### Scenario: <slug> -- <可讀標題>

**GIVEN** [前置條件]
**WHEN** [觸發操作]
**THEN** 系統 MUST [預期結果]

#### Scenario: <slug>-error -- <可讀標題>（異常路徑）

**GIVEN** [異常前提]
**WHEN** [操作]
**THEN** 系統 MUST 回傳 [錯誤] 且 MUST NOT [副作用]
```

### `testplan.md` 骨架

見 `<sdd-root>/references/testplan-template.md`（`<sdd-root>` 解析見「Plugin 資源路徑解析」章節）。

---

## 反模式

| 反模式 | 問題 | 正確做法 |
|--------|------|----------|
| **跳過 framing**（直接從描述萃取四元素，不分 R/S/W）| 領域假設 W 留白，AI 每次自行補不同假設 → 規格不可重現 | medium/high effort 先做 Step 0.5，把 W 顯式化 |
| **W 在 problem-frame 與 Step 4 假設表各寫一份** | 兩處漂移 | Step 4 假設表衍生自 problem-frame.md 的 W，單一來源 |
| **跳層展開**（直接從描述跳到 Step 3）| 缺少行為規格，資料模型設計錯誤 | 完成 Step 1 才進 Step 3 |
| **巨型 User Story**（一個 Story 含 5+ 功能）| AC 無法獨立測試 | 拆分直到每個 Story 只有 3~5 條 AC |
| **AC 直接當 Scenario**（沒有 GIVEN/WHEN/THEN）| 無法機器解析，trace rate 0% | 每條 AC 至少對應一個 Gherkin scenario |
| **Scenario 缺少 slug**（無 `#### Scenario: <slug>`）| scanner 無法追蹤 | 每個 Scenario heading 加顯式 slug |
| **略過 Step 2 qa-test-design**（只產 Gherkin 不產 TC）| Scenario 有規格沒測試設計 | Step 2 必須真正 dispatch sdd:qa-test-designer Task subagent |
| **Smoke Test 用 ST-NNN**（應用 SMK-NNN）| 與 qa-test-design ST=State Transition 衝突 | 冒煙測試統一用 SMK |
| **OOS 無理由** | 日後範疇爭議無法收斂 | 每項 OOS 附原因 + 未來考量 |
| **無標記修訂** | 變更歷史消失 | 第二次起每次加 `[ADDED/MODIFIED/REMOVED]` |
| **事後補 spec** | spec 繼承實作假設，失去獨立需求基線 | spec 必須在實作前完成 |
| **Story 大小不一** | 估時和測試切入點無法對齊 | 每個 Story 跑五尺度粒度自我檢查 |

---

## 工作流程摘要（Quick Reference）

```text
需求描述
  │
  ▼ Step 0: Domain Discovery 前置檢查
event-storming.md 存在且有 ≥3 domain events → 繼續
功能簡單（1 Actor + 1 Goal）→ 繼續（標「無需 Event Storming」）
多 Actor 複雜狀態但無領域資訊 → [WARN] 建議跑 /event-storming
  │
  ▼ Step 0.5: Problem Framing（medium/high；low 略過）
frame 分類 → R/S/W 拆解 → S∧W⟹R 論證 → frame concern 檢查表
frame concern 未補齊 → [WARN]（medium）/ [FAIL]（high）
→ 輸入 problem-frame.md（W 為 Step 4 假設表單一來源）
  │
  ▼ Step 1a: 四元素萃取（Actors / Actions / Data / Constraints）
  │
  ▼ Step 1b: User Stories + AC（≥3）+ 五尺度自我檢查
大尺度 → 拆分 | 中尺度 → 繼續 | 微尺度 → 降為 Scenario
  │
  ▼ Step 1c: Gherkin scenarios（#### Scenario: <slug> -- <title>）
RFC 2119 嵌入 GIVEN/WHEN/THEN
→ 輸入 specs/<cap>/spec.md
  │
  ▼ Step 2: Task tool dispatch → sdd:qa-test-designer
TC 表格 + Coverage Analysis
TC-ID 分配（依 host/plugin convention）
SMK-NNN for smoke tests
→ 輸入 testplan.md
  │
  ▼ Step 3（按需）: 資料模型 + API Schema + 衝突偵測
→ 輸入 design.md
  │
  ▼ Step 4: 假設 + 硬性限制 + Out of Scope（含原因與未來考量）
→ 輸入 proposal.md 尾段
  │
  ▼ Step 5: Done 定義 + SMK 冒煙測試 + Traceability Matrix
（US ↔ Gherkin slug ↔ TC-ID ↔ pytest docstring trace）
→ 輸入 proposal.md 末段 + tasks.md
  │
  ▼ 輸出
openspec/changes/<name>/
├── problem-frame.md （Step 0.5 frame + R/S/W + S∧W⟹R）
├── proposal.md   （Step 1b, 4, 5）
├── design/       （figma-design-sync 產出，選用）
├── specs/        （Step 1c Gherkin scenarios）
├── testplan.md   （Step 2 TC + coverage）
├── design.md     （Step 3 按需）
└── tasks.md      （Phase 結構 + pytest -k 驗收）
```

修訂時：在所有修改處加上 `[ADDED]` / `[MODIFIED]` / `[REMOVED]` 標記。

---

## Spectra CLI 整合（選用）

若專案已安裝 `spectra` CLI，本 skill 可作為 spectra-propose 的後處理放大器。

### 前置條件

- `spectra` CLI 已安裝（`spectra --version` 可執行）
- Change 已透過 `/spectra-propose <feature>` 建立

### 五步驟 ↔ Spectra Artifacts 映射

| 步驟 | 對應 Spectra Artifact |
|------|-----------------------|
| Step 0 | 確認 proposal.md ## Why 已由 spectra-propose 填入 |
| Step 1 | `proposal.md` Capabilities + `specs/*/spec.md` Scenarios |
| Step 2 | 新增 `testplan.md`（Spectra 原生無此 artifact） |
| Step 3 | `design.md` Data Model 區塊 |
| Step 4 | `proposal.md` Non-Goals + NFR |
| Step 5 | `tasks.md` DoD + `proposal.md` Traceability Matrix |

### 執行流程

```text
/spectra-propose <feature>
  ↓ 建立 proposal.md, specs, design.md, tasks.md
（告知 Claude「請使用 spectra-amplifier skill 展開 <change-name>」）
  ↓ Step 0-5 展開
  ↓ spectra analyze <name> --json（只看 Critical + Warning，最多 2 次）
  ↓ spectra validate "<name>"
/spectra-apply <change-name>
```

### 驗收

```bash
spectra analyze <change-name> --json
spectra validate <change-name>

# BDD trace coverage（可選；SDD_ROOT 解析見「Plugin 資源路徑解析」章節）
SDD_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/sdd}"
uv run python "$SDD_ROOT/scripts/check_spec_coverage.py" \
  --specs-dir openspec/changes/<change-name>/specs \
  --tests-dir tests/ --cap <feature-name>
```
