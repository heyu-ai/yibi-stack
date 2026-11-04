# Design：add-weekly-review-rule-loads

## D1 — 資料來源：transcript 的兩種 attachment

實測（yibi-mvp，Claude Code 2.1.316／2.1.317，2026-11-03）：

| attachment `type` | 何時出現 | 帶的路徑欄位 | 載入的內容 |
|---|---|---|---|
| `instructions` | session 開始（`reason: session_start` 或缺漏），設定變更時重載（`reason: account_change`，另帶 `removed`） | `files[].path`，`files[].type` 為 `Project` 或 `User` | 根目錄 `CLAUDE.md`／`AGENTS.md`、沒有 `paths:` 或 `paths: "**"` 的 rule、`~/.claude/CLAUDE.md`（`User`） |
| `nested_memory` | 工具第一次碰到符合 `paths:` 的檔案時 | `path` | path-scoped rule、子目錄 `CLAUDE.md` |

確認方式：在最近 60 份 transcript 中，每次必載的 `14-retirement-residual-sweep.md` 只出現在 `instructions`（26 次），
從未出現在 `nested_memory`。

2026-11-04 另掃本機 yibi-mvp 的 317 份 transcript（48,380 個 attachment 事件、235 個 `instructions`）：沒有任何
attachment 不是物件，也沒有任何 `instructions` 缺 `files` 或 `files` 不是清單。所以 D4 把這些形狀全部判為格式改變，
不會在現行資料上誤報（掃描腳本為一次性，未進 repo）。

## D2 — 計數單位與路徑正規化

- 單位是 sessionId，每個 rule 對應一個 session 集合。同一 session 重載、或同一事件在主 checkout 與 worktree 的
  transcript 各出現一次，都不會讓 **session 數**重複計數，所以 rule 與指令檔的計數不需要依 uuid 去重。
  唯一依 uuid 去重的是 `nested_memory_events`（見 D5），因為它數的是事件，不是 session。
- 路徑：去掉 `<main_repo>/` 前綴後，只收 `**/.claude/rules/**/*.md`（rule，含 rules 子目錄與子專案的
  `mobile/.claude/rules/`）與 `**/CLAUDE.md`、`**/AGENTS.md`（指令檔，含根目錄）。不在 repo 底下的路徑不計。
  子專案的 rule 以自己的路徑計數；`collect_rules` 只列根目錄 rules 的直接子項，所以報告把它標成「不在
  collect_rules 清單」。
- `<main_repo>/.claude/worktrees/` 底下的路徑要去掉 worktree 名稱，而名稱可以含 `/`（例如 `feat/x`）。名稱取自
  **權威來源**，不從 transcript 路徑推論（`collect_worktree_roots`，由 `cmd_collect` 算好再傳進
  `collect_rule_loads`）：
  - `git -C <main_repo> worktree list --porcelain` 中位於 `<main>/.claude/worktrees/` 底下的 worktree
  - 走訪 `<main>/.claude/worktrees/`，含 `.git` 項目（linked worktree 的 `.git` 是檔案）的目錄即為 worktree 根目錄，
    不再往下走。git 已不認得、目錄卻還在的 worktree 靠這條取得
  - 兩者取聯集，正規化時去掉最長的已知名稱，所以 `feat` 與 `feat/x` 並存時 `feat/x/CLAUDE.md` 對到 `CLAUDE.md`
  - `.claude/worktrees/` 不存在是常態，不算錯誤。git 失敗或目錄列不出來時名稱可能不齊，來源標為不完整
- 對不上任何已知名稱的 worktree 路徑（多半是期間已刪除的 worktree）：rule 路徑以**第一個** `/.claude/rules/` 推回
  相對路徑照常計入；其他檔案不猜，計入 `unresolved_worktree_paths`，報告表頭列出。這不使來源不完整。
- **真實限制**（2026-11-04 量測，見 D3）：已刪除 worktree 的根目錄與子目錄 `CLAUDE.md`／`AGENTS.md` 因此不計。
  該觀察期有 33 個這樣的路徑；根目錄 `CLAUDE.md` 與 `AGENTS.md` 各為 27/30 個 session。前一份快照（2026-11-03、
  以舊推論量測、觀察期早約 9 小時）兩者皆為 30，`backend/CLAUDE.md` 為 18，本次為 12；兩份的觀察期不同，差值只供
  量級參考。本機全部 transcript 中無法解析的路徑來自 9 個已刪除的 worktree，名稱都不含 `/`，所以被否決的舊推論
  （名稱是第一段）在這批資料上會算對；但它對名稱含 `/` 的 worktree 會捏造 `x/CLAUDE.md`。本 change 選擇少算並
  揭露數量，不選擇可能捏造。另一個限制：已刪除 worktree
  內子專案的 rule（`mobile/.claude/rules/x.md`）會被推成根目錄的 `.claude/rules/x.md`，因為 worktree 名稱與
  子專案目錄在路徑上無法區分；yibi-mvp 目前沒有子專案自帶 `.claude/rules/`。
- 被否決的作法，依時間順序：
  1. 只去掉 `.claude/worktrees/` 之後的第一段。PR #628 review 第 1 輪以 `feat/x` 重現它丟失 rule 載入，並捏造
     `x/CLAUDE.md`（I-8）。
  2. 以路徑中**最後一個** `/.claude/rules/` 為錨點，從 rule 路徑收集 worktree 名稱。PR #628 review 第 2 輪以
     probe_a 重現：worktree 內 `mobile/.claude/rules/m.md` 被併成根目錄的 `.claude/rules/m.md`，並造出假的
     worktree 名稱 `wt/mobile`，使 `mobile/CLAUDE.md` 變成 `CLAUDE.md`（R2-2）。兩輪都是「修在被指出的那一層、
     上一層重演」，所以 owner 裁決改用權威來源，不再修補推論。
- `instructions.files[].type == "User"` 不計。這不能只靠路徑判斷：repo 就是家目錄時（dotfiles repo），
  `~/.claude/CLAUDE.md` 也在 repo 底下。
- 觀察期的單位是 session，不是事件：至少有一筆事件的 timestamp 在 `[since, now]` 內的 session 才算觀察期內的
  session，這種 session 的所有載入紀錄都算，不論 attachment 本身的時間。觀察期開始前載入的指令在期內仍在
  context 裡。被否決的作法：以事件時間過濾。跨越 `since` 的 session 會讓期內的 `nested_memory` 進分子，
  期前的 `instructions` 卻被濾掉而不進分母，PR #628 review 以探針重現佔比 150% 與 200%。`now` 是上界：
  以 `--now` 回補過去某週時，之後才開始的 session 不算（R2-1）。

## D3 — 分母

實測（yibi-mvp，2026-11-04 量測，觀察期 14 天：2026-10-21T00:48Z 到 2026-11-04T00:48Z）。量測對象是
`worktree-trim-always-loaded-rules` 分支（HEAD `a4bb2bafa`）的 checkout，不是 yibi-mvp 的 main；transcript 取主 repo
與其 worktree：

```bash
python3 plugins/harness/skills/harness-weekly-review/scripts/harness_review.py collect \
  --repo /Users/howie/Workspace/github/heyu/yibi-mvp/.claude/worktrees/trim-always-loaded-rules \
  --days 14 --no-ci --out snap-fix2.json
```

| entrypoint | session 數 | 有載入專案指令 | 看得到 rule 14 |
|---|---:|---:|---:|
| `cli` | 28 | 28 | 28 |
| `sdk-cli` | 2 | 2 | 2 |
| `sdk-py` | 96 | 0 | 0 |
| `(unknown)` | 1 | 0 | 0 |
| 合計 | 127 | 30 | 30 |

「看得到 rule 14」欄是推導值：快照記錄 rule 14 共 30 個 session，而 rule 只計入有載入專案指令的 session
（共 30 個），所以每個有載入專案指令的 session 都有它。同一份快照中：

- 7 條每次必載的 rule 皆為 30 個 session，`always_missing` 為空，`excluded_sessions` 為 0
- `nested_memory_events` 為 1043、`nested_unresolved_events` 為 133、`unresolved_worktree_paths` 為 33（見 D2 的限制）
- 該分支 checkout 有 37 個 rule、其中 30 個 path-scoped；yibi-mvp 的 `origin/main` 是 35 個、28 個 path-scoped。
  差的兩個是 `15-retirement-sweep-incident-log.md` 與 `52-verification-incident-log.md`，2026-11-03 才在該分支以
  commit `247f5ae11` 建立
- path-scoped 0 次的有 5 個：`10`、`24`、`33`、`50-mobile-openspec-boundary` 存在滿兩週；`15` 是量測前一天才建立，
  它的 0 次不是兩週的觀察。同一天建立的 `52` 載入 1 次
- `42-worktree-safety.md` 在 30 個 session 中載入 1 次

所以佔比的分母是「有載入專案指令的 session 數」，報告另依 entrypoint 列出兩個數字。「有載入專案指令」的
判定是：`instructions` 列出至少一個本 repo 內、非使用者層的檔案。只列出使用者層檔案、或只列出 repo 外檔案的
session 不進分母，它的 path-scoped 載入也不進分子，只記進 `excluded_sessions`，否則佔比可超過 100%。`sdk-py`
session 為什麼不載入專案指令不在本 change 範圍；報告讓它看得見即可。

## D4 — 來源完整性與格式對照

沿用 `make_source`。下列情況都使本來源不完整：

- 任一檔案讀取失敗、任一目錄列不出來
- 任一行不是合法 JSON，或是合法 JSON 但不是物件
- attachment 形狀不符：`type` 為 `attachment` 的事件 `attachment` 不是物件（缺漏、字串化的 JSON、清單）；
  `nested_memory.path` 或 `instructions.files[].path` 不是字串；`files` 缺漏或不是清單（含 `{}`、`""` 這類 falsy 值）；
  `files` 含非物件項目
- 找不到 transcript
- transcript 存在，但觀察期內有時間戳的事件少於 `TRANSCRIPT_MIN_EVENTS`（3）筆。門檻與 `evaluation_scope`
  對 transcript 類建議的要求一致；timestamp 欄位改名時每一行都會被當成沒有時間戳，靠這條抓到
- worktree 名稱列舉失敗（D2）
- `rules` 來源不完整

另加格式對照，前提是觀察期內至少有一個 `entrypoint` 等於 `cli` 的 session（精確比對，`sdk-cli` 不算）：

- 沒有任何 `instructions` 事件 → 不完整。只列出使用者層檔案的 `instructions` 也算有事件
- 本 checkout 有每次必載的 rule，但觀察期內 `instructions` 列出的檔案沒有任何一個解析成 `.claude/rules/**/*.md`
  → 不完整

第二條刻意不比對本 checkout 的必載 rule **名稱**：在改名所有必載 rule 的分支 worktree 執行 collect 時，期內
transcript 載入的是舊名稱，拿新名稱比對會整節量不到（R2-3）。這是 AC-2「每次必載的 rule 一條都沒有載入」的實作：
「一條都沒有」以 transcript 本身判斷，不以 checkout 的清單判斷。本 checkout 的必載清單只用於 `always_missing`：
期內 0 次的必載 rule 列在報告，可能是期間才新增或剛改成必載，不判為格式改變。被否決的作法：

1. 「任一條必載 rule 為 0 次就不完整」：新 merge 一條必載 rule 的那一週會整節量不到（I-2，AC-2 已於 2026-11-04 修訂）。
2. 「checkout 的必載 rule 全部 0 次就不完整」：即上面 R2-3 的失效。

對照只在全部失效時觸發，不會抓到「部分 session 的格式不同」。後者的偵測依賴報告上的 entrypoint 分母：每次必載
的 rule 佔比若明顯低於 100%，就是訊號。這是已接受的剩餘風險。

回傳的 warnings：讀檔失敗、壞行、目錄列舉錯誤與「找不到 transcript」只記進本來源，不回傳，因為
`collect_transcript_blocks` 對同一批檔案已經回傳（HWR-DT-097，HWR-ST-029 確認此時快照 warnings 仍非空）。
形狀不符、期內事件不足、worktree 名稱列舉失敗、格式對照與 rules 來源不完整照常回傳，使 `collect` 回傳 3。

## D5 — 報告

報告最後新增「rule 載入次數（本期，以 session 計）」：

- 表頭：session 總數、有載入專案指令的 session 數、依 entrypoint 的兩個數字
- `unresolved_worktree_paths` 大於 0 時列出：幾個 worktree 內的路徑對不上現存的 worktree、未計入下表
- `always_missing` 非空時列出：「這些每次必載的 rule 本期 0 次，可能是期間才新增或剛改成必載」
- rule 表：每次必載或前 3 個 `paths:` pattern、session 數、佔比，依 session 數由多到少排列。硬碟上存在但 0 次的
  rule 都列出；有載入紀錄但不在 `collect_rules` 清單的 rule（已刪除、位於 rules 子目錄，或屬於子專案）標「不在
  collect_rules 清單」。沒有任何 session 載入專案指令時佔比顯示 `-`
- `nested_memory` 漂移：`nested_memory_events` 只數解析成本 repo rule 或指令檔的事件（依 uuid 去重），路徑是字串
  卻解析不出來的另記 `nested_unresolved_events`。有載入專案指令的 session 至少 `RULE_LOAD_MIN_SESSIONS`（3）個、
  `nested_memory_events` 卻是 0 時，path-scoped rule 的次數與佔比改寫「量不到」，表頭說明原因；不論
  `nested_unresolved_events` 是多少都一樣，因為路徑形狀整批改變時無法解析的事件可能很多。這不使來源不完整，
  因為每次必載的 rule 仍可判讀。低於門檻時照常顯示 0，但表頭註明「以下 path-scoped 的 0 次未經對照確認」。
  快照沒有 `nested_memory_events` 欄位時照常顯示次數
  - 被否決的作法：數所有 path 是字串的 nested_memory 事件（I-7 的修法）。path 改成相對路徑、`file://` URI，或期內
    只有 repo 外的事件時偵測不會觸發（R2-5，silent-failure-hunter 的 probe.out 三組）
  - `RULE_LOAD_MIN_SESSIONS` 與 `TRANSCRIPT_MIN_EVENTS` 數值相同但單位不同（session 數 vs 事件數），分開定義
- 指令檔表（`CLAUDE.md`／`AGENTS.md`，含根目錄）：依 session 數排序
- 來源不完整：只寫「量不到」，並指向報告開頭的「量測不完整」
- 快照沒有 `rule_loads`（本 change 之前的快照）：寫明快照產生於此功能之前、沒有載入紀錄。舊快照不一定有
  「量測不完整」區塊，所以不指向它

## 驗證

- 單元與端對端測試：HWR-DT-080..102、HWR-ST-026..030（見測試檔開頭的覆蓋對映）
- mutation，依時間順序：
  1. 初版實作（commit `e0ef59a`）完成後，對 9 個單點各做一次突變：來源恆完整、使用者層計入、拿掉 cli 對照、對照改以
     任何 session 為前提、worktree 不正規化、報告忽略來源、分母改用全部 session、忽略觀察期、丟掉 nested_memory。
     其中 2 個先存活，因此刪掉無作用的 uuid 去重，並把使用者層指令檔的測試改放在 repo 路徑底下；修改後 9 個都被
     抓到。這一輪沒有留存輸出。
  2. PR #628 review 第 1 輪，pr-test-analyzer 另跑 21 個單點突變，16 個存活。其中 4 個列為必修（finding I-9）：
     M1 佔比不防除以零、M13 `cmd_collect` 傳 `repo` 而非 `main_repo`、M2 `MEMORY_REL` 拿掉 `AGENTS`、M6 不計非物件的行。
  3. PR #628 第 1 輪修正，以腳本對 8 個單點各做一次突變（備份在記憶體、確認 anchor 只出現一次、`compile()` 後刪
     `__pycache__` 再跑 `-k RuleLoads`、還原後確認逐位元相同），8 個都被抓到：
     - (a) 佔比拿掉 `if total` 防護 → HWR-DT-092
     - (b) `cmd_collect` 傳 `repo` 而非 `main_repo` → HWR-ST-028
     - (c) `MEMORY_REL` 拿掉 `AGENTS` → HWR-ST-026
     - (d) 非物件的行不計入壞行 → HWR-DT-082
     - (e) 拿掉觀察期內最少事件數 → HWR-DT-088
     - (f) 必載 rule 有任一條 0 次就判為格式改變 → HWR-DT-085
     - (g) worktree 正規化退回「名稱是第一段」 → HWR-DT-091
     - (h) 沒有載入專案指令的 session 也計入分子 → HWR-DT-086
     第 3 輪重新設計後，(f) 與 (g) 的程式已不存在：格式對照改為 D4 的形式、worktree 改用權威名稱，由第 4 點的
     (e) 與 (a) 取代。
  4. PR #628 第 2 輪修正（重新設計），同一套腳本對 9 個單點各做一次突變，9 個都被抓到：
     - (a) `resolve_repo_path` 忽略注入的名稱、改用第一段 → HWR-DT-091、HWR-DT-100、HWR-DT-101、HWR-ST-030
     - (b) `collect_worktree_roots` 吞掉 git 失敗 → HWR-DT-102
     - (c) `nested_memory_events` 也數無法解析的事件 → HWR-DT-099
     - (d) 拿掉 `ts <= now` 上界 → HWR-DT-093
     - (e) 格式對照改回比對 checkout 的必載 rule 名稱 → HWR-DT-098
     - (f) `files` 為 falsy 時不計形狀不符（`att.get("files") or []`）→ HWR-DT-094
     - (g) 分母改用原始 instructions 路徑（N11）→ HWR-DT-095
     - (h) 「沒有 instructions 事件」改用 `with_instr` 判斷（N10）→ HWR-DT-096
     - (i) `RULE_LOAD_MIN_SESSIONS` 門檻改成 `>= 1` → HWR-DT-089、HWR-ST-027
- 真實資料：對 yibi-mvp 兩週 transcript 執行 `collect`（指令與時間見 D3），來源完整、沒有 warning；7 條每次必載的
  rule 皆為 30/30
