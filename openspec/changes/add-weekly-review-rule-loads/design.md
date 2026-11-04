# Design：add-weekly-review-rule-loads

## D1 — 資料來源：transcript 的兩種 attachment

實測（yibi-mvp，Claude Code 2.1.316／2.1.317，2026-11-03）：

| attachment `type` | 何時出現 | 帶的路徑欄位 | 載入的內容 |
|---|---|---|---|
| `instructions` | session 開始（`reason: session_start` 或缺漏），設定變更時重載（`reason: account_change`，另帶 `removed`） | `files[].path`，`files[].type` 為 `Project` 或 `User` | 根目錄 `CLAUDE.md`／`AGENTS.md`、沒有 `paths:` 或 `paths: "**"` 的 rule、`~/.claude/CLAUDE.md`（`User`） |
| `nested_memory` | 工具第一次碰到符合 `paths:` 的檔案時 | `path` | path-scoped rule、子目錄 `CLAUDE.md` |

確認方式：在最近 60 份 transcript 中，每次必載的 `14-retirement-residual-sweep.md` 只出現在 `instructions`（26 次），
從未出現在 `nested_memory`。

2026-11-04 另掃本機 yibi-mvp 的 317 份 transcript（48,380 個 attachment 事件、235 個 `instructions`），這是一次性
量測，掃描腳本未進 repo：沒有任何 attachment 不是物件，也沒有任何 `instructions` 缺 `files` 或 `files` 不是清單。
所以 D4 把這些形狀判為來源不完整，不會在現行資料上誤報。

## D2 — 計數單位與路徑正規化

- 單位是 sessionId，每個 rule 對應一個 session 集合。同一 session 重載、或同一事件在主 checkout 與 worktree 的
  transcript 各出現一次，都不會讓 **session 數**重複計數，所以 rule 與指令檔的計數不需要依 uuid 去重。
  依事件去重的只有 D6 的事件計數。
- 路徑：去掉 `<main_repo>/` 前綴後，只收 `**/.claude/rules/**/*.md`（rule，含 rules 子目錄與子專案的
  `mobile/.claude/rules/`）與 `**/CLAUDE.md`、`**/AGENTS.md`（指令檔，含根目錄）。不在 repo 底下的路徑不計。
  子專案的 rule 以自己的路徑計數；`collect_rules` 只列根目錄 rules 的直接子項，所以報告把它標成「不在
  collect_rules 清單：可能已刪除、位於 rules 子目錄，或屬於子專案」。
- `<main_repo>/.claude/worktrees/` 底下的路徑要去掉 worktree 名稱，而名稱可以含 `/`（例如 `feat/x`）。名稱只取自
  下列兩個來源的聯集（`collect_worktree_roots`，由 `cmd_collect` 算好再傳進 `collect_rule_loads`）：
  - `git -C <main_repo> worktree list --porcelain` 中位於 `<main>/.claude/worktrees/` 底下的 worktree。git 回傳的
    巢狀名稱（`feat/x`）照實保留
  - `<main>/.claude/worktrees/` 的**第一層**子目錄中含 `.git` 項目（linked worktree 的 `.git` 是檔案）的，以 `.`
    開頭的名稱略過。不往下走：殘留目錄內的巢狀 repo 或子模組不是 worktree 根目錄（PR #628 review W-4）。
    git 已不認得、目錄卻還在的 worktree 靠這條取得
  - 正規化時去掉最長的已知名稱，所以 `feat` 與 `feat/x` 並存時 `feat/x/CLAUDE.md` 對到 `CLAUDE.md`
  - `.claude/worktrees/` 不存在是常態，不算錯誤。git 失敗、目錄列不出來、或子項的狀態讀不到時名稱可能不齊，
    來源標為不完整。不先用 `Path.is_dir()` 判斷目錄是否存在：它把權限錯誤吞成 False
- 對不上任何已知名稱的 worktree 路徑（多半是期間已刪除的 worktree）**不推論**：不計入任何 rule、指令檔，
  不使該 session 成為「有載入專案指令」，也不算 `nested_unresolved_events`，只計入 `unresolved_worktree_paths`，
  報告表頭列出。這不使來源不完整。
- **真實限制**（2026-11-04 量測，見 D3）：yibi-mvp 的 worktree 多半用完就刪，所以這個限制很大。該觀察期有
  324 個對不上的路徑，逐一歸類來自 16 個已刪除的 worktree（一次性診斷腳本，未進 repo）；30 個 `cli` session 中
  只有 24 個進分母，`sdk-cli` 的 2 個都不進分母，因為它們的指令檔全在已刪除的 worktree 裡。次數與分母因此都偏低。
  這是 owner 接受的取捨（PR #628 Review Contract 的 Accepted Residual Risk 3），理由見 D7。
- `instructions.files[].type == "User"` 不計。這不能只靠路徑判斷：repo 就是家目錄時（dotfiles repo），
  `~/.claude/CLAUDE.md` 也在 repo 底下。
- 觀察期的單位是 session，不是事件：至少有一筆事件的 timestamp 在 `[since, now]` 內的 session 才算觀察期內的
  session，這種 session 的所有載入紀錄都算，不論 attachment 本身的時間。觀察期開始前載入的指令在期內仍在
  context 裡。被否決的作法：以事件時間過濾。跨越 `since` 的 session 會讓期內的 `nested_memory` 進分子，
  期前的 `instructions` 卻被濾掉而不進分母，PR #628 review 以探針重現佔比 150% 與 200%。`now` 是上界：
  以 `--now` 回補過去某週時，之後才開始的 session 不算（R2-1）。

## D3 — 分母

實測（yibi-mvp，2026-11-04 量測，觀察期 14 天：2026-10-21T08:46Z 到 2026-11-04T08:46Z）。量測對象是
`worktree-trim-always-loaded-rules` 分支（HEAD `a4bb2bafa`）的 checkout，不是 yibi-mvp 的 main；transcript 取主 repo
與其 worktree。量測時的程式是本 change 縮小宣稱後的版本（D7）：

```bash
python3 plugins/harness/skills/harness-weekly-review/scripts/harness_review.py collect \
  --repo /Users/howie/Workspace/github/heyu/yibi-mvp/.claude/worktrees/trim-always-loaded-rules \
  --days 14 --no-ci --out snap-fix4.json
```

| entrypoint | session 數 | 有載入專案指令 |
|---|---:|---:|
| `cli` | 30 | 24 |
| `sdk-cli` | 2 | 0 |
| `sdk-py` | 97 | 0 |
| `(unknown)` | 1 | 0 |
| 合計 | 130 | 24 |

同一份快照中：

- 來源完整，沒有 warning
- 7 條每次必載的 rule 皆為 24 個 session，`always_missing` 為空，`excluded_sessions` 為 0
- 原始計數：`instructions_events` 257、`nested_memory_events` 106、`nested_unresolved_events` 0、
  `unresolved_worktree_paths` 324（見 D2 的限制）
- 根目錄 `CLAUDE.md` 與 `AGENTS.md` 皆為 24 個 session，`docs/CLAUDE.md` 為 6、`backend/CLAUDE.md` 為 4
- 該分支 checkout 有 37 個 rule、其中 30 個 path-scoped；yibi-mvp 的 `origin/main` 是 35 個、28 個 path-scoped。
  差的兩個是 `15-retirement-sweep-incident-log.md` 與 `52-verification-incident-log.md`，2026-11-03 才在該分支以
  commit `247f5ae11` 建立
- path-scoped 0 次的有 15 個。其中 `15` 是量測前一天才建立，它的 0 次不是兩週的觀察；同一天建立的 `52` 載入 1 次。
  其餘 14 個的 0 次要打折看：分母只剩 24 個 session，已刪除 worktree 內的載入全部不計（D2 的限制）
- `42-worktree-safety.md` 在 24 個 session 中載入 1 次

所以佔比的分母是「有載入專案指令的 session 數」，報告另依 entrypoint 列出兩個數字。「有載入專案指令」的
判定是：`instructions` 列出至少一個本 repo 內、非使用者層、且路徑解析得出來的檔案。只列出使用者層檔案、只列出
repo 外檔案、或只列出已刪除 worktree 內檔案的 session 不進分母，它的 path-scoped 載入也不進分子；前兩種有載入
紀錄時記進 `excluded_sessions`，否則佔比可超過 100%。`sdk-py` session 為什麼不載入專案指令不在本 change 範圍；
報告讓它看得見即可。上表是單一 checkout 的一次量測，不代表所有 `sdk-py` session 都不載入專案指令
（PR #628 完整 diff 重審的 NIT：本機另一份統計中 `sdk-py` 的 1786 個 transcript 有 1569 個有 instructions）。

## D4 — 來源完整性

沿用 `make_source`。**只有**下列情況使本來源不完整：

- 任一檔案讀取失敗、任一目錄列不出來
- 任一行不是合法 JSON，或是合法 JSON 但不是物件
- 觀察期內 session 的事件 attachment 形狀不符：`type` 為 `attachment` 的事件 `attachment` 不是物件（缺漏、
  字串化的 JSON、清單）；`nested_memory.path` 或 `instructions.files[].path` 不是字串；`files` 缺漏或不是清單
  （含 `{}`、`""` 這類 falsy 值）；`files` 含非物件項目
- 找不到 transcript
- transcript 存在，但觀察期內有時間戳的事件少於 `TRANSCRIPT_MIN_EVENTS`（3）筆。門檻與 `evaluation_scope`
  對 transcript 類建議的要求一致；timestamp 欄位改名時每一行都會被當成沒有時間戳，靠這條抓到
- worktree 名稱列舉失敗（D2）
- `rules` 來源不完整

形狀錯誤依 session 暫存，掃完所有檔案、確定哪些 session 在觀察期內之後才計入。觀察期外的 session 不檢查：否則
一筆舊的壞事件會讓該節持續量不到，直到檔案超出保留期（PR #628 review F-1）。讀檔失敗與壞行找不到所屬 session
（截斷的行沒有可讀的 `sessionId`），可能屬於觀察期內的 session，所以一律計入。

`always_missing` 只作資訊列出，不影響完整性。不以載入次數、`entrypoint` 或「沒看到某種事件」推論格式漂移，
理由見 D7。

回傳的 warnings 就是 `source.errors` 的全部（同一份清單、同順序）。讀檔失敗、壞行、目錄列舉錯誤與「找不到
transcript」的文字與 `collect_transcript_blocks` 共用同一個標籤與函式（`TRANSCRIPT_LABEL`、
`transcript_bad_lines_msg`、`no_transcript_msg`），`cmd_collect` 只去掉與 `collect_transcript_blocks` 這次回傳的
warning 逐位元相同的那一筆。不依類別略過：兩次讀檔之間有一行被寫到一半時，兩邊的壞行數不同、文字不同，
兩筆都留下，`collect` 回傳 3（PR #628 review F-5 的 p3_append_race，HWR-ST-031）。被否決的作法：第 2 輪的
「讀檔失敗、壞行、目錄列舉錯誤只記進本來源、不回傳」，因為它假設兩個 collector 讀到同一份檔案，上述落差下
rule_loads 不完整、warnings 卻是空的。

## D5 — 報告

報告最後新增「rule 載入次數（本期，以 session 計）」：

- 來源完整時，表頭固定列出：session 總數、有載入專案指令的 session 數、依 entrypoint 的兩個數字、D6 的原始計數、
  每次必載但本期 0 次的 rule（沒有時寫「無」），以及固定的一句「格式漂移不保證偵測：表頭的原始計數請與前一週比對」
- 有 session 而 `instructions_events` 為 0 時，加一行以 `**注意**` 開頭的提示：沒有看到任何 instructions 事件，
  下表無法顯示 rule 載入。只陳述觀察到什麼與表格因此看不到什麼，不下「格式已改變」的結論；這一行不使來源不完整
- rule 表：每次必載或前 3 個 `paths:` pattern、session 數、佔比，依 session 數由多到少排列。硬碟上存在但 0 次的
  rule 都列出；有載入紀錄但不在 `collect_rules` 清單的 rule 標「不在 collect_rules 清單：可能已刪除、位於 rules
  子目錄，或屬於子專案」（PR #628 review D-2）。沒有任何 session 載入專案指令時佔比顯示 `-`
- 指令檔表（`CLAUDE.md`／`AGENTS.md`，含根目錄）：依 session 數排序
- 來源不完整：只寫「量不到」，並把 `source.errors` 逐條列在同一節，不印原始計數與表，也不指向其他段落。第 2 輪
  的「原因見上方『量測不完整』」被否決：該段落的內容來自快照 warnings，在 F-5 的落差下它不存在
- 快照沒有 `rule_loads`（本 change 之前的快照）：寫明快照產生於此功能之前、沒有載入紀錄
- 快照有 `rule_loads` 但缺某個原始計數欄位時，該計數顯示「未記錄」，不當成 0，也不觸發「注意」

## D6 — 原始計數

- `instructions_events`：觀察期內**所有** session 的 instructions attachment 數，包括只列出使用者層或 repo 外檔案
  的。它與下兩個事件計數的範圍不同（後兩者只計有載入專案指令的 session），因為它唯一的用途是判斷「注意」一行：
  一筆 instructions 都沒看到
- `nested_memory_events`：解析成本 repo rule 或指令檔的 nested_memory 事件數，只計有載入專案指令的 session
- `nested_unresolved_events`：同一批 session 中，路徑是字串、卻解析不成本 repo 檔案的事件數（相對路徑、`file://`
  URI、repo 外路徑）；對不上已知 worktree 的路徑不算在這裡，只算 `unresolved_worktree_paths`
- 三個事件計數都依事件 id 去重：同一事件在主 checkout 與 worktree 的 transcript 各出現一次時只算一筆。沒有 uuid
  的事件以 sessionId、檔案與行號組成替代 id。先前的替代 id 只用檔案與序號，同一檔案裡兩個 session 的事件會
  撞號（PR #628 review CR-4，HWR-DT-109）
- `unresolved_worktree_paths`、`excluded_sessions`、`always_missing` 也列在表頭
- 這些計數只給人比對，collector 不拿它們判斷來源是否完整（D7）

## D7 — 縮小宣稱：不推論格式漂移與已刪除 worktree 的根目錄

2026-11-04 owner 在 PR #628 的完整 diff 重審（第 2 輪之後重新開始的 R1，`.pr-review/final.md`）後裁決：停止推論，只保留確定的條件，原始計數交給人判讀。

**為什麼不再修補**：

- worktree 正規化同一形狀的錯誤出現第 5 次（第 1 輪 I-8 → 第 2 輪 R2-2 → 完整 diff 重審 W-1..W-4，見
  `.pr-review/final.md` 的彙整）：每次修在被指出的那一層，相鄰形狀又重演。
- 格式漂移偵測同一形狀的錯誤出現第 4 次（第 1 輪 I-7 → 第 2 輪 R2-5 → 完整 diff 重審 F-2..F-4）。
- reviewer 對同一個判斷的要求互相衝突：F-2 要求安靜的一週（沒人碰 scoped 路徑）不可報成量不到（少報），F-3 與
  F-4 要求 claude-desktop／sdk-cli 為主的一週、或 nested 計數被子目錄 CLAUDE.md 撐起來時要報量不到（多報）。
  「格式真的壞了」與「這週剛好沒發生」在單週資料上無法區分，依 yibi-mvp rule 41「假陽性率是 gate 的一等約束」，
  沒有可用的機械判準。

**被否決的作法**（依時間順序，皆已從程式移除）：

1. worktree 名稱取 `.claude/worktrees/` 之後的第一段。第 1 輪以 `feat/x` 重現它丟失 rule 載入，並捏造
   `x/CLAUDE.md`（I-8）。
2. 以路徑中**最後一個** `/.claude/rules/` 為錨點收集 worktree 名稱。第 2 輪以 probe_a 重現：worktree 內
   `mobile/.claude/rules/m.md` 被併成根目錄的 `.claude/rules/m.md`，並造出假的 worktree 名稱 `wt/mobile`（R2-2）。
3. 權威名稱對不上時，rule 路徑以**第一個** `/.claude/rules/` 推回相對路徑。已刪除 worktree 內子專案的 rule 會被
   推成根目錄的 rule（第 2 輪自己記下的已知限制）。
4. 已刪除的 worktree 以 transcript 目錄名稱 `<slug>--claude-worktrees-<X>` 推回根目錄（第 2 輪修正後追加，tasks 6.11）。
   完整 diff 重審重現：推回的名稱也套用到主 repo 目錄的 transcript（W-1）；在 worktree 子目錄啟動的 session 把 cwd
   當根目錄（W-2）；外層 worktree 還在、內層已刪除時造出 `x/CLAUDE.md`（W-3）。採用時該快照
   （snap-fix3，觀察期結束於 2026-11-04T01:57Z）的對不上路徑由 33 降為 10，根目錄 `CLAUDE.md` 由 27/30 升為 30/30；
   兩個數字來自觀察期不同的兩份快照，不能直接相減。對那 10 個路徑的逐筆查證（9 個是 session 讀到另一個已刪除
   worktree 的檔案，1 個讀自主 repo 目錄）是對 snap-fix3 的一次性量測。
5. `collect_worktree_roots` 遞迴走訪 `.claude/worktrees/`，殘留目錄內的巢狀 `.git` 被當成 worktree 根目錄（W-4）。
6. 格式對照：觀察期內有 `entrypoint` 等於 `cli` 的 session，卻沒有任何 `instructions` 事件、或 `instructions` 列出的
   檔案沒有任何一個是 rule，就判為不完整。其前身「任一條必載 rule 為 0 次」（I-2）與「checkout 的必載 rule 全部
   0 次」（R2-3）先後被否決。完整 diff 重審：只在有 `cli` session 時才跑，claude-desktop、sdk-cli 為主的一週印出必載 rule
   全 0% 的表（F-3）。
7. nested_memory 門檻：有載入專案指令的 session 至少 `RULE_LOAD_MIN_SESSIONS`（3）個、`nested_memory_events`
   卻是 0 時，path-scoped 次數改寫「量不到」。完整 diff 重審：安靜的一週被報成格式改變（F-2）；子目錄 `CLAUDE.md` 讓計數
   大於 0 時，path-scoped rule 的事件格式改了也不觸發（F-4）。

**取捨**：拿掉推論後，格式漂移與已刪除 worktree 的載入都不會被自動處理。前者靠表頭的原始計數與「注意」一行
讓人看見；後者少算並揭露數量，不捏造路徑（D2 的限制，D3 的實測 324 個路徑）。若日後要自動偵測，另開 change，
以多週快照的原始計數趨勢判斷，而不是單週的推論（PR #628 Review Contract 的 Follow-ups）。

## 驗證

- 單元與端對端測試：HWR-DT-080..097、HWR-DT-099..102、HWR-DT-107..110、HWR-ST-026..032（見測試檔開頭的覆蓋對映）。
  HWR-DT-098 與 HWR-DT-103..106 已隨 D7 移除
- mutation，依時間順序。第 1 到 5 點的程式有一部分已隨 D7 移除，保留紀錄供追溯：
  1. 初版實作（commit `e0ef59a`）完成後，對 9 個單點各做一次突變：來源恆完整、使用者層計入、拿掉 cli 對照、對照改以
     任何 session 為前提、worktree 不正規化、報告忽略來源、分母改用全部 session、忽略觀察期、丟掉 nested_memory。
     其中 2 個先存活，因此刪掉無作用的 uuid 去重，並把使用者層指令檔的測試改放在 repo 路徑底下；修改後 9 個都被
     抓到。這一輪沒有留存輸出，只有這段文字紀錄。
  2. PR #628 review 第 1 輪，pr-test-analyzer 另跑 21 個單點突變，16 個存活。其中 4 個列為必修（finding I-9）：
     M1 佔比不防除以零、M13 `cmd_collect` 傳 `repo` 而非 `main_repo`、M2 `MEMORY_REL` 拿掉 `AGENTS`、M6 不計非物件的行。
  3. PR #628 第 1 輪修正，以腳本對 8 個單點各做一次突變（備份在記憶體、確認 anchor 只出現一次、`compile()` 後刪
     `__pycache__` 再跑 `-k RuleLoads`、還原後確認逐位元相同），8 個都被抓到：(a) 佔比拿掉 `if total` 防護、
     (b) `cmd_collect` 傳 `repo`、(c) `MEMORY_REL` 拿掉 `AGENTS`、(d) 非物件的行不計入壞行、(e) 拿掉觀察期內最少
     事件數、(f) 任一條必載 rule 0 次就判為格式改變、(g) worktree 正規化退回第一段、(h) 沒有載入專案指令的 session
     也計入分子。(f) 與 (g) 的程式後來已移除。
  4. PR #628 第 2 輪修正，同一套腳本對 9 個單點各做一次突變，9 個都被抓到：(a) `resolve_repo_path` 忽略注入的名稱、
     (b) `collect_worktree_roots` 吞掉 git 失敗、(c) `nested_memory_events` 也數無法解析的事件、(d) 拿掉 `ts <= now`、
     (e) 格式對照比對 checkout 的必載 rule 名稱、(f) `files` 為 falsy 時不計形狀不符、(g) 分母改用原始 instructions
     路徑、(h) 「沒有 instructions 事件」改用 `with_instr` 判斷、(i) `RULE_LOAD_MIN_SESSIONS` 改成 `>= 1`。
     (e)、(h)、(i) 的程式後來已移除。
  5. 第 2 輪修正後追加的目錄名稱推回，3 個單點：停用推回被抓到、改取最長前綴存活（等價突變）、主 repo 目錄也套用被抓到。
     整段程式後來已移除（D7 第 4 點）。
  6. 完整 diff 重審後縮小宣稱，同一套腳本（`mutate_r4.py`，一次性、未進 repo）對 9 個單點各做一次突變，9 個都被抓到，
     失敗都是斷言失敗：
     - (a) `collect_worktree_roots` 恢復遞迴走訪子目錄 → HWR-DT-102
     - (b) 吞掉 `.claude/worktrees/` 的列目錄錯誤 → HWR-DT-107、HWR-ST-032
     - (c) 也計入觀察期外 session 的形狀錯誤 → HWR-DT-108
     - (d) 拿掉「注意」一行 → HWR-DT-081、HWR-DT-110
     - (e) 不完整時不列出原因 → HWR-DT-083
     - (f) `cmd_collect` 依類別略過 `rule 載入：` 開頭的 warning → HWR-ST-032
     - (f2) `collect_rule_loads` 依類別略過 warning → HWR-DT-082、088、090、093、094、102、108、HWR-ST-032
     - (g) 對不上的 worktree 路徑以第一段推回並計入 → HWR-DT-101
     - (h) 拿掉觀察期的 `now` 上界 → HWR-DT-093
- 真實資料：對 yibi-mvp 兩週 transcript 執行 `collect`（指令與時間見 D3），來源完整、沒有 warning；7 條每次必載的
  rule 皆為 24/24，根目錄 `CLAUDE.md` 為 24/24，`unresolved_worktree_paths` 為 324
