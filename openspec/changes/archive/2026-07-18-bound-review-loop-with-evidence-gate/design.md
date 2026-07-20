## Context

`/pr-cycle-deep` 是本 repo 的跨家 LLM group review skill：codex 與 agy 各自獨立 R1、交叉 R2 debate，由 Claude lead 彙整後進 fix → re-review 迴圈，直到全員 LGTM 才 merge。

實際使用時它反覆跑多輪難以結束，且 review 意見逐輪變得難以理解。proposal 記錄了量測結果，problem-frame.md 記錄了 R/S/W 拆解與正確性論證，event-storming.md 記錄了領域事件與 aggregate 不變式。此處只補充實作必須知道的現況約束：

- **外部 reviewer 看不到 repo 的規則**。`codex-r1-stage1.sh` 餵給 codex 的內容只有 `guard + prompt-r1.md + diff.patch`，guard 明文禁止探索 repo，並以唯讀模式執行。因此 reviewer 的 context 就是那份約 40 行、自足的 `prompt-r1.md`——**這是唯一能改變 reviewer 行為的槓桿**，不存在「reviewer 讀了太多規則」的問題。此限制直接決定了證據形式的設計（見 Decisions）。
- **每輪的 review summary 已經貼上 PR**。降級的 finding 即使不開 issue 也不會消失。這是「NIT 不開票」得以成立的前提，記為 problem-frame.md 的 W2。
- **finding 的降級出口已有承接者**。`pr-flow:issue-triage` 是既有 skill，因此 `deferred-from-review` 標籤有人收（W3）。
- **三個 voice 的產出格式已是嚴格結構化 markdown**，並有 agentic-hijack 偵測器把關（缺少 review 標題即 `[FAIL]`）。新增 `Evidence:` 欄位是在既有結構上加欄，不是引入新格式（W8）。

Stakeholder：本 repo 的維護者（單人），既是 skill 的作者也是它的使用者——這使得「skill 自己的 PR 用 skill 自己 review」成為常態，收斂問題會自我放大。

#### Goals

1. 讓 fix → re-review 迴圈的終止成為**結構性質**，而非依賴使用者疲勞或紀律。
2. 讓 blocking finding 的門檻**可證偽**——擋 merge 的理由必須能被一條指令示範。
3. 讓降級的意見有明確去處，且**不製造新的無出口累積器**。
4. 本 change 必須示範自己的主張：`plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 改完後不得變長。

#### Non-Goals

- **不做 doc/code 分流 rubric**。曾考慮偵測 diff 組成、對 doc-heavy PR 套用另一套 severity 定義。否決理由：其效果已被證據閘門大部分吸收——證據閘門一上，doc 上「不夠精確」類的 finding 自動過不了閘，不需另外分流；且它會引入 mixed PR 的判定灰色地帶與第二套要維護的 rubric。若證據閘門上線後仍觀察到 doc PR 特有的不收斂，再另開 change。
- **不改 `/pr-cycle-fast` 與 `/pr-review-cycle`**。各自獨立的 SKILL.md，不在本 change 範圍。
- **不做 rules corpus 的治理**（`/pr-retro` 路由表的刪除出口、rules hot/cold tier）。不同子系統，回饋源是 `/pr-retro` 而非 review 迴圈。刻意延後：本 change 上線後會直接減少該子系統的流入量，先做這個可能讓後者變小。
- **不改 R1／R2 的 debate 結構本身**，也不調整 voice 的數量或模型選擇。
- **不放寬 reviewer 的 sandbox 或 skill-hijack guard** 來讓它自行驗證證據可跑（W6）。放寬即重現 agentic 探索失效模式。
- **不建 golden-transcript eval harness**。testplan 指出 21 個 scenario 中 18 個是 LLM 執行期行為、pytest 不可驗證，建議以 golden transcript 收斂該殘餘。本 change 不做——先讓契約落地並誠實標示「契約測試只證明文件符合性」，harness 另開。
- **不追求「零漏網」**。本設計明確接受部分真問題被降級為 issue（見 Risks）。

## Decisions

### 證據閘門作為 blocking 的前提條件

任何 finding 要 blocking，必須在 `Evidence:` 欄位提供該類型所要求的證據。提不出者不被禁止發表，但自動降級為非 blocking，且必須保留原標題、描述與降級理由。

**為何選此**：這是唯一同時命中三個症狀的單一機制。無法以證據示範的 finding 幾乎必然是在複述掌故而非指出缺陷（解「意見難懂」）；取得證據的成本天然限制每輪的 blocking 數量（解「不收斂」）；而它不是新發明——現行 Step 5 已要求 lead 對 disputed item 與 single-voice Critical 實跑 minimal repro 而非以推理裁決，本決策只是把該規則**從例外路徑升格為預設路徑**。

**替代方案**：(a) 提高 NIT 的門檻描述、要求「更具體」——否決，「具體」本身不可證偽，等於沒有閘門；(b) 讓 lead 自行判斷 finding 是否值得擋——否決，這正是現況，且把裁決責任放回無法被檢查的推理上。

### 證據形式依 finding 類型分類

`prompt-r1.md` 需明列各類 finding 可接受的證據形式，且該表為**封閉列舉**——未列出的類型無可接受形式，恆降級：

| Finding 類型 | 可接受的證據形式 | 可 blocking |
| ------------ | ---------------- | ----------- |
| Logic / security 缺陷 | **具體 failure scenario**：輸入值、預期輸出、實際輸出 | 是 |
| Test gap | 存活的 mutation：指名要弄壞哪一行 production code，測試仍綠 | 是 |
| Doc 事實錯誤 | 證明其錯誤的指令：路徑不存在、範例 exit 非零、引用的 file:line 對不上、宣稱與程式碼矛盾 | 是 |
| 命名／結構不一致 | grep 輸出顯示至少 2 個 sibling 使用另一慣例 | 是 |
| 精確度／可能誤導／建議補充 | 無可接受形式 | **否——恆降級** |

**logic / security 收 failure scenario 而非可跑指令，是被硬性限制逼出來的設計**：reviewer 以 read-only sandbox 執行且被禁止探索 repo（W6），因此它**無從得知測試 harness 的形狀、既有測試名稱或專案的執行方式**。要求它交出可跑指令，等於要求它猜——猜錯就是「證據無效」，於是真缺陷被誤殺。改收 failure scenario（輸入／預期／實際）後，reviewer 只需從 diff 就能導出，**由 lead 負責把它翻成可執行的指令**。這把「需要 repo 知識」的工作放到唯一擁有 repo 知識的角色身上。

**為何封閉列舉**：把「什麼可以擋你」寫成封閉清單，比寫成原則更難被繞過。最後一列是設計的核心：它讓「這句話可以更精確」這類無限可生成的意見結構性地無法 blocking。表中不得出現 `other` / `etc.` 等 catch-all 列，否則逃生門重開。

**替代方案**：只寫「必須附可執行證據」而不分類——否決，reviewer 會對 doc 類 finding 交出無意義的證據（例如 `cat file.md` 證明「這句話存在」），閘門形同虛設；且會對 logic bug 交出猜測的指令，造成誤殺。

### 驗證成本分層與三種執行結果

- 證據由 reviewer 提供，lead 不負責代找。
- `Evidence:` 欄位缺漏或不符格式者**直接降級，不需執行任何指令**（結構檢查）。
- lead **必須**實際驗證 Critical 的證據；Important **可選擇性**抽驗。
- 執行**必須**產生三種結果之一，且三者處置相異：

| 執行結果 | 意義 | 處置 |
| -------- | ---- | ---- |
| 跑了，缺陷重現 | reviewer 判斷正確 | 留在 blocking |
| 跑了，缺陷不存在 | reviewer 判斷錯誤 | 移出 blocking，並記錄「未重現」 |
| **根本跑不起來** | 證據無效，缺陷狀態**未知** | lead 嘗試修復一次；修不好則**降為 Important 進 deferred**——絕不 drop，絕不記為「未重現」 |

**第三列是本決策的核心，也是一個修正**：初版設計把「跑不起來」與「缺陷不存在」同樣 drop。這是錯的——**「證據無效」不等於「缺陷不存在」**，把兩者混同會讓一個真缺陷因為 reviewer 寫錯測試名稱而被靜默丟棄。三分法把「未知」獨立出來，並給它一個保守的去處（降級但保留）。

**為何分層**：閘門的絕大多數淘汰發生在「有沒有附證據」這個零成本的結構檢查，而非「證據對不對」的昂貴驗證。若不分層，lead 每輪要跑 N 個 repro，成本會使該閘門在實務上被略過——一個因為太貴而被繞過的閘門等於不存在。

**替代方案**：全部證據都實跑——否決，成本不可持續；全部都不跑只看有沒有填——否決，reviewer 會填無效證據且無人發現，Critical 這一類必須真驗。

### 輪數上限保證終止，審查面縮限降低成本

| 輪次 | 審查範圍 | blocking 條件 |
| ---- | -------- | ------------- |
| Round 1 | 完整 diff（`base..baseline`），並**記錄** baseline head SHA | Critical + Important，皆須附證據 |
| Round 2 | `baseline..HEAD`（fix delta），加上確認 round-1 的 blocking 已修 | 僅 Critical，須附證據 |
| Round 3 | 不存在 | — |

Round 2 結束仍有未解 Critical → 進入既有的 circuit breaker 三選項 UX，交人類裁決。

**終止由「不存在 Round 3」無條件保證，不由審查面大小保證。** 這一點必須寫清楚，因為初版設計把兩者混為一談：

> Round 1 的範圍是 `base..baseline`，Round 2 是 `baseline..HEAD`——這兩個 commit range **不相交，並非子集關係**，且 Round 2 的行數**不保證**小於 Round 1（作者在 Round 2 期間推入大型變更時反而更大，見 problem-frame.md W7）。

審查面縮限（只審 fix delta）的作用是**降低 finding 生成量與 token 成本**，是效率與品質性質。把它誤當終止的證明有實際代價：會讓人以為 W7 不成立時收斂保證就失效，於是為一個不存在的問題加防禦（例如禁止 Round 2 期間推 commit）。

**為何仍需輪數上限**：證據閘門降低 blocking finding 的生成率，但**不保證其 < 1/輪**。上限使「迴圈必在 2 輪內離開」成為可證明的性質，出口是 merge 或人類，不會是第 3 輪。

**替代方案**：(a) 只加 max rounds 而不縮限審查面——否決，第 2 輪仍全量重審，token 成本不變且 fix delta 之外的雜訊持續生成 finding；(b) 維持每輪全量重審但只有 Critical 能擋——否決，同上的成本問題，且 Important 級的 regression 完全無人看。

### 降級 finding 的雙軌出口

- 降級的 **Important** → 每個 PR 一張批次 issue（非每個 finding 一張），標記 `deferred-from-review`，交由 `pr-flow:issue-triage` 承接。
- 降級的 **NIT** → 不開 issue，留在既有的 PR review comment。

**為何選此**：兩類 finding 的未來命運本就不同。Important 是「真問題但證據不夠硬」，值得再看一眼；NIT 是「精確度可以更好」，進了 issue 就是死在那裡，誠實的做法是承認 PR comment 的歷史紀錄已經足夠。批次而非逐張開票，是為了不讓 issue tracker 變成新的無出口累積器——**用製造另一個只進不出的方式來解決只進不出，是本 change 最該避免的失敗模式**。

**替代方案**：(a) 全部降級 finding 都開批次 issue——否決，NIT 流量會淹沒 issue tracker 且無人處理，製造「有在追蹤」的錯覺；(b) 全部都不開票只留 PR comment——認真考慮過（零新增累積器、零新程式碼），最終否決，因為 Important 級的真問題確實需要出現在未來會被看到的清單裡，而 issue-triage 的存在使該出口是通的。

### 移除 NIT 的 blocking 效力

NIT 改為預設非 blocking。lead 得於當輪順手修掉瑣碎 NIT，但它永遠不構成 merge 門檻。

**這不是修改 severity 標準，而是恢復與 owner 的一致性。** `pr-cycle-deep` 的 severity 章節開頭即宣告 `/pr-review-cycle` 的同名章節為 owner、自身僅為 condensed summary。而 owner 的 canonical 表格對 Actionable NIT 寫的是 **`Does not block merge — fix opportunistically`**，且明載該標準「applies regardless of source... in this skill and in `/pr-cycle-deep`」。`pr-cycle-deep` 卻在 summary 中額外加上 owner 沒有的 blocking 約定——這是 dual-source 漂移，且漂出來的正是不收斂的最大來源。兩檔非 symlink，各自獨立，故漂移為真。**因此本決策不需觸碰 `/pr-review-cycle`**（Non-Goals 成立）。

**NIT-blocking 不是一句約定，而是散在 6 處的一套機制**，必須全數處理，否則決策表與散文互相矛盾：

| # | 位置 | 內容 | 處置 |
|---|------|------|------|
| 1 | severity 表 Actionable NIT 列 | `cleans up every **undisputed actionable NIT** before merge (see Step 5)` | 改為與 owner 一致：不 blocking |
| 2 | Step 5 開頭散文 | `Note the project override: ... this skill's convention cleans up every actionable NIT before merge` | 刪除該 override 句 |
| 3 | Step 5 彙整決策表 Actionable NIT 列 | `**Must fix** (user emphasized "all NITs cleaned up")` | 改為 deferred / 不 blocking |
| 4 | `final.md` 格式的 NIT 段標題 | `## Actionable NIT (must fix — user requires all NITs cleaned up)` | 改為非 blocking 的措辭 |
| 5 | 收斂條件 | `no new [Critical] / [Important] / [Actionable NIT] findings` | 移除 NIT 項 |
| 6 | `LGTM-with-trickle-NITs` 整段 | lead judgment call，繞過「no new NITs 永遠關不起來」 | **整段刪除**（見下） |

**錨點必須用實際字串，且兩處變體不同**：位置 1 是 `undisputed actionable NIT`，位置 2 是 `actionable NIT`。以「this skill's convention cleans up every actionable NIT」單一字串比對只會命中位置 2，位置 1 會留存而測試回報綠燈——此即本 repo 已記錄的「anchor 過時 → 突變沒套用 → 驗證是空的」。檢查器必須對**兩個變體**各有一條斷言。

**`LGTM-with-trickle-NITs` 整段刪除的理由**：該段存在的唯一前提是「NIT 會擋 merge，導致嚴格的 no-new-NITs 條件永遠關不起來」。根因移除後它沒有適用情境；且其成立條件之一為「每個 voice 的 verdict 連續 **2+ 輪** LGTM」，在 2 輪上限下亦不可能滿足。保留它會讓未來讀者誤以為 NIT 仍會擋。它是本 change 所治之病的止痛藥——#184 那次 commit（18 加 0 刪）看到了不收斂，但治的是「如何在不收斂時宣告收斂」。移除它同時歸還 17 行預算。

**替代方案**：(a) 保留該約定但排除 doc 類 NIT——否決，需先定義何謂 doc 類，等同引入已被 Non-Goals 排除的分流 rubric；(b) 把 trickle-NITs 改寫成適用新規則——否決，等於在新機制上再長一個例外路徑，而例外路徑正是本 change 要減少的東西。

### 契約檢查器以純函式暴露

`test_convergence_contract.py` 的檢查邏輯 MUST 以純函式暴露：

```python
def check_convergence_contract(text: str) -> list[str]:
    """回傳失敗訊息清單；空清單代表全數通過。"""
```

測試以合成 fixture 呼叫該函式，而非只對真實 SKILL.md 斷言。

**為何選此**：**只對真實檔案斷言的測試檔，無法測試自己的失敗路徑。** 沒有純函式入口，「錨點消失時必須變紅」「空檔案不得空洞通過」「行數 +1 必須失敗」這些負向案例全部無法實作，檢查器就退化成「永遠綠、無資訊量」的裝飾——正是本 repo 反覆記錄的失效模式（一個 guard 的 PASS 在你證明它會對已知壞輸入失敗之前沒有資訊量）。此決策由 Step 2 的 qa-test-designer 指出，屬設計層而非測試細節。

**替代方案**：只對真實檔案斷言——否決，理由如上；以 monkeypatch 抽換檔案路徑——否決，可行但把「純資料轉換」偽裝成 I/O，且 fixture 需落地暫存檔，比純函式更慢更脆。

### 以行數預算作為本 change 的自我約束

`plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 於本 change 完成後的行數必須 **≤ 1220**（改動前的現況）。此條件以機械檢查實作。

**為何選此**：該檔 55 次修改中僅 1 次為真正的簡化，是「只進不出」最直接的證據。若本 change 為了加入證據閘門與輪數預算而讓它變長，就是用它要治的病去治病——成為第 56 個淨加的 commit。此預算把「設計要示範自己的主張」從自我期許變成可驗證的條件。移除項（NIT 約定句、circuit breaker 舊門檻、可能冗餘的 R2 跳過邏輯）提供的空間必須足以容納新增項。

**替代方案**：不設預算，靠 review 把關——否決，本 change 的整個前提就是「靠 review 把關的東西會失控」。

## 資料模型與 API

**不適用。** 本 change 的產物為 SKILL.md runbook 與其驗證測試，**無 Entity、無 DB schema、無 API endpoint、無 Pydantic model**。event-storming.md 識別的三個 aggregate（`Finding` / `ReviewRound` / `DeferralBatch`）是**概念模型**，用於界定不變式與檢查決策表是否有空格，**不對應任何將被建立的 Python class**。

此節刻意留白而非硬填：為一個沒有資料層的 change 發明 Entity 表格，會讓後續讀者誤以為有東西要實作。

DBC 對應（require / ensure / invariant → Pydantic validator）同樣不適用，改以測試落地，見 problem-frame.md 的 DBC 對應表。

#### 衝突偵測

`effort=high` 規定必做。逐項確認：

- [x] **前置確認**：`openspec/specs/` 是否有既有 specs？**不存在**（本 repo 的 openspec 目錄僅有 `changes/`，無 baseline specs）→ 本 change 為 **baseline，無既有 spec 可衝突**。以下各項據此檢查其餘衝突面。
- [x] **Entity 命名**：不適用——本 change 不引入 Entity。
- [x] **API endpoint**：不適用——本 change 不引入路由。
- [x] **共用資料表**：不適用——本 change 不動 DB。
- [x] **Event / Message schema**：`prompt-r1.md` 的 finding 格式是 voice 與 aggregator 之間的實質 message schema。新增 `Evidence:` 為**加欄**，既有欄位不變，故對只認得舊欄位的消費者向後相容。**風險點**：`codex-r1-stage1.sh` 與 `agy_validate.py` 的 agentic-hijack 偵測器以 `## Summary|Findings|Verdict` 標題為判準；新增欄位位於 finding 區塊內、不動這三個標題，故偵測器不受影響（W8，需於實作時實測確認）。
- [x] **權限模型**：不適用——本 change 不引入存取控制。**但相鄰**：`gh issue create --label` 需要 `deferred-from-review` 標籤存在，否則失敗；此為前置條件而非權限衝突，已列入 tasks。
- [x] **與既有 skill 的命名衝突**：`pr-review-convergence` 為新 capability slug，`spectra list` 顯示無同名 change 或 spec。
- [x] **與 sibling skill 的行為衝突**：`/pr-cycle-fast` 與 `/pr-review-cycle` 各自有獨立 SKILL.md 與獨立的 severity 約定；本 change 只改 `pr-cycle-deep`，不會使三者的 severity 語意在同一份文件內矛盾。**但會使三者之間不一致**——這是刻意的（見 Risks）。

## Implementation Contract

#### 範圍邊界

**In scope**：`pr-cycle-deep` 的 severity 定義、`prompt-r1.md` 的內容規格、Step 5 aggregator 的降級與三分法規則、Step 7 的輪次契約與 circuit breaker 門檻、降級出口的路由規則，以及驗證上述契約的純函式檢查器與其測試。

**Out of scope**：R1／R2 的 debate 機制、voice 的偵測與模型選擇、`setup-review-dir.sh` 的 diff 產生邏輯、其餘 pr-flow skill、rules corpus 的內容、golden-transcript eval harness。

#### 可觀察行為

1. **reviewer 輸出含證據欄位**：`prompt-r1.md` 產生的 review，其每個 finding 區塊包含 `Evidence:` 欄位，且該 prompt 明列封閉的證據形式表。
2. **降級是 aggregator 的預設行為**：無有效證據的 Critical／Important 出現在降級清單而非 blocking 清單，且降級理由被明白寫出（「無證據」而非消失），原標題與描述逐字保留。
3. **三分法可觀察**：Critical 證據的執行結果被記為重現／未重現／無效之一；無效者出現在 deferred 且標為 Important，不出現在「未重現」的紀錄中。
4. **Round 2 的 blocking 只含 Critical**：Important 與 NIT 一律進降級清單。
5. **不存在 Round 3**：Round 2 結束後流程走向 merge 或 circuit breaker，不再進入 fix → re-review。
6. **NIT 永不 blocking**：任何輪次的 NIT 都不出現在 blocking 清單。
7. **降級出口可觀察**：降級 Important 存在時恰建立一張 `deferred-from-review` issue；僅有降級 NIT 或無降級時不建立 issue。
8. **檢查器可被合成 fixture 呼叫**：`check_convergence_contract(text)` 為純函式，對錨點缺失、空文字、超行的輸入皆回傳非空失敗清單。

#### 驗收條件

以 `plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py` 機械驗證，每項須可獨立失敗。完整 TC 表與覆蓋分析見 `testplan.md`；此處列契約層的驗收：

- **行數預算**：`plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 行數 ≤ 1220（PRC-VL-001~005）。
- **NIT 約定句已移除（兩個變體各一條斷言）**：全文不含 `cleans up every **undisputed actionable NIT**`（severity 表變體），亦不含 `this skill's convention cleans up every actionable NIT`（Step 5 變體）。以**字串內容**為錨點，不以行號定位。單一字串比對只會命中後者，前者會留存而回報綠燈。
- **NIT 不再 blocking 的 6 個站點皆已處置**：severity 表、Step 5 override 散文、Step 5 彙整表 NIT 列、`final.md` NIT 段標題、收斂條件的 NIT 項、`LGTM-with-trickle-NITs` 整段。全文不含 `user requires all NITs cleaned up` 與 `user emphasized` 的 NIT 歸因，亦不含 `LGTM-with-trickle-NITs`。
- **prompt 含證據欄位規格**：`prompt-r1.md` 內容規格區塊含 `Evidence:` 欄位（PRC-DT-001）。
- **證據分類表完整且封閉**：五個類型齊備，且無 catch-all 列（PRC-DT-037）。
- **三分法齊備且相異**：三種執行結果各有相異處置，`repair once` 錨點存在（PRC-DT-043/044/045）。
- **輪數契約存在**：明載 Round 2 僅 Critical 可 blocking、Round 3 不存在（PRC-ST-003/005）。
- **終止不依賴審查面大小**：文件不含以審查面縮小為終止條件的措辭（PRC-ST-006）。
- **circuit breaker 門檻已更新**：不含「連續 3 輪」的舊門檻描述。
- **檢查器對壞輸入必紅**：每個必要錨點的單點 mutation 皆被殺（PRC-EG-006）；空文字不得空洞通過（PRC-EG-001）；路徑不存在須 `[FAIL]` 而非 skip（PRC-EG-005）。

錨點策略須遵循本 repo 既有教訓：測試若因錨點字串過時而找不到目標，**必須 `[FAIL]` 而非略過**——一個因為找不到目標而靜默通過的驗證等於不存在。錨點比對須以 `Path.read_text(encoding="utf-8")` 讀原始 UTF-8（錨點含全形與 CJK 字元，ASCII 替代會靜默不匹配）。

#### 失敗模式

- 若 SKILL.md 行數超出預算 → 測試失敗，訊息須同時指出實際行數與預算，促使實作者回頭刪除而非放寬預算。
- 若移除「待評估」的 R2 跳過邏輯後發現其仍被 Step 7 依賴 → 保留該段並於 tasks 記錄，行數預算改由其他移除項吸收；**不得以「預算放寬」作為解法**。
- 若新增 `Evidence:` 欄位破壞了 agentic-hijack 偵測器 → 該偵測器會對正常 review 輸出誤報 `[FAIL]`。實作時須以真實 review 輸出實測確認（W8）。
- 若 `deferred-from-review` 標籤不存在 → `gh issue create --label` 失敗。SKILL.md 該步驟須含標籤缺失時的 `[FAIL]` 提示。

## Risks / Trade-offs

- **[Round 2 僅 Critical 可擋，fix 引入的 Important 問題會被放行]** → 刻意的取捨而非疏漏。緩解：這些問題進批次 issue 有追蹤；且現況的替代方案並非「擋下來」，而是「跑到第 5 輪後使用者疲勞直接 merge」——後者更糟，因為它假裝有守門。
- **[reviewer 寫不出有效證據，真問題被降級]** → 這是 problem-frame.md 的 W1，本 change 最大的假設風險。緩解：logic/security 改收 failure scenario（reviewer 只需 diff 即可導出）；三分法把「證據無效」與「缺陷不存在」分開，無效者降級保留而非 drop。殘餘：仍會有真 finding 因證據形式不便而降級，接受此代價以換取迴圈有下界。
- **[lead 不遵守「Critical 證據必跑」的約定]** → W4。lead 為 LLM，此為 runbook 約定而非機械強制。無法以 pytest 驗證（testplan 已誠實標示）。緩解：契約寫成決策表而非散文，降低誤讀機率；殘餘由 golden-transcript harness 收斂，該 harness 不在本 change 範圍。
- **[契約測試全綠被誤讀為「行為正確」]** → testplan 的 21 個 scenario 僅 3 個可完全自動化，18 個是 LLM 執行期行為。緩解：TC 表以 `[mech]`／`[doc]`／`[manual]` 前綴標示每個 TC 證明了什麼，testplan 明講「契約測試全綠只證明文件符合性」。
- **[行數預算被以壓縮散文的方式規避]** → 預算只能檢查行數，無法檢查資訊密度。緩解：預算的目的是強制「加東西前先想刪什麼」，而非追求最短；若實作時發現必須壓縮既有內容才能過關，該現象本身即為「應該移除更多」的訊號，於 tasks 中處理而非改預算。
- **[三個 pr-flow lifecycle skill 的 severity 語意變得不一致]** → 本 change 只改 `pr-cycle-deep`，`/pr-cycle-fast` 與 `/pr-review-cycle` 仍沿用舊約定。使用者切換 skill 時會遇到不同的 blocking 規則。接受：三者本就服務不同場景且各有獨立 runbook；若證據閘門在 deep 上被證實有效，再評估移植。
- **[本 change 的 PR 會被改動前的舊 skill 來 review]** → 舊規則（NIT blocking、無輪數上限）可能讓它重現它要修的問題。緩解：知悉即可，必要時對本 PR 手動採用新規則；不因此阻擋。
- **[baseline SHA 因 stale ref 而使 Round 2 審查面靜默膨脹]** → CLAUDE.md 已記錄兩個實例：stale fork 的 `origin` 使 `git diff origin/main...HEAD` 膨脹成數百個無關檔案；`codex review --base <SHA>` 回傳 stale cache。兩者皆無錯誤訊息。緩解：testplan 的 Missing Coverage (c) 已標明需補「baseline 新鮮度檢查」的 TC；實作時須在 Round 2 界定審查面前確認 baseline 新鮮度。

## Migration Plan

skill 的行為改動於 SKILL.md 合併後即對新的 `/pr-cycle-deep` 呼叫生效，無資料遷移。

需注意本 repo 既有的安裝機制陷阱：`pr-cycle-deep` 透過 plugin 通道散布，而部分 skill 是直接 symlink 進 repo checkout。合併後應在主 repo 執行 `git pull`，並依該 skill 的散布方式決定是否需要重新安裝，再驗證載入的是新版本——本 repo 已有「合併後 `/pr-retro` 載到舊版 skill body」的前例。

Rollback：`git revert` 該 commit 即回復舊行為，無殘留狀態。

## Open Questions

- Step 7 中「LGTM 的 voice 跳過 R2」的 token 節省邏輯，在 Round 2 改為 regression-only 後是否整段冗餘？實作時細讀該段後確認。若仍有必要則保留，行數預算由其他移除項吸收。
- 批次 issue 的建立時機：Round 2 結束後一次建立，或每輪各建一張？傾向前者（一個 PR 一張），但需確認 circuit breaker 路徑（人類裁決）下該 issue 是否仍應建立。
- `deferred-from-review` 標籤是否需先於 repo 建立？`gh issue create --label` 對不存在的標籤會失敗，需於 tasks 確認。
- 是否以 PATH 上的假 `gh` 把 issue 建立與否的 dry-run 變成可重跑的自動化測試？testplan 建議此法可將 `many-important-one-issue` / `nit-only-no-issue` 從 partial 推向 covered。範圍與成本待評估，可能另開 change。
