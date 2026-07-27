# Tasks：add-retro-evidence-gate

## 1. 前置確認

- [x] 1.1 讀 `tasks/mycelium` 的 typed-lessons models，確認是否已有 `parked` 狀態值與 recurrence 計數欄位。行為：產出「park 是加欄或沿用既有欄位」的明確結論並記於本檔；若需加欄，確認為向後相容擴充（rule 02 type guard）。驗證：貼出 schema 相關程式碼片段與結論一句話。

  **結論（1.1）：沿用既有欄位，零 schema / DB migration。** `LessonRecord`（`tasks/mycelium/models.py:72-96`）有 `confidence: int = Field(ge=1, le=10)` 與 `tags: list[str] = Field(default_factory=list)`，但**無**專屬 `parked` 狀態欄位、**無**每筆 lesson 的 recurrence 計數欄位（`recurrence_pr_count` 在另一彙總 model）。`db.py` 確認 `lessons.tags` 為 `TEXT NOT NULL DEFAULT '[]'`（JSON 持久化，`db.py:158/359/649/1124`），且支援 `exclude_tags` LIKE 過濾（`db.py:510-521`）。
  - park = `confidence ≤ 4` + `tags` 含 `"parked"`；recurrence = `tags` 含 `"recurrence-<n>"`（同 `key` 再現時 bump）。
  - 向後相容（rule 02 type guard）：既有讀取者見到多的 tag 不崩；正常 recall 可用 `exclude_tags=["parked"]` 濾除 parked lesson。
  - Review 修正（PR #339 mob review + 本 follow-up PR）：`mycelium lessons add` 原本沒有
    `--tag` / `--tags`，且沒有 recurrence/unpark mutation 路徑；因此 task 3.6 與本檔 6.1 加入
    最小、向後相容的 `--park` CLI/service/DB 支援（不做 schema migration）。
- [x] 1.2 量測本 change 前 `.claude/rules/` 中 frontmatter 無 `paths:` key（每 session 全量載入）的檔案總行數，作為「本 change 自我約束——always-loaded 面淨增為零」的 baseline。行為：baseline 數字被記錄。驗證：印出數字並寫入本檔。

  **Baseline（1.2）：6 個 always-loaded 檔、共 3012 行**（`python3 scripts/check_always_loaded_growth.py`）：01=81、02=339、03=156、13=1391、15=752、16=293。5.1 的檢查以 `--base origin/main` 算這些檔的淨增行數，須為 0。

## 2. commit-time lint（純函式檢查器）

- [x] 2.1 實作 `scripts/lint_rule_evidence.py` 的純函式 `check_rule_evidence(diff_text) -> list[str]`，滿足需求「commit-time lint 分層強制且以純函式暴露」與設計決策「lint 分層強制 + 純函式檢查器」。行為：對 git-staged diff 判定證據標記存在性，接受結構化（`<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`）與 prose（`Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`）擇一；回傳失敗訊息清單。驗證：`uv run pytest scripts/tests/test_lint_rule_evidence.py -q`。
- [x] 2.2 實作分層強制：新增 `.claude/rules/NN-*.md` 檔或 settings.json 新註冊 hook 及其 script 缺標記 → 非零 exit 擋 commit；既有 rule 檔新增 section 缺標記 → warn-only。行為：兩類輸入產生 error vs `[WARN]` 兩種可觀察結果。驗證：test 對兩類合成 diff 分別斷言 exit code 與訊息。
- [x] 2.3 實作 new-section 偵測 heuristic（以 diff hunk 新增行中的 `^#{2,3} ` heading 為錨點）與錨點 fail-loud + UTF-8 讀取。行為：編輯既有 section 的行內變更不誤觸發 warn。驗證：fixture「編輯既有 section」不產生 `[WARN]`；錨點字串缺失時 `[FAIL]` 而非略過。
- [x] 2.4 合成 fixture 負向測試（滿足「commit-time lint 分層強制且以純函式暴露」的可測性）。行為：`check_rule_evidence` 對「有新增內容但缺證據標記（錨點缺失）」回傳非空清單，不空洞通過；對真正空的輸入（無 diff 內容可檢查）回傳空清單。驗證：`test_anchor_missing_is_not_vacuous_pass` 斷言前者非空、`test_empty_diff_returns_empty` 斷言後者為空。**修訂記錄（2026-07-25，PR #339 mob review）**：本行原寫「pytest 對兩案例斷言回傳非空」，與 `test_empty_diff_returns_empty` 實際斷言（真空 diff 回傳空清單）矛盾——這是把 proposal.md AC-003-3 的字面文字直接抄進 tasks.md，未對齊本檔 testplan.md REG-VL-001 早已定義的較窄範圍。Review Contract 的 AC-8 已同步修正措辭；此行同步改寫以符合實際測試行為。
- [x] 2.5 於 `.pre-commit-config.yaml` 註冊 hook，warn-only 段設 `verbose: true` 使警告可見。行為：`make ci` 執行該 hook 且警告不被靜默。驗證：`pre-commit run lint-rule-evidence --all-files` 顯示輸出。

## 3. `/pr-retro` Evidence Gate runbook

- [x] 3.1 於 `plugins/growth/skills/pr-retrospective/SKILL.md` 新增 Step 5.0 Evidence Gate，滿足需求「每個「加 rule/hook」action item 寫入前必須分級」與設計決策「Evidence Gate 置於既有三道 gate 之上游」。行為：Step 5 在 Q5→action 映射前先分級，未分級者不進 Promotion Gate；分級依「有無可接受證據形式」而非 `--source` 分數。驗證：字串錨點測試確認 Step 5.0 段存在且位於 Promotion Gate 敘述之前。
- [x] 3.2 於 Step 5.0 加入證據形式表，滿足需求「證據形式依 lesson 類型封閉列舉且無 catch-all」與設計決策「證據形式表以 lesson 類型封閉列舉（見 spec SBE Example）」「複用姊妹 change 的證據模式，不重新發明」。行為：表為封閉列舉、最後一列標「無可接受形式，恆 park」、無 `other`/`etc.` catch-all 列。驗證：錨點測試確認最後一列存在且全文無 catch-all 列字樣。
- [x] 3.3 於 Step 5.0 加入三種執行結果規則，滿足需求「Tier 1 probe 必有三種執行結果且無效不等於不成立」。行為：文件明載重現／未重現／無效三分法、「無效先修一次、修不好降 Tier 3 park、不記為未重現、不 drop」。驗證：錨點測試確認「無效」「repair once」「不記為未重現」三個錨點皆存在。
- [x] 3.4 於 Step 5.0 加入成本分層規則，滿足需求「驗證成本分層」與設計決策「成本分層：便宜當場跑、昂貴派 subagent 或降級」。行為：文件明載結構檢查零成本、秒級 probe 當場跑、昂貴 probe 派 subagent 或降 Tier 2，並指向 rule 11 既有的 probe 紀律段落（不再指向不存在的 `verification-recipes` 配方 9/10——PR #339 mob review 指出該文件在本 repo 從未存在，已改連結真實段落）。驗證：`scripts/tests/test_pr_retrospective_evidence_gate_anchors.py::test_cost_tiering_anchors` 對真實 SKILL.md 斷言「派 subagent」與「降級 Tier 2」措辭存在。
- [x] 3.5 於 Step 5 的 Q5→action 映射表加入證據前置條件。行為：`寫入規則文件` 與 `新增 hook` 兩列各標「須先通過 Evidence Gate（Tier 1/2 帶證據）」。驗證：錨點測試確認兩列含該前置條件字串。
- [x] 3.6 於 Step 5.0 加入 Tier 3 park 與升級規則，滿足需求「Tier 3 park 與 recurrence 升級契約」與設計決策「Tier 3 park 複用 typed-lessons，recurrence 升級但不繞過證據」。行為：Tier 3 park 到 typed-lessons（confidence ≤ 4、parked），recurrence ≥ 2 解除 park 重新受評但仍須通過 Tier 1/2 證據。驗證：錨點測試確認「recurrence ≥ 2」「解除 park」「仍須通過 Tier 1 或 Tier 2」錨點存在。

## 4. rule 11 作者面規範

- [x] 4.1 於 `.claude/rules/11-skill-authoring.md` 新增「Retro-authored rule/hook 的三層證據標準」段，滿足設計決策「規範內容寫入 rule 11 而非新增 always-loaded rule 檔」，複用既有 verify-before-authoring / Cross-doc Cite 脈絡。行為：規範只在編輯 `skills/**` 時載入，非全量。驗證：錨點測試確認該段存在於 rule 11。
- [x] 4.2 確認未新增任何 frontmatter 無 `paths:` key 的 rule 檔。行為：規範內容全數落在 rule 11（paths 觸發）。驗證：對照 1.2 baseline 的全量載入檔清單無新增檔。

## 5. 自我約束與收尾

- [x] 5.1 實作並執行「本 change 自我約束——always-loaded 面淨增為零」的機械檢查。行為：全量載入 rule 檔總行數相對 1.2 baseline 淨增為 0，且數字被印給操作者。驗證：檢查腳本輸出淨增行數 = 0。
- [x] 5.2 收尾閘門。行為：`make ci` 全綠且其後 `git diff --name-only` 為空（formatter hook 就地改檔）；`spectra validate` 與 `spectra analyze`（Critical + Warning 為 0）通過。驗證：貼出三者輸出摘要。

## 6. Code review remediation（PR #339 mob review，本 follow-up PR 補齊剩餘兩項）

> PR #339 mob review 提出多項 remediation，其中 rename-bypass / loose-regex / hunk-boundary
> 缺口、always-loaded growth 計算修正、evidence marker 收緊已隨 PR #339 一併合併
> （commit `bf9ebcc` / `805ca29` / `b4deb48`）。以下 6.1、6.2 是同一批 review 意見中，
> 完成但漏未推送、本 follow-up PR 補上的兩項。

- [x] 6.1 讓 Tier 3 park 成為可執行流程。行為：Evidence Gate 在 typed-lessons 寫入前分級；
  `mycelium lessons add --park` 以 `confidence ≤ 4` 原子地新增 parked lesson、同 key 再現時 bump
  `recurrence-<n>`，`recurrence ≥ 2` 解除 park 並回報 `reassess`；若重評後仍為 Tier 3，再次
  `--park` 只重套 parked、不重複 bump。parked lesson 預設不進 normal recall 與 tier promotion，
  且原標題／描述不被覆寫。驗證：`uv run pytest tasks/mycelium/tests/test_lesson_parking.py -q`
  （CLI/service/DB、recurrence、default exclusion）與 runbook anchor test。
- [x] 6.2 讓 evidence lint 在 CI 讀到正確的 PR / push diff range。行為：`.github/workflows/ci.yml`
  對 `pull_request` 事件以 `--base`/`--head` 指定 PR range、對 `push` 事件指定
  `before`/`sha`，並加 `fetch-depth: 0` 使 range diff 可解析（shallow checkout 預設只有單一
  commit，range diff 會失敗）。驗證：
  `uv run pytest scripts/tests/test_retro_evidence_gate_integration.py -q`。

  **6.2 修正（本 PR 的 CI 紅燈）：range mode 當時只做了呼叫端。** `scripts/lint_rule_evidence.py`
  原本只吃 positional diff 檔，`--base` 被當成檔名 ->
  `[FAIL] 無法讀取 diff 檔：[Errno 2] No such file or directory: '--base'`，exit 2，
  後面每個 CI step 全 skipped。當時的驗證測試只斷言「ci.yml 這個**字串檔**裡有 `--base`」，
  沒有任何測試用這組 flag 真的呼叫過腳本，所以本機全綠、CI 必紅——屬 CLAUDE.md
  「綠燈來自問錯問題的探測」家族的**介面兩端各自綠燈**軸。補上：
  - 實作端：`_parse_args()`（手寫，避免 argparse 的 `SystemExit` 逃出 `main()` 的
    回傳-exit-code 契約）+ `_range_diff()`（**三點** `base...head`；`pull_request.base.sha`
    是 base 分支 tip 不是 merge-base，兩點會把別人合進 base 的改動算進本 PR）。
    解不開的 commit -> exit 2 大聲失敗，不得回空 diff 讓 gate 空洞通過。
  - 測試端：`scripts/tests/test_lint_rule_evidence.py` 以真 git repo 跑 range，含正向對照
    （缺證據的新 rule 檔在 range mode 下必回 exit 1）與四條 exit-2 契約；
    `scripts/tests/test_retro_evidence_gate_integration.py` 加 drift guard。

## 7. Mob review remediation（PR #347，3 voices × R1+R2）

> 六個聲音（Claude 4 subagent / Codex / Gemini agy）R1 獨立 + R2 交叉辯論。R2 中兩家外部
> 聲音對 Claude 的 10 項發現全數 AGREE、無 DISAGREE。以下 13 項為 blocking set，全部已修
> 並逐項 mutation 驗證。

- [x] 7.1 **`mycelium-memory-tiers` delta 漏抄兩個已部署 scenario**（Consensus Critical）。
  MODIFIED 在 archive 時是整段取代，reviewer 以拋棄式 spectra 專案**實跑 archive** 證明
  `Archival export preserves full content` 與 `Archived lesson still queryable` 會被靜默刪除
  （exit 0、無警告，`spectra validate` 亦回報 valid）。已逐字抄回；另寫對照腳本驗證兩個
  MODIFIED requirement 都帶齊，並以「拿掉一個 scenario」的正向對照確認該檢查會 [FAIL]。
- [x] 7.2 **reassess → active 交接產生重複列**（Consensus Critical，lead 實證重現）。
  `lessons add` 是無條件 INSERT 新 UUID，而 reassess 已拿掉舊列的 `parked`，於是同 key 兩列；
  孤兒列被 `_dedup_latest_winner` 藏出 show/search，卻通過 promotion 三個過濾（實測
  `_fetch_non_archival` 回 2 列），最終 age 成 archival 匯出成重複 lesson。修法：runbook 在
  reassess 通過 Tier 1/2 後**先 add 後 retire**（複用既有 retire，`retired_at IS NULL` 已在
  promotion filter 內）。補 `LSN-PARK-ST-005`（釘住缺陷）與 `ST-006`（釘住修法）兩條。
  **與 Codex R2 建議的分歧已記錄在 SKILL.md**：它建議 transactional finalize-by-id（原子、更乾淨），
  本 PR 採最小修法，理由與升級條件都寫在該處。
- [x] 7.3 **三條 CI 斷言改成解析 YAML、綁到實際 job / step / argv**（Critical + 2 Important）。
  原本 `fetch-depth: 0` 是整檔字串比對（拆多 job 後失效）、`if:` 條件零斷言（改成
  `pull_request_target` 則 step 永久 skip 而測試全綠）、drift guard 只抽 flag 名稱（改等號形式
  `--base=<sha>` 則 guard 全綠但 runtime exit 2）。三個曾存活的突變現已全部 KILLED 且各只殺一條。
- [x] 7.4 **AC-4 三點語意鎖補上真正能分辨的 fixture**（Consensus Important，三家獨立提出）。
  舊 fixture（base 新增缺證據檔）在兩點下呈現為刪除，`_is_newly_protected` 對 `/dev/null`
  必不匹配，兩種語意輸出相同。新增「base 刪除一個 fork 前就存在的缺證據 rule 檔」：三點 exit 0、
  兩點 exit 1。依 Codex R2 建議**增加而非取代**舊 fixture。`...` → 兩點的突變現已 KILLED。
- [x] 7.5 **空字串 `--base`/`--head` 的 fail-open**（Consensus Important）。`""` 不是 `None`，
  `"...head"` 是合法 range（等同 `HEAD...head`）→ git exit 0 回空 diff → gate 印 `[OK]`。
  `_parse_args` 加空值拒絕 + `LSN` 對應測試；突變已 KILLED。三家皆誠實標註目前 wiring 下
  兩個 SHA 必為非空，屬殘餘風險而非活 bug。
- [x] 7.6 **parked 排除面四個入口只測了一個**（Consensus Important）。補 `search_lessons_typed`
  預設排除 / `include_parked`、CLI `lessons show|search --include-parked` 各一條、以及 demotion
  側排除。四個突變逐一驗證，且**精準命中**：突變 search 那處只殺 search 的兩條測試
  （第一次用字串 replace 誤中 show 那處，屬「把 A 機制的突變配到 B 的測試」，已重做）。
- [x] 7.7 **`park_lesson` 拒絕覆寫未 parked lesson 的守衛零覆蓋**（Consensus Important）。
  拿掉守衛會把 confidence 9 的 active lesson 夾成 4 並掛 parked——靜默的可見性損失。
  補 `LSN-PARK-DT-005` 並斷言 rollback 有效；突變已 KILLED。
- [x] 7.8 **`nightly_agent` 直接 SQL 讀取仍撿到 parked**（Important，Gemini R2 升為 Critical）。
  被 park 的教訓當晚會從側門重回 rule 生成管線。加 `_excluded_lesson_ids`（parked + retired，
  `tags`/`retired_at` 各自獨立做欄位存在判斷、SQL 維持靜態字串、讀取路徑維持唯讀），補三條測試。
  retired 洩漏是本 PR 之前就存在的漏洞，一併補。
- [x] 7.9 **`retro-evidence-gate` spec 與 SKILL.md / code / design.md 互相矛盾**（Important）。
  「狀態 parked」改為 `tags 含 "parked"`；補 re-park 不重複 bump、拒絕覆寫、confidence 拒絕
  三個 scenario 與 `status=` 輸出契約。
- [x] 7.10 **`test_lesson_parking.py` 違反 rule 09**（Important）。重寫為 `class TestXxx` +
  `LSN-PARK-<DT|ST|VL|EG|CV>-NNN` 結構化 ID，與 `test_lessons_retire.py` 的分層一致。
- [x] 7.11 **confidence 契約三方矛盾**（Codex R2 升為 Important）。統一為「> 4 直接拒絕，
  不是 clamp」，同步 `commands/lessons.md`、rule 11 與 spec。
- [x] 7.12 NIT 批次：rule 11 的 push range 兩點寫法、`db.get_lessons` 等不存在的方法名、
  spec 標題仍稱 commit-time、docstring bullet 只講 pre-commit、`--all-files`「毫無作用」過度陳述、
  恆真斷言 `confidence <= 4`、初次 park 的 tag 清洗硬寫 `recurrence-1`（改前綴比對 + `EG-001`）。
- [ ] 7.13 **Deferred（人類裁決）**：Codex R2 新開的 Critical「既有 always-loaded 文件仍可經
  warn-only 路徑新增缺證據 section」與 contract 的 Non-goals 第三條直接衝突。@howie 於
  2026-07-26 裁定**維持 Non-goal、本項不 blocking**，理由是升級為 error 會 retro-block 整個
  歷史 corpus，正是當初列為 Non-goal 的原因。留在 Follow-ups。
