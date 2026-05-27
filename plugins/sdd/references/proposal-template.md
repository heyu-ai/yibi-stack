# Proposal：{{change-name}}

> 版本：v1.0 | 日期：{{date}} | 狀態：Draft

## 背景

{{背景說明：目前痛點、現有機制的限制、為什麼需要這個 change}}

---

## Step 1 — User Stories

### 四元素萃取

| 元素 | 內容 |
|------|------|
| **Actors** | {{誰會用到這個功能：使用者角色、系統、外部服務}} |
| **Actions** | {{他們會做什麼動作：動詞 + 受詞}} |
| **Data** | {{涉及哪些資料：檔案路徑、DB table、API response}} |
| **Constraints** | {{硬性限制：不能做什麼、效能要求、安全要求}} |

---

### US-001：{{user-story-title}}

**Persona**：{{使用者角色，一句話描述}}
**Action**：{{他們想完成的動作}}
**Outcome**：{{成功後他們看到/感受到什麼}}

**Acceptance Criteria**：

- AC-001-1：GIVEN {{前置條件}} WHEN {{操作}} THEN {{期望結果}}
- AC-001-2：GIVEN {{前置條件}} WHEN {{操作}} THEN {{期望結果}}

---

## Step 1c — Gherkin Scenarios

> Gherkin scenarios 請寫入 `specs/<cap>/spec.md`（`#### Scenario: <slug> -- <title>` 格式）。
> 本 proposal.md 只記錄 US + AC；scenario slug 透過 Traceability Matrix 追溯。

---

## Step 4 — 假設與約束

### 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | {{假設}} | {{影響描述}} |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | {{限制描述}} | {{來源：安全性原則 / 框架設計 / 外部 API}} |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| {{功能}} | {{原因}} | {{未來是否考慮}} |

---

## Step 5 — 完工標準

### Done 定義

此功能視為「完成」的條件：

- [ ] US-001 的 Gherkin scenarios 全部通過
- [ ] {{測試覆蓋條件}}
- [ ] 向後相容驗證通過

### 冒煙測試情境

### SMK-001：{{scenario-title}}

- GIVEN {{前置條件}}
- WHEN {{操作}}
- THEN {{期望結果}}

### QA 技術建議

- {{測試策略：等價類別、邊界值、決策表、冪等性測試等}}
