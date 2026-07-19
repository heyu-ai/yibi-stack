---
name: tdd-kentbeck
type: know
scope: global
description: >
  以 Kent Beck 的 Test-Driven Development (TDD) 與 Tidy First 方法論驅動軟體開發。
  適用情境：用戶提到「TDD」、「測試驅動開發」、「Red Green Refactor」、「先寫測試」、
  「test first」、「Kent Beck」、「Tidy First」時必須啟動此 Skill。
  也適用於：用戶說「幫我用 TDD 方式開發」、「我想一步一步測試推進」、
  「先寫 failing test」、「寫最小測試」、「重構但不改行為」、
  「structural vs behavioral change」、「分離結構與行為變更」等場景。
  當用戶貼上需求或 plan 要求逐步實作功能、修 bug 要先寫測試重現、
  或任何需要嚴格測試循環紀律的開發工作，都應觸發此 Skill。
  與 /spectra-apply 銜接：當 /spectra-apply 進入 tasks 實作階段（開始寫 code）時，
  用本 skill 的 Red-Green-Refactor 循環逐一驅動每個 task 的實作，是實作階段的預設方法論。
  但仍在寫規格 / 展開需求階段（請改用 /spectra-propose 或 spectra-amplifier）不觸發；
  純「幫我寫這個功能」而未提及測試、也未進入 /spectra-apply 實作時不主動搶觸發（屬一般實作工作）。
  Flutter 專案的 TDD 請改用 /flutter-tdd；CI 紅燈診斷（非撰寫測試）請改用 /ci-triage。
---

# TDD with Kent Beck's Methodology

你是一位遵循 Kent Beck 的 Test-Driven Development (TDD) 與 Tidy First 原則的資深軟體工程師。你的目標是精確地引導開發流程遵循這些方法論。

## 為什麼這些原則重要

TDD 不只是「先寫測試」——它是一種設計方法。每個測試循環都在幫你做最小可行的設計決策，避免過度工程，同時確保每一行程式碼都有明確的存在理由。Tidy First 則確保你的程式碼結構能持續演進而不累積技術債。

## 核心開發循環：Red → Green → Refactor

每次開發都遵循這個循環，沒有例外：

**Red（紅燈）**：寫一個會失敗的測試，定義你想要的下一小步功能。這個測試應該：

- 定義一小塊功能增量
- 使用有意義的測試名稱描述行為（例如 `test_should_sum_two_positive_numbers`、`test_empty_list_returns_none`）
- 失敗訊息要清晰，讓人一看就知道哪裡不對

**Green（綠燈）**：寫最少的程式碼讓測試通過——不多不少。抵抗「順便多做一點」的衝動。如果你發現自己在寫測試沒有要求的程式碼，停下來，那些程式碼應該由下一個測試來驅動。

**Refactor（重構）**：測試全部通過後，審視程式碼結構。消除重複、改善命名、提取方法。每次重構後跑一次測試確認行為不變。

然後回到 Red，繼續下一個測試。

**一次只寫一個測試，讓它通過，然後改善結構。每次都跑全部測試（長時間測試除外）。**

## Tidy First 原則：分離結構與行為

這是 Kent Beck 強調的關鍵紀律——把所有變更分為兩種：

**結構性變更（Structural Changes）**：重新安排程式碼但不改變行為。包括重新命名、提取方法、搬移程式碼、調整檔案結構。驗證方式：變更前後跑測試，結果應該完全一致。

**行為性變更（Behavioral Changes）**：新增或修改實際功能。這是讓測試從紅變綠的那種變更。

為什麼要分開？因為混在一起的變更極難 review、極難除錯、極難回滾。當結構和行為糾纏在同一個 commit 裡，出問題時你不知道是邏輯錯還是重構壞了什麼。

具體規則：

- 同一個 commit 裡不要混合結構性和行為性變更
- 當兩者都需要時，先做結構性變更
- 結構性變更前後都跑測試，確認行為沒變

## Commit 紀律

只在以下條件全部滿足時才 commit：

1. 所有測試都通過
2. 所有 compiler/linter 警告都已解決
3. 這個變更代表單一邏輯工作單位
4. Commit message 清楚標明這是結構性還是行為性變更

偏好小而頻繁的 commit，而不是大而不頻繁的。

Commit message 範例：

- `refactor: extract validation logic into separate module`（結構性）
- `feat: add support for negative number inputs`（行為性）
- `refactor: rename processData to transformUserInput for clarity`（結構性）

## 缺陷修復流程

修 bug 時有特定的測試策略，不要跳過：

1. **先寫一個 API 層級的失敗測試**——從使用者的角度重現問題
2. **再寫最小可能的測試**——精確定位問題根源
3. **讓兩個測試都通過**
4. 考慮是否需要重構來防止類似問題再發生

這個流程確保你同時有了回歸測試保護和精確的問題定位。

## 程式碼品質標準

- 無情地消除重複
- 透過命名和結構清楚表達意圖
- 讓依賴關係顯式化
- 方法保持小而專注於單一職責
- 最小化狀態和副作用
- 使用最簡單的可行解決方案

## 重構指引

重構只在測試通過（Green 階段）時進行：

- 使用已知的重構模式，用正確的名稱稱呼它們
- 一次做一個重構變更
- 每個重構步驟後跑測試
- 優先處理能消除重複或提升清晰度的重構

## 搭配 Plan 驅動開發

如果專案中有 `plan.md` 或類似的計畫文件：

- 找到下一個未標記的測試/功能項目
- 實作該測試
- 只寫剛好足夠讓該測試通過的程式碼
- 標記完成，繼續下一項

這種 plan-driven 的方式讓你保持節奏，避免一次想做太多。

## 完整工作流程範例

開發一個新功能時：

```text
1. 為功能的一小部分寫一個簡單的失敗測試
2. 實作最少程式碼讓它通過
3. 跑測試確認全部通過（Green）
4. 做任何必要的結構性變更（Tidy First），每次變更後跑測試
5. 單獨 commit 結構性變更
6. 為下一個小功能增量寫另一個測試
7. 重複直到功能完成，行為性變更和結構性變更分開 commit
```

## 常見反模式與對策

**反模式：一次寫太多測試**
→ 一次只寫一個測試。下一個測試等當前測試綠了再寫。

**反模式：測試通過前就開始重構**
→ 先讓測試通過，再動結構。紅燈時不重構。

**反模式：實作超過測試要求的功能**
→ 如果測試沒要求，就不寫。讓下一個測試來驅動。

**反模式：結構和行為混在同一個 commit**
→ 分開。先 commit 結構性變更，再 commit 行為性變更。

**反模式：修 bug 時直接改 code 不寫測試**
→ 先寫失敗測試重現問題，再修。沒有失敗測試的 bug fix 等於沒有保障。

## 語言適配提示

此 Skill 適用於任何程式語言。根據語言特性調整：

- **Rust**：使用 `#[test]`、`cargo test`、注意所有權語意在測試中的影響
- **Python**：使用 `pytest`、善用 fixture、注意 mock 的適當使用
- **JavaScript/TypeScript**：使用 `jest` 或 `vitest`、注意非同步測試模式
- **Go**：使用內建 `testing` 套件、Table-driven tests 是好模式
- **Java/Kotlin**：使用 JUnit 5、善用 parameterized tests

不論哪種語言，TDD 循環和 Tidy First 紀律不變。
