---
name: event-storming
type: know
scope: global
description: >
  領域發現前置 skill，在開始寫 spec 之前使用。
  適用情境：「我們要做什麼功能」「領域事件有哪些」「系統邊界怎麼畫」「哪些是關鍵業務規則」
  「限界上下文」「aggregate」「domain event」「event storming」「領域建模」。
  spectra-amplifier Step 0 偵測缺少領域資訊時會建議先跑此 skill。

effort: medium
---

# Event Storming Skill

> **Status: draft**
> 本次只設計接口 + handoff artifact 規格。
> 完整六色貼紙、Pivotal Events、Saga、Bounded Context 深度識別等內容後續 PR。

---

## 核心理念

Event Storming 是領域發現工具，不是規格工具。
它的輸出（domain events, bounded contexts, aggregate roots）是 spectra-amplifier
Step 1 的前置輸入；沒有領域資訊就展開規格，等於在沙灘上蓋房子。

---

## When to Use

- 開始寫 spec 之前（特別是涉及多個 Actor 或複雜狀態轉換的功能）
- `proposal.md` ## Why 段落寫好後，但 ## What Changes 尚未展開時
- spectra-amplifier Step 0 提示「缺少領域資訊」時
- 使用者說「幫我把這個需求的邊界畫清楚」時

---

## 最小可用輸出（本次 draft 範圍）

輸出三個核心領域產物，寫入 `openspec/changes/<name>/event-storming.md`：

| 產物 | 最少數量 | 說明 |
|------|---------|------|
| Domain Events | ≥ 3 | 系統中發生的重要事情（過去式動詞，如「訂單已建立」） |
| Bounded Contexts | ≥ 1 | 相關領域事件和規則的邊界 |
| Aggregate Roots | ≥ 1 | 每個 Bounded Context 的一致性邊界實體 |

---

## Steps

### Step 1 — 領域事件識別

1. 請使用者用一句話描述「系統中最重要的事情發生了什麼」
2. 將所有提到的業務動作轉為**過去式事件**（如「用戶已登入」「訂單已建立」）
3. 識別觸發每個事件的 Command（誰做了什麼）
4. 識別每個事件的 Policy（若 X 發生則 Y）
5. 至少確認 3 個核心 Domain Events

```markdown
## Domain Events（範例）
- 「用戶已完成電話驗證」— Command: 用戶送出驗證碼
- 「家長帳號已建立」— Command: 用戶填寫家長資料
- 「兒童個人資料已建立」— Policy: 家長帳號建立後觸發
```

### Step 2 — Bounded Context 劃分

根據 Domain Events 的主題群，識別自然邊界：

1. 把語意相近的事件歸組
2. 每組就是一個 Bounded Context 候選
3. 為每個 Context 命名（英文 kebab-case，如 `user-onboarding`）
4. 確認 Context 之間的關係（上游/下游、共享核心、防腐層）

### Step 3 — Aggregate Roots 識別

在每個 Bounded Context 內：

1. 找出一致性邊界：哪些實體必須一起改變？
2. 識別最頂層的實體作為 Aggregate Root
3. 記錄 Root 下的其他 Entities

### Step 4 — 輸出 handoff artifact

填寫 `openspec/changes/<name>/event-storming.md`（格式見 handoff-artifact-template.md）。

確認：

- [ ] ≥ 3 個 Domain Events（過去式動詞）
- [ ] ≥ 1 個 Bounded Context（英文 kebab-case）
- [ ] ≥ 1 個 Aggregate Root
- [ ] `## Notes for Amplifier` 欄位填寫對 Step 4 假設的影響

---

## Handoff to Spectra Amplifier

完成後，告知使用者：

```text
Event Storming handoff artifact 已產出：
  openspec/changes/<name>/event-storming.md

下一步：執行 /spectra-amplifier 展開完整規格。
amplifier Step 0 會讀取此 artifact 作為領域脈絡。
```

---

## Out of Scope (draft status)

以下功能尚未包含，後續 PR 補充：

- 六色貼紙完整方法（Events / Commands / Aggregates / External Systems / Policies / Read Models）
- Pivotal Events 識別（系統狀態分割點）
- Saga / Process Manager 識別
- Context Map（Bounded Context 之間的關係圖）
- 自動偵測 Aggregate Root 候選（需要程式碼分析）

---

## FAQ

| Issue | Fix |
|-------|-----|
| 使用者只有一句話描述 | 用「如果要讓這個功能運作，系統中必須發生哪三件事？」引導 |
| 不確定 Domain Event 名稱 | 統一用「{實體} 已 {動作}」格式，如「訂單已取消」|
| Bounded Context 邊界不清 | 問「這個事件由哪個部門 / 系統負責？」作為邊界線索 |
| 功能太小，不需要 Event Storming | 如果只有 1 個 Actor + 1 個 Goal，可直接跑 spectra-amplifier |
