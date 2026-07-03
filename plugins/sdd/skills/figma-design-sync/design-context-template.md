# Design Context Template

`design-context.md` 的骨架（owner：figma-design-sync skill）。
spectra-amplifier 與 design.md 只**引用**本產出物，不複製內容；
若章節語意變更，直接修改本 template，下游以引用方式自然取得新結構。

---

## 骨架

```markdown
# {{feature_name}} — Design Context

> 來源：{{figma_url}}
> Figma version：{{version}} | lastModified：{{last_modified}} | 擷取時間：{{extracted_at}}
>
> **截圖不入 git**；本機無圖時執行 figma-design-sync（sync 模式）自動補抓。
> 本檔由 figma-design-sync 維護——請勿手改（sync 會覆蓋）；設計詮釋請寫進 spec 或 proposal。

## 1. 畫面清單（Screens）

| Slug | 名稱 | 截圖 | 用途 | 可見 Actor 線索 |
|------|------|------|------|----------------|
| {{screen_slug}} | {{screen_name}} | ![{{screen_slug}}](assets/{{screen_slug}}.png) | {{一句話用途}} | {{此畫面暗示的使用者角色}} |

## 2. 互動流程（Flows）

<!-- 依 prototype 連結或版面順序描述 screen 間導航；推斷者標 inferred -->

1. {{screen_a}} → {{screen_b}}：{{觸發條件（按鈕/手勢）}}
2. {{screen_b}} → {{screen_c}}：{{觸發條件}}（inferred）

## 3. UI 元件與狀態（Components & States）

### {{component_name}}

| Variant / State | 有設計稿 | 說明 |
|-----------------|----------|------|
| default | ✓ | {{描述}} |
| disabled | ✓ | {{描述}} |
| error | ✗ | [DESIGN GAP: error 狀態無設計稿] |
| loading | ✗ | [DESIGN GAP: loading 狀態無設計稿] |

## 4. Design Tokens

<!-- 來自 get_variable_defs；file 未定義 variables 時註明並改列 inline style 摘要 -->

| 類別 | Token | 值 | 用於 |
|------|-------|-----|------|
| color | {{token_name}} | {{value}} | {{使用處}} |
| typography | {{token_name}} | {{value}} | {{使用處}} |
| spacing | {{token_name}} | {{value}} | {{使用處}} |
| radius | {{token_name}} | {{value}} | {{使用處}} |

## 5. 文案表（Copy）

<!-- i18n 與用詞一致性的單一參照點 -->

| Screen | Element | 原文 |
|--------|---------|------|
| {{screen_slug}} | {{element}} | {{原文文案}} |

## 6. Edge Cases 與設計缺口

<!-- empty / error / loading / 長文字 / 權限差異等是否有稿；缺口統一標 [DESIGN GAP] -->

| 情境 | 有設計稿 | 備註 |
|------|----------|------|
| 空清單（empty state） | {{✓/✗}} | {{說明或 [DESIGN GAP: ...]}} |
| 錯誤狀態（error state） | {{✓/✗}} | {{說明或 [DESIGN GAP: ...]}} |
| 載入中（loading state） | {{✓/✗}} | {{說明或 [DESIGN GAP: ...]}} |
| 超長文字 / 溢出 | {{✓/✗}} | {{說明或 [DESIGN GAP: ...]}} |

## 7. 給 Step 1a 的四元素提示

<!-- 從設計可直接觀察到的候選清單；標示為候選，需 spectra-amplifier 驗證 -->

> 以下為設計稿可觀察的**候選**，spectra-amplifier Step 1a 需驗證後採用。

| 元素 | 候選內容 |
|------|----------|
| **Actors** | {{從畫面推斷的角色}} |
| **Actions** | {{按鈕/手勢對應的操作動詞}} |
| **Data** | {{畫面呈現的資料實體與欄位}} |
| **Constraints** | {{設計暗示的限制：必填標記、字數上限、狀態互斥}} |
```

---

## 填寫指引

| 章節 | 指引 |
|------|------|
| 1 畫面清單 | 每個 screen 一列；slug 與 manifest 的 `nodes[].slug` 一致；截圖用相對路徑（本地存在時可預覽） |
| 2 互動流程 | prototype 有連結就照連結；沒有就依版面順序推斷並標 `inferred` |
| 3 元件與狀態 | 缺失的狀態稿是規格的高價值輸入——`[DESIGN GAP]` 會被 amplifier 轉為 `[NEEDS CLARIFICATION]` 或 W |
| 4 tokens | `get_variable_defs` 為空時，改列 design context 彙整的 inline style 摘要並註明來源 |
| 5 文案表 | 逐字抄原文，不改寫——這是 i18n 與用詞一致性的單一參照點 |
| 6 edge cases | 沒有稿也要列出情境本身（✗ + `[DESIGN GAP]`），讓缺口顯式化 |
| 7 四元素提示 | 只列「畫面上看得到證據」的候選；不腦補業務邏輯 |

章節 1/3/6/7 是 spectra-amplifier Step 1a 的直接輸入。
