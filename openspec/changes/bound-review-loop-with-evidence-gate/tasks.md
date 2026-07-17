# tasks.md — bound-review-loop-with-evidence-gate

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。
> 推導依據：US-002（輪數上限）與 US-001（證據閘門）為核心路徑——US-003 的降級出口以它們的產物為前提，
> 故 P1；行數預算為交付門檻而非功能，列於 Phase 5 驗證。無 [P] 標記：`.spectra.yaml` 未啟用 `parallel_tasks`。

## Phase 1：Foundational（阻斷性前置依賴）

先行執行：行數預算（C3）要求本 change 淨不增行，必須先騰出空間再加新內容；
`deferred-from-review` 標籤不存在會使後續 `gh issue create --label` 失敗。

- [x] T001 依 design「移除 NIT 的 blocking 效力」，使 Actionable NIT 在任何輪次都不構成 merge gate，並恢復 `plugins/pr-flow/skills/pr-cycle-deep/SKILL.md` 與其宣告 owner（`/pr-review-cycle` 的 canonical severity 標準，該表對 NIT 寫 `Does not block merge — fix opportunistically`）的一致性（`Actionable NIT never blocks merge`）：處置 design 決策表列出的**全部 6 個站點**——severity 表 NIT 列、Step 5 的 project-override 散文、Step 5 彙整表 NIT 列、`final.md` 的 NIT 段標題、收斂條件中的 NIT 項、`LGTM-with-trickle-NITs` 整段（後者整段刪除）。驗證：PRC-DT-003 / PRC-DT-004 對**兩個變體**各有斷言（`cleans up every **undisputed actionable NIT**` 與 `this skill's convention cleans up every actionable NIT`——單一字串只會命中後者）；全文不含 `LGTM-with-trickle-NITs`、`user requires all NITs cleaned up`。不得觸碰 `/pr-review-cycle`（Non-Goals）。
- [x] T002 處置 design「Open Questions」列出的 R2 跳過邏輯：細讀 Step 7 中「LGTM 的 voice 跳過 R2」的 token 節省段落，判定其在 Round 2 改為 regression-only 後是否冗餘。冗餘則移除，否則保留並記錄理由。驗證：內容 review 並在 PR 描述記載判定結果；**不得**以「放寬行數預算」作為保留後的補償手段（design「失敗模式」明列）。
- [x] T003 使 `deferred-from-review` 標籤於 repo 存在，讓降級出口的 `gh issue create --label` 不致失敗（`Demoted findings have a defined destination`）：查詢現有標籤，不存在則建立；並於 SKILL.md 對應步驟加入標籤缺失時的 `[FAIL]` 提示。驗證：`gh label list` 可見該標籤；SKILL.md 該步驟含失敗處置說明。

## Phase 2：證據閘門（P1 — 核心路徑，US-001 與 US-002 皆以其產物為前提）

### US-001：blocking 主張必須可複驗（P1 — 核心路徑）

**Story Goal**：擋 merge 的每個理由都能被一條指令複驗，提不出證據的意見仍被記錄但不擋人。
**Test traceability**：AC-001-1~4 → TC PRC-DT-011~023、PRC-DT-031~037、PRC-DT-041~045、PRC-DT-051~053
  Verification: `pytest -k "PRC-DT-011 or PRC-DT-012 or PRC-DT-019 or PRC-DT-023 or PRC-DT-031 or PRC-DT-035 or PRC-DT-037 or PRC-DT-043 or PRC-DT-044 or PRC-DT-045 or PRC-DT-053"`

- [x] T010 依 design「證據閘門作為 blocking 的前提條件」，使 reviewer 產出的每個 finding 帶有 `Evidence:` 欄位（`Blocking findings require executable evidence`）：於 SKILL.md 的 `prompt-r1.md` 內容規格區塊，在 finding 格式中新增該必填欄位，說明其語意為「lead 可據以複驗該缺陷的證據」。驗證：PRC-DT-001（`Evidence:` 錨點存在）。
- [x] T011 依 design「證據形式依 finding 類型分類」，使 reviewer 對「什麼算證據」無解讀空間，且 logic/security 不被要求交出它無從得知的指令（`Evidence forms are enumerated by finding type`）：於 prompt 規格區塊加入**封閉式**證據分類表，五類齊備（logic/security 收 failure scenario、test gap 收存活 mutation、doc 事實錯誤收證明指令、命名不一致收 grep ≥2 siblings、精確度類無可接受形式），且不得有 catch-all 列。驗證：PRC-DT-031（logic 收 scenario 且不要求指令）、PRC-DT-035（精確度恆降級）、PRC-DT-036（sibling 門檻為 2）、PRC-DT-037（封閉列舉，5 列無 catch-all）。
- [x] T012 使無有效證據的 finding 於彙整階段被降級而非消失，且原標題／描述／降級理由逐字保留（`Blocking findings require executable evidence`）：於 SKILL.md Step 5 aggregator 規則加入降級判定與 deferred 區塊的內容義務。驗證：PRC-DT-012（理由須為 absent evidence）；並依 testplan「Missing Coverage (a)」把「逐字保留／must not silently discard」的措辭加入 PRC-DT-002 的必要錨點清單——此為目前最弱的一環。
- [x] T013 依 design「驗證成本分層與三種執行結果」，使閘門的多數淘汰不需執行任何指令（`Evidence verification is tiered by severity`）：於 Step 5 明載三層——證據缺漏或格式不符者結構檢查直接降級、Critical 必驗、Important 選擇性抽驗。驗證：PRC-DT-051（Critical must execute）、PRC-DT-052（Important selective）、PRC-DT-053（格式不符者不執行任何東西）。
- [x] T014 依 design「驗證成本分層與三種執行結果」，使「證據跑不起來」不再被當成「缺陷不存在」而誤殺真缺陷（`Evidence verification is tiered by severity`）：於 Step 5 加入三分法表——重現留 blocking／未重現移出並記錄／**無效**則修復一次、修不好降為 Important 進 deferred 且絕不 drop、絕不記為未重現。驗證：PRC-DT-041/042/043/044（三項義務齊備）、PRC-DT-045（三列處置互異）。
- [x] T015 使 severity × evidence × round 的決策表無空格（`Blocking findings require executable evidence`）：於 SKILL.md 以表格明載 12 個組合（3 severity × 2 evidence × 2 round）各自的處置。驗證：PRC-DT-023（12/12 解析為 blocking／deferred／non-blocking 之一，0 未定義、0 歧義）；PRC-DT-011~022 逐格斷言，其中 PRC-DT-019（R2 Important 有證據仍 deferred）為最關鍵的反直覺格位。

## Phase 3：輪數契約（P1 — 核心路徑，收斂保證的來源）

### US-002：迴圈在有限輪數內離開（P1 — 核心路徑）

**Story Goal**：迴圈必在 2 輪內離開，出口是 merge 或人類裁決，不存在「再跑一輪看看」。
**Test traceability**：AC-002-1~4 → TC PRC-ST-001~007
  Verification: `pytest -k "PRC-ST-001 or PRC-ST-003 or PRC-ST-004 or PRC-ST-005 or PRC-ST-006 or PRC-ST-007"`

- [x] T020 依 design「輪數上限保證終止，審查面縮限降低成本」，使迴圈必在 2 輪內離開（`Review surface is bounded to two rounds`）：於 SKILL.md Step 7 以表格明載 Round 1 審完整 diff 並**記錄** baseline head SHA、Round 2 審 `baseline..HEAD` 且僅 Critical 可 blocking、Round 3 不存在。驗證：PRC-ST-001（R2 審查面為 delta 而非完整 diff）、PRC-ST-003（R2 空則 merge，R3 不開始）、PRC-ST-005（R3 不可達，`Round 3` 只出現在 does-not-exist 列）；並依 testplan「Missing Coverage (b)」補錨點斷言 runbook 要求**記錄** SHA——沒有它審查面規則不可實作。
- [x] T021 使文件不再宣稱終止來自審查面遞減（`Review surface is bounded to two rounds`）：於 Step 7 明載兩個 commit range 不相交、非子集、Round 2 大小無保證，並明載終止僅依賴輪數上限。驗證：PRC-ST-006（全文無以審查面大小為條件的終止措辭：`smaller` / `narrower` / `subset` / `遞減`）。此為修正初版設計的錯誤宣稱，見 problem-frame.md 的反面對照。
- [x] T022 使 Round 2 結束仍有未解 Critical 時進入人類裁決而非第 3 輪（`Review surface is bounded to two rounds`）：將 circuit breaker 觸發條件由「連續 3 輪未達成全員 LGTM」改為「Round 2 結束且 blocking 集合非空」，沿用既有三選項 UX。驗證：PRC-ST-004（進入 circuit breaker，無自動第三輪）；全文不含「連續 3 輪」的舊門檻描述。
- [x] T023 使 merge 閘門僅以 blocking 集合定義，NIT 任何輪次皆不擋（`Actionable NIT never blocks merge`）：於 Step 7 明載 merge 條件。驗證：PRC-ST-007（blocking 空且 NIT 未解時放行）、PRC-DT-015/016/021/022（NIT 四格皆非 blocking，實作為單一 parametrized 測試配 4 個 id，非 4 份複製）。
- [x] T024 依 design Risks「baseline SHA 因 stale ref 而使審查面靜默膨脹」，使 Round 2 界定審查面前確認 baseline 新鮮度：於 Step 7 加入新鮮度檢查要求（CLAUDE.md 已記錄 stale fork `origin` 與 `codex review --base` stale cache 兩個實例，兩者皆無錯誤訊息）。驗證：依 testplan「Missing Coverage (c)」新增 TC 斷言 runbook 要求該檢查；目前不存在此 TC。

## Phase 4：降級出口（P2 — 依賴 Phase 2 的降級判定產物）

### US-003：降級的意見有明確去處（P2 — 中等複雜度，無阻斷性依賴）

**Story Goal**：每筆 finding 都有去處且不重複堆積；不用製造新累積器的方式解決舊累積器。
**Test traceability**：AC-003-1 → TC PRC-DT-061~065
  Verification: `pytest -k "PRC-DT-061 or PRC-DT-062 or PRC-DT-063 or PRC-DT-064 or PRC-DT-065"`

- [x] T030 依 design「降級 finding 的雙軌出口」，使降級 Important 進入有人承接的清單、NIT 留在既有 PR comment（`Demoted findings have a defined destination`）：於 SKILL.md 加入路由規則——每個 PR **至多一張**批次 issue 收錄所有降級 Important、標記 `deferred-from-review`；降級 NIT 不開票；無降級 Important 時不建立。驗證：PRC-DT-061（3 筆→1 張列 3 筆）、PRC-DT-062（1 筆→1 張）、PRC-DT-063（僅 NIT→0 張）、PRC-DT-064（無降級→0 張）、PRC-DT-065（混合→1 張只列 Important）。文件不得出現「每個 finding 一張」的表述。
- [x] T031 確定批次 issue 的建立時機（design「Open Questions」）：判定於 Round 2 結束後一次建立，並確認 circuit breaker 路徑（人類裁決）下是否仍建立。將結論寫入 SKILL.md 對應步驟。驗證：內容 review 確認 SKILL.md 對兩條路徑（正常收斂、circuit breaker）皆明載 issue 建立與否。

## Phase 5：契約檢查器與驗證（P1 — 交付門檻）

**Test traceability**：AC-003-2~3 → TC PRC-VL-001~005、PRC-DT-001~004、PRC-EG-001~007、SMK-001~002
  Verification: `pytest plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py -q`

- [x] T040 依 design「契約檢查器以純函式暴露」，使負向測試可行（`Skill document line budget`）：於 `plugins/pr-flow/skills/pr-cycle-deep/scripts/tests/test_convergence_contract.py` 實作純函式 `check_convergence_contract(text: str) -> list[str]`，回傳失敗訊息清單。錨點比對以 `Path.read_text(encoding="utf-8")` 讀原始 UTF-8（C5：錨點含全形與 CJK，ASCII 替代會靜默不匹配）。驗證：PRC-DT-001（錨點齊備回傳空清單）、PRC-DT-002（錨點缺失回傳含該錨點與 `absent` 的失敗）。
- [x] T041 依 design「以行數預算作為本 change 的自我約束」，使行數預算成為可機械檢查的條件（`Skill document line budget`）：於檢查器加入行數斷言，失敗訊息須同時含實際行數與預算。驗證：PRC-VL-001（1220 通過）、PRC-VL-002（1221 失敗且訊息含 1221 與 1220）、PRC-VL-003（1219 通過）、PRC-VL-004（末行無換行不 off-by-one）、SMK-002（真實檔案行數有印出且 ≤ 1220）。
- [x] T042 使檢查器對「沒東西可查」的輸入大聲失敗而非空洞通過（`Skill document line budget`）：加入空文字與路徑不存在的處置。驗證：PRC-EG-001（空文字回傳非空失敗列出所有缺失錨點，**絕不**因 0 ≤ 1220 而通過）、PRC-EG-005（路徑不存在 `[FAIL]` 指出該路徑、非零 exit、非 pytest skip）。
- [x] T043 使含 CJK／全形字元的錨點以真實 UTF-8 位元組比對（`Skill document line budget`）：驗證：PRC-EG-002（中文禁字原文被偵測，且 ASCII 轉寫版不被誤判）、PRC-EG-003（禁字在 code fence 內的結果須為明文刻意的決定——偵測或以明述範圍略過，絕非意外繞過）。
- [x] T044 使每個必要錨點與行數預算皆通過 mutation 驗證，證明 guard 有能力變紅（`Skill document line budget`）：對每個必要錨點，複製真實文字、**只**刪該錨點、斷言檢查器失敗並指名它、還原——**每次迭代只做一個 mutation**（複合突變會因錯的理由變紅，給出假的「已驗證」）。行數同法 ±1。驗證：PRC-EG-006（N/N 突變體被殺；存活即代表該錨點實際未被檢查、綠燈無資訊量）、PRC-EG-007（±1 行兩個突變體皆被殺）。
- [x] T045 決定 PRC-VL-005（CRLF）與 PRC-EG-004（重複錨點）的去留（testplan「Redundant TCs」）：**先確認** repo 是否以 `.gitattributes` / pre-commit 強制 LF、檢查器是否用 `in` 而非計數斷言，再決定刪或留。驗證：結論寫入 testplan 的 Redundant 表；不得未經確認即刪除。
- [ ] T046 確認全量 CI 通過且工作樹乾淨：執行 `make ci`，隨後確認 `git diff --name-only` 為空（formatter hook 就地改檔會使本地綠燈與 commit 出來的樹不一致）。驗證：SMK-001（契約套件 exit 0 且收集到測試，收集到 0 個為失敗）；`make ci` 全綠且 `git diff --name-only` 輸出為空——非空則先 commit 該改寫再 push。

## Phase 6：SDD 文件同步與收尾

- [ ] T050 執行 `spectra analyze bound-review-loop-with-evidence-gate --json` 與 `spectra validate`，使 Critical + Warning 為 0。驗證：analyze 輸出的 Critical/Warning 計數為 0；validate 回報 valid。
- [ ] T051 每輪 fix 後同步 openspec 文件：本 repo 既有教訓——多輪 fix 會讓 `design.md` / `testplan.md` / `tasks.md` 與實作逐輪漂移，下一輪 reviewer 會找到「新增的測試／邏輯未記錄於 design」。把「同步本輪改動的 openspec 文件」當每輪的固定清單項，而非最後一次性補。驗證：每輪 fix 結束時 `spectra analyze` 的 Critical/Warning 仍為 0。
- [ ] T052 於 PR 描述明載：契約測試全綠只證明**文件符合性**，21 個 scenario 中 18 個為 LLM 執行期行為、pytest 不可驗證（testplan 已標）。驗證：PR 描述含該聲明；不得讓綠燈被誤讀為行為證明。
