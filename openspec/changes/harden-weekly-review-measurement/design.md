# Design：harden-weekly-review-measurement

> 狀態：Draft。下方「待裁決」各項在 owner 決定前不得進入 apply。

## Context

本文的函式名稱、欄位名稱與行為，都是 2026-10-01 對 `8edb41d8` 的 harness_review.py 讀碼確認的結果（不寫行號，行號會漂移）。

| 資料來源 | 目前的完整性訊號 | 漏洞 |
|---|---|---|
| hook inventory（collect_hook_inventory） | `complete` 起始 True，只在 settings 檔讀取／解析失敗時設 False | hook 腳本讀不到只記 warning 並存成空字串，`complete` 仍 True，進而產生假的 hook-unregistered；hooks 目錄 `iterdir` 未防護，讀不到時直接拋例外 |
| hook events（collect_hook_events） | `covers_window = bool(files) and not reasons` | 讀檔沒有傳 `failed`；格式錯誤行只記 warning；不檢查觀察期中段缺口；目錄 `iterdir` 未防護 |
| transcripts（collect_transcript_blocks） | `read_failures = len(failed)` | 截斷的 JSON 行不算讀取失敗；transcript_files 的 `os.walk` 沒有 `onerror`，目錄錯誤被靜默丟棄 |
| rules（collect_rules） | 只有 `unreadable[]`，沒有 `complete` | `glob("*.md")` 失敗時靜默回空，上週的 rule 類建議全部變 resolved |
| workflows／gates（collect_gate_inventory） | `workflows_complete` 起始 True，單檔讀取失敗才設 False | `glob("*.y*ml")` 靜默回空；gate 上線日期的 `git log --diff-filter=A` 沒有 `--follow`，改名或 shallow clone 會回傳近期日期 |
| CI（collect_ci_failures） | `complete`，多數失敗路徑已設 False | runs 清單用 `.get("workflow_runs", [])`，不比對 `total_count`，回應形狀不符時被當成 0 筆失敗 |
| 上週快照（resolve_prev／diff_snapshots） | 版本必須等於 SNAPSHOT_VERSION（目前為 2） | 只跑過 collect、沒跑過 report 的快照沒有 `carried`／`weeks`，carried 建議會靜默消失、週數歸零，也沒有 `streak_reset`；`--prev auto` 遇到壞 JSON 會 exit 2，SKILL.md 沒寫 |

判定層：evaluation_scope 產生 `kinds`／`unevaluated_ids`／`unevaluated_prefixes`。diff_snapshots 對「上週有、本週沒有」的建議，在「kind 在 scope 內且未被列為 unevaluated」時判 resolved，沒有逐對象的觀察或樣本檢查。

## Goals / Non-Goals

**Goals**

- G1：任何資料來源的任何讀取失敗，都不會讓依賴該來源的上週建議被判成 resolved
- G2：resolved 必須有正向證據（來源完整，且對象本週有被觀察到、樣本達門檻）
- G3：歸因只接受精確身分，不確定一律不可歸因
- G4：用家族層級的注入測試取代逐條補洞，並以 mutation 證明每個注入點都有測試守住

**Non-Goals**：與 proposal 相同。另外，不追求「讀取失敗時仍盡量給出結論」：寧可多報 unmeasured，也不可誤報 resolved。

## Decisions

### D1：Source 完整性結構

每個 collector 回傳 `source: {complete: bool, errors: [str]}`，`complete` 預設 False，在函式最後一步才依「errors 為空」設為 True。目錄列舉改用共用的 helper：用 `os.scandir` 包 try，把 OSError 寫進 errors，不再使用 `Path.glob`、未防護的 `iterdir`、沒有 `onerror` 的 `os.walk`。逐行解析的格式錯誤也寫進 errors。

被否決的方案：沿用各 collector 現有的不同欄位（`covers_window`、`read_failures`、`unreadable`、`workflows_complete`），只修預設值。否決理由是四種形狀讓 evaluation_scope 必須逐一記得每種欄位的語意，這正是三輪漏網的來源。

### D2：evaluation_scope 對缺漏欄位保守

任何來源的 `source` 欄位缺漏、型別不符，或 `complete` 不是 True，都視為該來源量不到。`ci.measured` 缺漏時不再拋 KeyError，同樣視為量不到。docstring 改為描述實際行為。

### D3：resolved 需要逐對象的正向證據

每種建議類型宣告自己的「觀察證據」：

| 建議類型 | 判 resolved 所需的本週觀察 |
|---|---|
| hook-error／hook-slow／hook-silent-block | 該 hook 本週呼叫次數 ≥ 門檻 N_hook（見待裁決 Q1） |
| hook-unregistered | 該 hook 腳本本週讀取成功，且 inventory 完整 |
| transcript 類 | transcript 來源完整，且 `in_window` ≥ 門檻 N_transcript |
| rule 類 | rules 來源完整，且該 rule 檔本週讀取成功 |
| gate-silent | CI 完整、gate 可歸因、上線日期確定，且觀察期內該 job 至少執行 1 次 |
| gate-unwired | workflows 來源完整 |

不滿足時判 unmeasured 並 carried，與現行 carried 的語意相同。DT-029 正向對照（`hooks: {}` 判 resolved）改寫為「判 unmeasured」。

### D4：歸因只接受精確身分

gate-silent 改為比對 workflow 檔名、job id、step 名稱三者的精確值，移除 `stem in key.casefold()` 與 `stem in s.casefold()`。`_gate_attribution_problem` 新增三種不可歸因的情況：任何 step 名稱含 `${{`、名稱含跳脫序列、名稱是多行 plain scalar。`yaml_scalar` 遇到無法完整解析的雙引號跳脫或多行 plain scalar 時回傳 None，不再回傳部分字串。

### D5：gate 上線日期

改用 `git log --follow --diff-filter=A`；repo 是 shallow clone（`git rev-parse --is-shallow-repository` 為 true）時，日期一律為 None，gate-silent 判 unmeasured。

### D6：上週快照的 carried 資訊缺漏

上週快照沒有 `carried` 或 `weeks` 時（只跑過 collect），本週對所有延續中的建議標記 `streak_reset: true`，並在報告中寫出原因。`--prev auto` 遇到壞 JSON 時維持 exit 2，但 SKILL.md 的 exit 2 列要補上這個成因，「最後一份」的說明要寫明會略過版本不符的快照。

### D7：快照版本

判定語意改變，SNAPSHOT_VERSION 從 2 升為 3。版本不符的舊快照依現行規則被略過，所以升級後的第一週沒有可比較的上週，所有週數從 1 開始。

## Risks / Trade-offs

- **unmeasured 會變多**：正向證據門檻讓低流量的 hook 長期處於 unmeasured。這是刻意的取捨，但報告需要讓 unmeasured 一眼可辨，不能與 resolved 混在一起。
- **升版導致週數歸零一次**：見 D7。替代方案是寫 v2→v3 的遷移，但 v2 的 resolved 判定本身不可信，遷移等於沿用錯誤結論，所以不建議。
- **共用列舉 helper 是新的單點**：helper 若自己吞掉錯誤，所有 collector 會同時失守。家族層級測試必須直接對 helper 注入目錄錯誤。

## 待裁決（owner）

- **Q1**：N_hook 與 N_transcript 的值。建議先沿用產生新建議時的 `calls >= 3`，讓「產生」與「解除」用同一個門檻；也可以另設較高的解除門檻，避免建議在門檻附近反覆出現又消失。
- **Q2**：是否接受 D7 的「升版後週數歸零一次」，還是要求寫遷移。
- **Q3**：D4 移除子字串比對後，現有 workflows 中若有 gate 只靠子字串才能歸因，它們會從「可歸因」變成「不可歸因」，gate-silent 不再對它們發報告。是否接受這個覆蓋面縮小？實作前會先列出受影響的 gate 清單。
- **Q4**：本 change 是否要等 #508 merge 後才開始實作（建議要，避免兩邊同時改 harness_review.py）。
