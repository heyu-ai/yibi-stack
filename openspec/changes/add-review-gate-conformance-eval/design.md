## Context

`/pr-cycle-deep` 的 Evidence gate 以散文形式寫在 pr-cycle-deep 的 SKILL.md 裡，由 lead agent
在 Step 5 聚合時閱讀並施行。它有一張明文的 disposition 矩陣（severity × evidence × round），
宣稱每一格都有定義且無歧義——這是一個可證偽的宣稱，但目前沒有任何機制證偽它。

既有防線的涵蓋範圍：pr-cycle-deep 的 convergence contract 測試斷言 runbook 內的錨點字串在場，
並以逐錨點 mutation 證明每個錨點承重；agy 輸出驗證腳本處理外部 CLI 的靜默失敗；amplifier
驗證腳本檢查 TC 覆蓋率與 docstring 追溯。三者都只碰文件與工具輸出，沒有一個碰 disposition
判定本身。`add-pr-review-contract` 的 testplan 已用 doc 與 mech 前綴明確標示這個界線，並在
Missing Coverage 建議補上 golden-eval harness，該建議未實作。

專案內已有同形狀的前例：skill trigger eval 模組具備 fixture 模型、可插拔的 agent judge
backend、逐類計分與 baseline regression 比對。本設計沿用其形狀，不重造骨架。

## Goals / Non-Goals

**Goals:**

- 證明或推翻「lead agent 實際執行的 disposition 與矩陣所寫的一致」。
- 偵測 gate 自身的 fail-open：finding 在聚合過程中被靜默丟棄。
- 量測判定的跨次穩定度，並把不穩定當成一級結論而非雜訊。
- 讓這套 eval 本身可被證偽，並預先承諾它失去價值時的移除條件與時程。

**Non-Goals:**

- **不驗證矩陣本身是否正確**。「被 deferred 掉的 finding 是否其實是真缺陷」需要縱貫資料，
  且需要把數月後、以不同措辭描述的同一缺陷連回當初的 deferred 項目——缺乏 join key，
  本 change 不處理，報告必須明講此界線。
- 不比較或排名各家 reviewer（Claude / codex / agy）的品質。
- 不修改 Evidence gate 的規則內容；本 change 只量測既有規則的執行情形。
- 不把 eval 接入 pre-commit 或 merge gate。
- 不修改既有 skill trigger eval 模組；兩者 fixture 語意不同，不共用資料模型。

## Decisions

### 受測系統定義為 agent 加 SKILL.md，而非可單元測試的函式

Evidence gate 沒有程式實作，判定發生在 lead agent 的執行期。因此受測系統是「agent 讀
SKILL.md Step 5 後產生的 disposition」，驗證方式必然是 eval 而非 pytest。

考慮過的替代方案：先把 disposition 判定移進 Python，再用 pytest 精確測試。否決的理由是
順序錯誤——目前沒有證據顯示散文形式不足以驅動一致行為，先重寫等於在未證實問題的情況下
付出大幅重構成本。若本 eval 顯示判定不穩定，那才是啟動該重構的證據，屆時本 eval 也隨之退場
（見 sunset 觸發條件三）。

### 守恆檢查的優先序高於一致性檢查

輸出必須包含每一筆輸入 finding、恰好一次，且標題與描述逐字保留。此檢查獨立於 disposition
是否正確，並優先回報。

理由：錯誤的 disposition 會出現在聚合輸出裡，人類複查時看得到；被丟棄的 finding 不會留下
任何痕跡，是不可見的失效。gate 的規則本身已要求降級的 finding「moved, never dropped」，
但沒有任何機制檢查這條規則被遵守。守恆是可數且客觀的，不依賴對矩陣的詮釋。

### 每個 fixture 只變動一個因子，並涵蓋放行方向

fixture 逐格對應矩陣，每筆只改變一個因子（severity、evidence 形式、round、contract mapping
其中之一）。必須同時包含期望為 blocking 與期望為 non-blocking 的案例。

理由：多因子 fixture 會因為錯的原因變紅，於是產生假的「已驗證」。而只包含期望 deferred
的 fixture 集合，會被一個「永遠回答 deferred」的退化行為全數通過——過度攔截與正確攔截
在那樣的集合上無法區分。

### 穩定度以三值判定，且門檻先於執行定義

每個 fixture 執行 n 次獨立判定（預設 n 為 5），結果分三類：

| 條件 | 判定 |
| --- | --- |
| 至少 4 次落在同一 disposition 且該 disposition 等於正解 | CONFORMANT |
| 至少 4 次落在同一 disposition 但該 disposition 不等於正解 | NONCONFORMANT |
| 沒有任何 disposition 達到 4 次 | UNSTABLE |

理由：把 UNSTABLE 併入 NONCONFORMANT 會混合兩種修法不同的失效——「規則寫錯或沒被遵守」
要改 SKILL.md 文字，「規則被不可靠地遵守」要把該格移進程式。合併之後 pass rate 無法指向
任一修法。

n 為 5 是成本下限，不是統計推導的結果；它能偵測粗大的不穩定，給不出信賴區間。**只有首輪
無多數（UNSTABLE，即無任一 disposition 達 4 次）的 fixture** SHALL 加跑至 n 為 15 後重判；
4 比 1 已達多數門檻，為終局 CONFORMANT / NONCONFORMANT，不重跑。此限制必須寫進報告，不得
以「已驗證」概括。（此段原散文曾把 4 比 1 也納入重跑，與本節判定表及 spec 的
「reaches neither a five-run nor a four-run majority」矛盾，已更正；見 fixtures/DISCOVERIES.md D3。）

### fixture 的有效性定義為 mutation 存活與否

每個 fixture 綁定一個對 SKILL.md 的單一變更（移除或改寫該 fixture 所依賴的那一句規則）。
套用該變更後，該 fixture 必須由 CONFORMANT 轉為 NONCONFORMANT；否則該 fixture 沒有測到它
宣稱測的規則。

考慮過的替代方案：以 suite 整體 pass rate 作為有效性指標。否決理由是 pass rate 無法區分
「規則被遵守」與「根本沒測到規則」，兩者都呈現為綠燈。

執行紀律（違反任一則該次 mutation 結果作廢）：

- 一次只套用一個變更。複合變更會因為錯的理由變紅。
- 變更的定位字串若在 SKILL.md 中找不到，SHALL 以失敗中止，不得靜默略過——找不到即代表
  變更未套用，該次驗證是空的。
- 還原後 SHALL 清除快取位元碼並更新來源檔時間戳，避免以還原前的狀態重跑。

### sunset 的觸發條件與檢視排程於本 change 內先行承諾

**fixture 層級，每季 prune：**

| 狀態 | 動作 |
| --- | --- |
| mutation 仍能使其轉紅，且窗口內曾因真實回歸而紅 | 保留於常規頻率 |
| mutation 仍能使其轉紅，但從未紅過 | 保留但降至每季執行 |
| mutation 無法使其轉紅 | 移除該 fixture |
| 曾紅但全數為 eval 自身問題（fixture 過時、SKILL.md 合法改寫） | 修正一次；同一 fixture 第二次即移除 |

**suite 層級，任一條件成立即進入移除評估：**

1. 連續兩季，所有存活 fixture 皆屬「從未紅過」——已無回歸可偵測。
2. 窗口內假警報次數超過真警報次數——淨負面，會訓練使用者忽略紅燈。
3. disposition 判定已移入程式並由 pytest 直接涵蓋——被更好的機制取代。這是預期中最理想的
   結局，不是失敗。

**檢視不依賴記憶**：本 change 的 tasks 包含建立一個帶到期日的季檢視 issue，且每次紅燈
SHALL 在該 issue 留下一行分類（真警報或假警報）。未分類的紅燈預設計入假警報——歧義的
預設方向偏向移除，用以抵銷「工具因為已經存在而繼續存在」的傾向。

### 移除成本必須維持在刪除等級

eval 不進入 pre-commit 與 CI 阻擋路徑，程式碼集中於單一模組目錄，執行入口為單一命令，
排程為單一項目。

理由：sunset 若需要重構才能完成，實務上就不會發生。把移除成本壓在「刪一個目錄、拿掉一個
排程項目」這個等級，是讓 sunset 條件真的可執行的前提。此決定同時與既有建議一致——該建議
本就指定以手動或 nightly 執行而非進 pre-commit。

## Implementation Contract

**行為**：操作者執行 gate eval 命令後，取得一份報告，內容為每個 fixture 的三值判定
（CONFORMANT / NONCONFORMANT / UNSTABLE）、n 次執行的 disposition 分佈、守恆檢查結果，
以及 suite 層級的彙整。報告同時輸出人類可讀摘要與機器可讀 JSON。

**介面與資料形狀**：

- fixture 為單一檔案，欄位包含識別碼、合成的 R1 finding 文字、所屬 round、Review Contract
  片段、期望 disposition、以及綁定的 mutation 描述（定位字串與變更後內容）。
- oracle 為 disposition 矩陣的機器可讀轉錄，欄位為 severity、evidence 形式、round、
  contract mapping 四個因子對應到期望 disposition。轉錄過程本身即為第一項驗證：任何一格
  無法在不做詮釋的情況下轉錄，即證明該格並非其自稱的無歧義。
- 期望 disposition 為封閉列舉，值域涵蓋 blocking、deferred、outside-contract、non-blocking。
- 執行入口提供三個子命令：跑 eval、跑 mutation 驗證、產生 prune 與 sunset 建議報告。

**失敗模式**：

- fixture 檔案缺失、格式不符、或期望 disposition 不在列舉內 SHALL 以驗證錯誤中止，
  不得靜默略過該筆。
- oracle 與 fixture 的因子組合對不上 SHALL 中止並指名該筆，不得回退到預設值。
- mutation 的定位字串找不到 SHALL 中止並指名該 fixture。
- judge backend 呼叫失敗 SHALL 明確回報為執行失敗，不得與「判定為 deferred」混淆。
- 空的 fixture 集合 SHALL 以失敗中止，不得回報為全數通過。

**驗收條件**：

- 對照組一：餵入一組刻意標錯的期望 disposition，eval SHALL 回報失敗並指名該筆。從未紅過的
  eval 不算通過驗收。
- 對照組二：至少對三個代表不同 tier 的 fixture（結構層退件、形式錯配、封閉列舉排除）各套用
  一次獨立 mutation，三者皆 SHALL 由 CONFORMANT 轉為 NONCONFORMANT。
- 守恆檢查 SHALL 有其自身的對照：餵入一份刻意漏掉一筆 finding 的輸出，檢查 SHALL 回報守恆
  失敗並指名該筆。
- 單元測試涵蓋 fixture 驗證、三值判定門檻、守恆比對、prune 與 sunset 規則求值，皆不需呼叫
  agent。

**範圍界線**：

- 在範圍內：fixture 與 oracle、eval 執行與報告、守恆檢查、三值穩定度判定、mutation 驗證、
  prune 與 sunset 規則求值、季檢視 issue 的建立。
- 在範圍外：修改 SKILL.md 的 gate 規則、把 disposition 判定移入程式、reviewer 品質比較、
  縱貫的缺陷回溯、把 eval 接入任何阻擋路徑、修改既有 skill trigger eval 模組。

## Risks / Trade-offs

- [eval 成為 gate 規則的第二份副本，兩者會不同步] → fixture 只儲存輸入與期望結果，不複製
  規則文字；SKILL.md 改版導致 oracle 過時時，綁定的 mutation 會失效，該 fixture 隨即在 prune
  規則下被移除。不同步的後果是自我清理，而非靜默的錯誤結論。
- [n 為 5 給不出統計保證] → 明確記錄它偵測的是粗大不穩定；落在邊界的 fixture 加跑至 15 再判；
  報告不得以「已驗證」概括穩定度結論。
- [假警報與真警報的分類需要人工判定，無人分類則指標失效] → 未分類的紅燈預設計為假警報，
  使歧義的預設方向偏向 sunset。
- [呼叫 agent 有成本與延遲] → 不進 commit 路徑，以手動或排程執行；fixture 數量以矩陣格數
  為上限而非任意擴增。
- [本 eval 全綠可能被誤讀為「gate 是對的」] → 報告首行 SHALL 聲明本結果只證明對既有規則的
  符合度，不證明規則本身正確。此限制在 Non-Goals 與驗收條件中重複出現，屬刻意冗餘。
