## Context

`/pr-retro-hard`（PR #376）出貨時刻意把 conformance eval 排除在範圍外，理由記於其 design 的
Decisions 與 Non-Goals。本 change 是那個續作。

現況三件事構成本設計的約束：

1. **彙整核心已被完全鎖住，行為層完全沒被量測。** 81 個決定性測試涵蓋 policy kernel 這個純
   函式；「voice 是否真的抓得到瑕疵」則是 LLM 執行期行為，pytest 驗不到。
2. **repo 已有兩份同架構、零共用的 eval 模組**（`tasks/gate_eval/` 與 `tasks/skill_eval/`）。
   再 fork 一份會變成第三份。
3. **`enable_demotion` 目前是 shadow（預設 `false`）**，所以沒有正在流血的洞；但也因此沒有
   任何資料可以支持把它打開。這是本 change 存在的理由，也是它不急的理由。

`tasks/gate_eval/sunset.py` 的每個函式（apply_mutation / restore_and_invalidate / is_effective /
classify_prune / evaluate_suite_sunset）已泛用於 MutationDescriptor、StabilityVerdict、
FixtureWindowRecord，**不涉及 disposition 語意**——它可以被 import 而非複製。

## Goals / Non-Goals

**Goals:**

- 讓「retro mob review 的 voice 是否有效」成為可量測、可回歸的性質，而不是一個信念。
- 把突變驗證核心收斂成單一實作，讓第三個 eval 模組不必再 fork 一次。
- 定義把 `enable_demotion` 由 shadow 轉為開啟所需滿足的**可檢查條件**，讓那個決定有依據。
- 讓整套東西的**移除成本**維持在「刪一個目錄加一個排程項目」。

**Non-Goals:**

- **不執行 shadow pilot。** pilot 需要 10 次真實 retro 的資料，無法在實作階段產生。本 change
  只定義協定與 harness。
- **不修改 `enable_demotion` 的預設值。** 那是 pilot 資料支持後的獨立決定。
- **不修改 `pr-retrospective` 既有四道 gate 的行為。** 沿用 `/pr-retro-hard` 的委派範式。
- **不修改 `tasks/skill_eval/`。** 它與本 change 無關；把它一併收斂進共用模組是另一個 change。
- **不以歷史失效案例作量化 gate。** 見下方 Decisions 的專節。

## Decisions

### 提升 sunset 突變核心為共用模組

把 `tasks/gate_eval/sunset.py` 的突變原語搬到 `tasks/_eval_mutation.py`，`gate_eval` 改為
import。**行為完全不變**，`gate_eval` 的既有測試即為回歸鎖。

替代方案：直接 fork 整個 `gate_eval` 到新模組。否決理由是它會製造第三份平行實作——repo 已有
兩份（`gate_eval` / `skill_eval`）零共用的同架構程式碼，第三份會讓任何一個突變語意的修正
需要三處同步，而那正是靜默 drift 的溫床。

命名用底線前綴（`_eval_mutation`）表示它是 `tasks/` 內部的共用件，不是對外 CLI 模組。

### 替換 models 而非重用 gate_eval 的 ConformanceFixture

`gate_eval` 的 `ConformanceFixture` 綁定 gate 專屬的 factors（severity / evidence / round /
contract_mapping）。retro mob review 的決策面完全不同：它的 factor 是 claim–evidence 對的
形狀、defect family、以及 settling check 的可執行性。

因此 models 是**必須替換的那一個檔案**，其餘（CLI 骨架、manifest / disposition 回放、突變
迴圈）沿用。這一點必須寫在 skill.md 裡，否則下一個人會嘗試 drop-in 重用 `mutation-verify`
並得到一個對不上決策面的 fixture。

### 保留 judge 接縫讓核心不 import LLM

沿用 `gate_eval` 的接縫：核心**不 import 任何 LLM**；判斷經 `--emit-manifest` 產出、由 agent
session 執行、再以 `--dispositions` 回放，兩端以 signature 綁定。

這是整套東西可被單元測試的唯一原因。替代方案（核心直接呼叫模型）會讓每個測試都變成網路
呼叫，且結果不決定性——那樣的 suite 沒有回歸價值。

signature 綁定的作用是：manifest 與 dispositions 不匹配時**硬失敗**，而不是靜默套用一組
對不上的判斷。

### 加入 anchor-presence judge 等價物

讓 mutation-kill 能在 pytest 內**決定性地**證明，不需 agent session。這是「fixture 真的綁到
production 邏輯」這個需求裡最高價值的一塊：沒有它，「突變被 killed」只能靠跑一次 agent
session 來宣稱，而那既慢又不決定性。

### Corpus-derived mutation 與必須保留的 clean twin

突變運算子由歷史失效歸納，不從空白頁造 defect：**evidence replacement**、**scope expansion**、
**actor inversion**、**causal substitution**。每次只改一個最小片段，字數 / 格式 / 引用密度
保持不變。

**必須保留 clean twin**——每個 mutant 都要有一個同形狀但未突變的對照。沒有它，量到的只是
「看到可疑句就報錯」的傾向，而不是「能分辨真假」的能力。

三道 realism 檢查：prevalence check（該形狀在真實 retro 中確實出現過）、blind discriminator、
leave-one-family-out（設計 prompt 時不用某 defect family，再用它測泛化）。

### 六項量測指標而非單一命中率

量測拆六項，不只「抓到幾條」：detection recall、class accuracy、target localization、
settling-check validity、**clean-twin false-positive rate**、false park rate。

只看 recall 會讓「對所有東西都報錯」得到滿分。clean-twin false-positive rate 與 false park
rate 是這個退化的直接對照。

### Shadow pilot 協定與啟用降級的條件

10 次真實 retro 的 shadow mode：**先取得使用者原本的校準，再揭露 mob 結果**，記錄哪些決定
被改變；由**不知先後順序的 adjudicator** 比較 evidence alignment；跨案例**隨機交換
baseline-first / mob-first**，否則順序本身會 anchor。

收集：false objection rate、false park rate、使用者因 mob 放棄正確 lesson 的比例、mob 修改後
claim–evidence alignment 變差的比例、使用者 override 率、對抗 voice 產生但無法執行的 settling
check 比例。

`enable_demotion` 由預設關閉改為開啟的條件寫成一個可檢查的判定，而不是一句「pilot 數據支持
後」。判定內容屬 pilot 設計，本 change 負責把它變成 harness 能輸出的一個 verdict。

### 成本量測不得使用引擎現有的 session token 欄位

同一份 PR packet 做 paired A/B（`/pr-retro` vs `/pr-retro-hard`）：M1 / M2 各自 wall-clock
p50/p95、**critical-path latency**（三 voice 平行，不是三家相加）、每 voice input/output/cache
tokens、timeout / invalid / retry rate、使用者多花幾次互動、**每個「最後確認為真的新 finding」
之增量成本**。

**不得**用引擎現有的 session token 欄位當這個數字——`pr-retrospective` SKILL.md 自己承認它
涵蓋整個 session，混有其他工作時會失真。eval runner 要在每個 reviewer call 邊界分別計量。

初期用相對 budget，不訂美元硬門檻：p95 增量等待不超過 baseline 兩倍；每個確認有效 finding
的成本不超過一次完整 `/pr-retro` baseline。

### 排除以歷史失效案例作量化 gate

曾考慮拿本 repo 自承的「retro 宣稱後來被證偽」案例（rule 13 的 trap EXIT 那格、agy print 旗標
的 verified 標記、rule 11 的過時 residual note）當語料。

**否決**，理由是 **hindsight leakage**：那些反證敘述就寫在 rule 檔內，而外部 voice 具備 repo
讀取權，因此量到的是「會不會查資料」而非「會不會推理」。加上 survivorship bias 在數學上
無法補償（未被發現的錯誤不在語料內）。此類語料只能作定性警示，**不可作為發布閘門**。

### 不註冊 pre-commit hook 或 merge 阻擋

沿用 `tasks/gate_eval/cli.py` 的存活策略——其 docstring 寫明理由：「移除成本因此維持在刪一個
目錄加一個排程項目」。

只有秒級的決定性測試進 CI；其餘是離線 suite，並配 `eval-fixture-sunset` 的季度汰除分類
（keep / demote / remove / repair，UNCLASSIFIED 一律歸 false alarm——歧義偏向廢除）。

## Implementation Contract

**Behavior**

- 共用突變模組提供的原語，其可觀察行為與現行 `gate_eval` 完全一致：對一份來源套用單一
  突變、還原並使快取失效、判定該突變是否有效、把一個 fixture 的穩定度分類為 keep / demote /
  remove / repair。`gate_eval` 的既有離線 suite 在 refactor 前後輸出相同的分類結果。
- 新 eval 模組提供一個 CLI，能在**不呼叫任何 LLM** 的情況下走完「產出 manifest → 讀回
  dispositions → 輸出六項指標」的完整迴圈。缺少 dispositions 時它輸出 manifest 並以非零
  結束，明說還缺什麼，而不是輸出一份空指標。
- pilot harness 能對一份 baseline 校準與一份 mob 結果輸出一個 verdict，說明啟用降級的條件
  是否滿足；資料不足時 verdict 是「資料不足」，**不是** false。

**Interface / data shape**

- 共用模組匯出的名稱：apply_mutation、restore_and_invalidate、is_effective、classify_prune、
  evaluate_suite_sunset，以及它們操作的 MutationDescriptor、StabilityVerdict、
  FixtureWindowRecord。`gate_eval` 改為從共用模組 import 這些名稱，不保留本地副本。
- 新模組的 CLI 子指令至少含：emit-manifest（產出待判斷清單）、score（回放 dispositions 並
  輸出指標）、pilot-verdict（輸出啟用降級的判定）。
- manifest 與 dispositions 以 signature 綁定；不匹配時硬失敗並指出兩邊的 signature。

**Failure modes**

- manifest / dispositions signature 不匹配 → 非零結束，訊息同時印出兩個 signature。
- fixture 缺少 clean twin → 非零結束並指名該 fixture。這是硬失敗而非警告：沒有 clean twin
  的量測會系統性高估 recall。
- 突變的 anchor 在來源中找不到**或不唯一** → 非零結束並指名該突變。沿用本 repo 既有紀律：
  anchor 對不上時突變根本沒套用，此時的「killed」是空的。
- 指標計算遇到零樣本的類別 → 該欄位輸出「無樣本」而非 0。0 會被讀成「表現很差」，語意相反。

**Acceptance criteria**

- `gate_eval` 的既有測試在 refactor 後全數通過，且未新增針對 sunset 行為的重複測試——回歸
  由既有測試承擔，這是「行為不變」的驗證方式。
- 新模組的每個 gate（signature 綁定、clean-twin 必要性、anchor 唯一性）都有一個**實際會觸發
  它的輸入**作為正向對照，而不是只測 happy path。
- 每個宣稱「鎖住某個不變量」的測試都以隔離突變驗證過：破壞該不變量後該測試轉紅；突變一次
  只改一件事，anchor 找不到或不唯一時硬失敗而非略過。
- `make ci` 全綠，且其後工作樹無殘留改動。
- 新模組**不**出現在任何 pre-commit hook 或 CI 阻擋設定中，只有秒級決定性測試進 CI。

**Scope boundaries**

- 在範圍內：共用突變模組的抽出、新 eval 模組的骨架與指標、corpus-derived 突變運算子的定義
  與 fixture 格式、pilot 與成本量測的協定與 harness。
- 不在範圍內：執行 pilot、變更 `enable_demotion` 預設值、修改 `pr-retrospective` 的四道
  gate、修改 `tasks/skill_eval/`、任何 pre-commit 或 merge 阻擋的註冊。

## Risks / Trade-offs

- [抽出共用模組時靜默改變 `gate_eval` 行為] → 不新增 sunset 行為的測試，改以既有測試作為
  回歸鎖；refactor commit 必須是純搬移加 import 調整，任何行為修正另開 commit，讓 diff 本身
  可審。

- [新模組成為第三個沒人維護的 eval 目錄] → 沿用 `gate_eval` 的存活策略：零 CI 阻擋、移除
  成本維持在刪一個目錄；並掛進 `eval-fixture-sunset` 的季度汰除分類，UNCLASSIFIED 一律歸
  false alarm。

- [corpus 太小導致指標沒有統計意義] → 指標輸出必須附樣本數；零樣本類別輸出「無樣本」而非
  0。本 change 不宣稱指標達到某個門檻，只宣稱它可被量測。

- [pilot 協定定義得很漂亮但永遠不被執行] → 這是已知且被接受的殘餘風險。緩解是把
  `enable_demotion` 維持在 shadow：協定沒被執行時，現狀就是「不啟用」，而不是「在沒有資料
  的情況下啟用」。**這個 trade-off 的方向是刻意的**——不做 pilot 的代價是功能停在 shadow，
  而不是一個未驗證的機制開始改動 lessons DB。

- [judge 接縫讓「跑完整 eval」需要人手動介入一次 agent session] → 接受。這是核心可被單元
  測試的代價，且 anchor-presence judge 等價物讓最高價值的那一塊（fixture 綁定驗證）不需要
  agent session。

- [本 change 的 Non-Goals 隨時間被遺忘，後續 PR 把 pilot 執行也塞進來] → Non-Goals 與 Scope
  boundaries 兩處各寫一次，且 tasks 不含任何執行 pilot 的項目。

## Open Questions

- 六項指標各自的**發布門檻**（而非量測方式）留待 pilot 首批資料出來後再訂。本 change 不預設
  門檻值，因為在沒有任何真實樣本前訂的門檻是猜的。
- corpus 的初始規模與來源取樣方式（哪幾次歷史 retro）需要在實作時與維護者確認；prevalence
  check 的判準依賴這個取樣。
