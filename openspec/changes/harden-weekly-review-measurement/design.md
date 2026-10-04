# Design：harden-weekly-review-measurement

> 狀態：Q1–Q4 已於 2026-10-03 裁決（見文末「裁決紀錄」），可進入 apply。

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

每個 collector 回傳 `source: {complete: bool, errors: [str]}`，`complete` 預設 False，在函式最後一步才依「errors 為空」設為 True（`make_source`）。目錄列舉改用共用的 helper `scan_dir`：用 `os.scandir` 包 try，目錄不存在回空（不是錯誤），其他 OSError 寫進 errors，不再使用 `Path.glob`、未防護的 `iterdir`、沒有 `onerror` 的 `os.walk`。逐行解析的格式錯誤也寫進 errors。

實作的來源與記錄位置（快照 v3）：`hooks.inventory.source`、`hooks.events.source`、`hooks.transcript.source`、`rules.source`、`ci.inventory.source`（含 workflows 與 `scripts/harness` 的列舉）、`ci.failures.source`（`ci.measured` 由它導出）、`ci.failures.activity.source`（各 workflow 檔的 run 數）。舊的 `complete`、`workflows_complete` 欄位移除，避免兩份真相；`covers_window`（紀錄涵蓋的時間夠不夠）與 `read_failures`（讀不到的 transcript 檔數，只供人閱讀）保留，它們回答不同的問題。

被否決的方案：沿用各 collector 現有的不同欄位（`covers_window`、`read_failures`、`unreadable`、`workflows_complete`），只修預設值。否決理由是四種形狀讓 evaluation_scope 必須逐一記得每種欄位的語意，這正是三輪漏網的來源。

### D2：evaluation_scope 對缺漏欄位保守

任何來源的 `source` 欄位缺漏、型別不符，或 `complete` 不是 True，都視為該來源量不到。`ci.measured` 缺漏時不再拋 KeyError，同樣視為量不到。docstring 改為描述實際行為。

### D3：resolved 需要逐對象的正向證據

每種建議類型宣告自己的「觀察證據」：

| 建議類型 | 判 resolved 所需的本週觀察 |
|---|---|
| hook-error／hook-slow | 該 hook 本週呼叫次數 ≥ 門檻 N_hook（= 3，見裁決 Q1），**或**它已從完整的 hook 註冊清單消失（物件不存在） |
| hook-silent-block | 該 hook 本週呼叫次數 ≥ N_hook。**沒有**「已從清單消失」的捷徑：對象常是 plugin hook，repo 的註冊清單看不到它，「不在清單」不是證據 |
| hook-unregistered | inventory 來源完整（任一 hook 腳本讀不到即不完整，已涵蓋「該腳本本週讀取成功」） |
| transcript 類（hook-stale-plugin、hook-silent-block） | transcript 來源完整，且 `in_window` ≥ 門檻 N_transcript（= 3，見裁決 Q1） |
| rule 類 | rules 來源完整。**任何一個 rule 檔讀不到、目錄列不出來，rule 類整類本週不判定**（見下方「實作時的修訂」第 1 點） |
| gate-silent | CI 完整、gate 清單完整、gate 可歸因、上線日期確定，且 gate 所在的 workflow 在觀察期內至少跑過 1 次，**或** gate 已不存在／已不在 CI（見第 3 點） |
| gate-unwired | workflows 與 gate 清單的來源完整 |
| 其他（hook-no-data／low-signal／insurance-idle、gate-noisy…） | 只看來源完整，沒有逐對象的額外證據 |

不滿足時判 unmeasured 並 carried，與現行 carried 的語意相同。DT-029 正向對照（`hooks: {}` 判 resolved）改寫為「判 unmeasured」。

### 實作時的修訂（apply 階段發現原設計表有出入，依下列處理）

1. **rule 類整類不判定，而非逐檔**。原表同時寫「rules 來源完整」與「該 rule 檔本週讀取成功」，但 D1 規定「任一檔讀取失敗 → source 不完整」，兩者合起來只剩整類不判定。取保守的一邊（Non-Goal：寧可多報 unmeasured），舊行為「讀不到的那一檔不判定、其他檔照常 resolved」因此改變（HWR-DT-038）。代價：一個永遠讀不了的 rule 檔（例如編碼錯誤）會讓所有 rule 建議長期維持 unmeasured，warning 會每週提醒。
2. **「物件已不存在」是 hook-error／hook-slow 的正向證據**。沒有這條，被刪掉的 hook 的建議會永遠停在 unmeasured。hook-silent-block 不適用（plugin hook 在 repo 清單外），因此 plugin hook 的 silent-block 可能長期維持 unmeasured，這是接受的取捨。
3. **gate-silent 的證據是 workflow 層級，不是 job 層級**。原表寫「觀察期內該 job 至少執行 1 次」，但 CI collector 只列舉 failed run，看不到成功的 job；要 job 層級得為每個成功的 run 都抓一次 jobs，成本過高。改為對 gate 所在的每個 workflow 檔查一次 run 總數（`gh api …/workflows/<file>/runs`，只取 `total_count`），存在 `ci.failures.activity`。已知殘餘風險：workflow 有跑、但 gate 所在的 job 被 job 層級的 `if:` 略過時，會被當成有觀察到。gate 已不存在或已不在 CI 時，gate-silent 的對象不存在，視為正向證據（`gate-unwired` 另行處理）。

### D4：歸因只接受精確身分

gate-silent 只接受精確身分，移除 `stem in key.casefold()` 與 `stem in s.casefold()`。`_gate_attribution_problem` 新增三種不可歸因的情況：**同一個 workflow 檔內**任何 step 名稱含 `${{`、名稱含無法解碼的跳脫序列、名稱是多行 plain scalar。`yaml_scalar` 遇到無法完整解碼的雙引號跳脫（只解碼 `\"`、`\\`、`\/`）或多行 plain scalar 時回傳 None，不再回傳部分字串。

**「三者精確值」的實作方式**：原文寫比對 workflow 檔名、job id、step 名稱三者。實作只比對 step 名稱（不分大小寫、完全相同），因為 job id 在 jobs API 的回應裡不存在（只有顯示名稱），要比對得另外解析 workflow 的 job 區塊，且 job 顯示名稱可含 matrix 與運算式。取而代之的是既有的歧義檢查：呼叫 gate 的 step 名稱若也被別的（沒有呼叫它的）step 使用，整支 gate 不可歸因。所以剩下可歸因的 gate，其 step 名稱在所有 workflow 內唯一指向它，workflow 檔名與 job 的身分由「名稱不重複」一併確立。

### D5：gate 上線日期

改用 `git log --follow --diff-filter=A`；repo 是 shallow clone（`git rev-parse --is-shallow-repository` 為 true）時，日期一律為 None，gate-silent 判 unmeasured。指令失敗或輸出不是 `true`／`false` 時同樣視為未知（None），並出現 warning：無法判斷就不下結論。

### D6：上週快照的 carried 資訊缺漏

上週快照沒有 `carried` 或 `weeks` 時（只跑過 collect），本週對所有延續中的建議標記 `streak_reset: true`，並在報告中寫出原因。`--prev auto` 遇到壞 JSON 時維持 exit 2，但 SKILL.md 的 exit 2 列要補上這個成因，「最後一份」的說明要寫明會略過版本不符的快照。

### D7：快照版本

判定語意改變，SNAPSHOT_VERSION 從 2 升為 3。版本不符的舊快照依現行規則被略過，所以升級後的第一週沒有可比較的上週，所有週數從 1 開始。

## Risks / Trade-offs

- **unmeasured 會變多**：正向證據門檻讓低流量的 hook 長期處於 unmeasured。這是刻意的取捨，但報告需要讓 unmeasured 一眼可辨，不能與 resolved 混在一起。
- **升版導致週數歸零一次**：見 D7。替代方案是寫 v2→v3 的遷移，但 v2 的 resolved 判定本身不可信，遷移等於沿用錯誤結論，所以不建議。
- **共用列舉 helper 是新的單點**：helper 若自己吞掉錯誤，所有 collector 會同時失守。家族層級測試必須直接對 helper 注入目錄錯誤。（實測：對 `scan_dir` 做「吞掉 OSError」的 mutation，HWR-DT-051 的列舉注入格全部轉紅；`os.walk` 的 `onerror` 也要有「頂層仍有可讀檔案、只有子目錄讀不到」的專屬注入格，否則會被「整個目錄 0 個檔案」這條路徑遮住。）
- **gate-silent 的觀察證據是 workflow 層級**：見「實作時的修訂」第 3 點。job 被 `if:` 略過時會被誤當成有跑；要補需要為成功的 run 抓 jobs，另案評估。
- **plugin hook 的 hook-silent-block 可能長期 unmeasured**：沒有呼叫次數可當證據，也不在 repo 的註冊清單內。它們會留在 `carried`，報告的「本週量不到」區段每週列出，不會升級。需要時由人在判讀階段直接結案。
- **一個壞掉的 rule 檔讓所有 rule 建議長期 unmeasured**：見「實作時的修訂」第 1 點；warning 每週都會出現，提醒修檔。
- **hook-events「觀察期中段缺口」沒有處理**：issue #509 第 8 項的前半（格式錯誤行）已由 source 涵蓋，後半（紀錄中段缺了幾天、但最早與最新一筆都合格，`covers_window` 仍為 True）沒有對應的 Requirement，這次也沒有實作。緩解只有間接的：hook-error／hook-slow／hook-silent-block 要本週呼叫數 >= 3 才能 resolved，但 hook-no-data／hook-low-signal／hook-insurance-idle 仍可能在有缺口的紀錄上被誤判。需要另開 issue 決定缺口的判準（連續幾天沒紀錄算缺口、與 `EVENTS_MAX_STALENESS` 的關係）。

## 裁決紀錄（owner：howie，2026-10-03）

- **Q1：N_hook = N_transcript = 3**。沿用產生新建議時的 `calls >= 3`，「產生」與「解除」共用同一個門檻，不另設較高的解除門檻。已知取捨：門檻附近的建議可能反覆出現又消失，實測若觀察到再回頭評估。transcript 類以 `in_window >= 3` 套用同一個數字（這是對裁決的解讀：原文只寫 `calls >= 3`，transcript 沒有 calls 欄位）。
- **Q2：接受** D7 的「升版後週數歸零一次」，不寫 v2→v3 遷移。
- **Q3：接受** D4 造成的 gate-silent 覆蓋面縮小。前提不變：實作前先列出受影響的 gate 清單，附在 PR 描述。
  - **實測結果（2026-10-03，對 yibi-mvp 的真實 workflow 實跑新舊兩種歸因，29 個 gate、28 個已接 CI）**：沒有任何一個 gate 從「可歸因」變成「不可歸因」，Q3 預期的覆蓋面縮小在目前的目標 repo 沒有發生。差異在反方向：10 個 gate（`ci-check-cloudrun-env.sh`、`ci-check-diff-coverage.py`、`ci-check-retirement-residual-sweep.py`、`rule-gate-change-naming.py`、`rule-gate-change-number-collision.py`、`rule-gate-ci-concurrency.py`、`rule-gate-cross-repo-refs.py`、`rule-gate-gradle-heap.py`、`rule-gate-markdown-table-pipes.py`、`rule-gate-mobile-profile-backend.py`）的名稱字根出現在別的 step 或 job 名稱裡（例如 `Assert change-naming hook stays registered in pre-commit` 是另一個檢查，不是 gate 本身）。舊的子字串比對會把那些 step／job 的失敗算成 gate 的失敗，使 gate-silent 被壓抑；精確比對之後，這些 gate 若真的沒有自己的失敗才會被報 gate-silent。這份差集只從靜態的 workflow 檔推得，實際影響要看 CI 失敗資料。
- **Q4：等 #508 merge 後才開始實作**。交班紀錄（2026-10-02）記載 #508 已 merge；apply 前以 `gh pr view 508` 確認為 `MERGED`（merge commit `b234ceaa`，2026-10-01）。本分支已把 origin/main 併進來（用 merge 而不是 rebase：分支已推上 PR #516，rebase 需要 force push）。
