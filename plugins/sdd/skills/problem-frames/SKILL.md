---
name: problem-frames
type: know
scope: global
description: >
  Michael Jackson Problem Frames 方法論：在寫 spec 之前，把問題拆成
  R（需求）/ S（規格）/ W（領域假設），並證明 S ∧ W ⟹ R，藉此把領域假設前置顯式化。
  適用情境：用戶提到「problem frame」「問題框架」「領域假設」「規格邊界」「機器與世界」
  「R/S/W」「需求 vs 規格」「正確性論證」「frame concern」「需求太模糊先框問題」時觸發。
  也適用於：需求把「機器要做什麼」與「世界要成立什麼」混在一起、
  或 AI 老是自行補不同假設導致規格不可重現時。
  位於 event-storming 之後、spectra-amplifier 之前，產出 problem-frame.md 作為展開規格的前置輸入。
effort: medium
---

# Problem Frames Skill

## Human Entry Point

本 skill 把模糊需求在進規格展開前先「框」起來：拆成 R/S/W 並補上 frame concern。

**完整方法論**：讀本目錄的 `methodology.md`（owner，單一真實來源）——
含 5 種 frame 型別與各自 frame concern、R/S/W 拆解、S ∧ W ⟹ R 論證模板、
frame concern 檢查表、Design by Contract 對應、`problem-frame.md` 輸出骨架，以及完整 worked example。
本 SKILL.md 僅為壓縮摘要，語意以 `methodology.md` 為準。

---

## 核心洞見

> **需求描述的是「世界」（R），不是「機器」（S）；而 W 是世界既有的假設。**
> 正確性論證：**S ∧ W ⟹ R**。
> AI 最大的亂源是自動補上沒寫清楚的 W，且每次不同。把 W 顯式寫出，採樣自由度就被剪掉一大半。

---

## When to Use

- event-storming 之後、`/spectra-amplifier` 展開規格之前
- 需求把「機器要做什麼」與「世界要成立什麼」混在一起時
- 規格反覆生成、結果不穩定（AI 每次補的隱含假設不同）時
- 使用者說「這需求太模糊，先把問題框清楚」時

---

## Quick Start

1. 讀 `methodology.md`（同目錄）
2. 用 frame 分類決策表選出主導 frame（必要時組合多個）
3. 拆 R / S / W，每條 W 標明「若不成立的後果」
4. 寫 S ∧ W ⟹ R 正確性論證
5. 逐項勾選該 frame 的 frame concern 檢查表
6. （選填）標出 require / ensure / invariant 對應到哪個 Pydantic validator / 測試
7. 產出 `openspec/changes/<name>/problem-frame.md`，交給 spectra-amplifier Step 0.5

---

## Frame 型別速查

| Frame 型別 | 何時選 | Frame Concern（要補的論證）|
|------------|--------|---------------------------|
| Required Behaviour | 機器自動維持世界狀態 | 機器行為 ∧ 因果律 ⟹ 受控領域維持需求狀態 |
| Commanded Behaviour | 操作者下命令、機器執行 | 命令 ⟹ 正確回應且拒絕違反安全約束者 |
| Information Display | 世界狀態映射到顯示 | 顯示 ⟹ 與真實世界一致（含延遲假設）|
| Simple Workpieces | 使用者建立／編輯工件 | 編輯序列 ⟹ 工件不變式始終維持 |
| Transformation | 輸入資料 → 輸出資料 | 輸入規則 ∧ 對應規則 ⟹ 輸出完整且無多餘 |

> 完整 concern 檢查表、多 frame 組合、shared phenomena 一致性檢查見 `methodology.md`。

---

## Handoff to Spectra Amplifier

完成後告知使用者：

```text
Problem Frame artifact 已產出：
  openspec/changes/<name>/problem-frame.md

下一步：執行 /spectra-amplifier 展開完整規格。
amplifier Step 0.5 會讀此 artifact：
  - W（領域假設）→ 直接成為 Step 4 假設表的單一來源（唯一直接傳遞的 leg）
  - R / S    → 成為 Step 1 User Story 與 Gherkin scenario 骨架
  - DBC 對應  → 經 Gherkin / AC 間接影響 Step 2 qa-test-designer 的 Decision Table
               （qa-test-designer 只收 Gherkin / AC，不直接收 problem-frame.md）
```

---

## 與後續流程的關係（Phase 2 預告）

本 skill 屬「輸入收斂」：把 W 前置顯式化，降低 AI 採樣自由度。
文章的「輸出剪枝」（確定性 gate + 合約強制 + auto-fix loop）尚未建：

- **本次（方法論優先）**：只 require/ensure/invariant **文件化**對應到 Pydantic validators，不強制。
- **Phase 2**：把 `check_spec_coverage.py` 擴成 frame-concern completeness / contract-coverage gate，
  讓「合約沒對應測試、frame concern 未補齊」直接 CI fail——這才讓本 skill 的 W／S／R 真正被咬住。

---

## 反模式

| 反模式 | 問題 | 正確做法 |
|--------|------|----------|
| R 裡寫機器實作 | 需求綁死實作 | R 只描述世界狀態，做法留 S |
| W 留白 | AI 自行補假設、每次不同 | 顯式列每條 W + 「若不成立的後果」|
| 跳過 frame 分類直接萃取四元素 | 不知該補哪段 concern | 先分類 frame，照 frame concern 填空 |
| W 在 problem-frame 與 Step 4 各寫一份 | 兩處漂移 | W 以 problem-frame.md 為單一來源 |

---

## FAQ

| Issue | Fix |
|-------|-----|
| 分不清 R 和 S | 問「這句話拿掉機器還成立嗎？」成立→R（世界）；只在介面才有意義→S |
| 不知道選哪個 frame | 多數功能是組合；先選最主導的那個立骨架，其餘當子問題 |
| 需求太小要不要做 framing | 單一 Actor + 單一 Goal、無隱含領域假設：可略過本「獨立」problem-frames skill，直接跑 spectra-amplifier。注意 amplifier Step 0.5（medium/high）仍會執行框架步驟，但對無隱含 W 的需求會 trivially 通過——並非「跳過 Step 0.5」 |
| W 寫不出來 | 問「這功能要對，世界必須先成立哪些事且不是機器保證的？」 |
