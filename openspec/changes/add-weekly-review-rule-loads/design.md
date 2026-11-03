# Design：add-weekly-review-rule-loads

## D1 — 資料來源：transcript 的兩種 attachment

實測（yibi-mvp，Claude Code 2.1.316／2.1.317，2026-11-03）：

| attachment `type` | 何時出現 | 帶的路徑欄位 | 載入的內容 |
|---|---|---|---|
| `instructions` | session 開始（`reason: session_start` 或缺漏），設定變更時重載（`reason: account_change`，另帶 `removed`） | `files[].path`，`files[].type` 為 `Project` 或 `User` | 根目錄 `CLAUDE.md`／`AGENTS.md`、沒有 `paths:` 或 `paths: "**"` 的 rule、`~/.claude/CLAUDE.md`（`User`） |
| `nested_memory` | 工具第一次碰到符合 `paths:` 的檔案時 | `path` | path-scoped rule、子目錄 `CLAUDE.md` |

確認方式：在最近 60 份 transcript 中，每次必載的 `14-retirement-residual-sweep.md` 只出現在 `instructions`（26 次），
從未出現在 `nested_memory`。

## D2 — 計數單位與正規化

- 單位是 sessionId，每個 rule 對應一個 session 集合。同一 session 重載、或同一事件在主 checkout 與 worktree 的
  transcript 各出現一次，都不會重複計數；因此不需要像 `collect_transcript_blocks` 那樣依 uuid 去重。
  `nested_memory_events`（見 D5）是事件數而非 session 數，所以這個欄位依 uuid 去重。
- 路徑：去掉 `<main_repo>/` 前綴後，只收 `.claude/rules/**/*.md`（rule，含 rules 子目錄）與 `**/CLAUDE.md`、
  `**/AGENTS.md`（指令檔，含根目錄）。不在 repo 底下的路徑不計。
- `<main_repo>/.claude/worktrees/` 底下的路徑要去掉 worktree 名稱，而名稱可以含 `/`（例如 `feat/x`）：
  - rule 以路徑中最後一個 `/.claude/rules/` 為錨點。
  - 其他檔案比對已知的 worktree 名稱，取最長者。已知名稱取自所有 rule 路徑中 `/.claude/rules/` 之前的部分，
    所以要先收齊整批 transcript 的路徑，再統一正規化。
  - 都對不上時才把第一段當名稱。此時名稱含 `/` 的 worktree 根目錄 `CLAUDE.md` 會被當成子目錄的檔案；只在整批
    transcript 都沒有該 worktree 的 rule 路徑時發生。
  - 被否決的作法：只去掉 `.claude/worktrees/` 之後的第一段。PR #628 review 以 `feat/x` 重現它丟失 rule 載入，
    並捏造 `x/CLAUDE.md`。
- `instructions.files[].type == "User"` 不計。這不能只靠路徑判斷：repo 就是家目錄時（dotfiles repo），
  `~/.claude/CLAUDE.md` 也在 repo 底下。
- 觀察期的單位是 session，不是事件：至少有一筆事件的 timestamp 在 `since` 之後的 session 才算觀察期內的
  session，這種 session 的所有載入紀錄都算，不論 attachment 本身的時間。觀察期開始前載入的指令在期內仍在
  context 裡。被否決的作法：以事件時間過濾。跨越 `since` 的 session 會讓期內的 `nested_memory` 進分子，
  期前的 `instructions` 卻被濾掉而不進分母，PR #628 review 以探針重現佔比 150% 與 200%。

## D3 — 分母

實測（yibi-mvp，2026-11-03 量測，觀察期 14 天：2026-10-20T15:44Z 到 2026-11-03T15:44Z）。量測對象是
`worktree-trim-always-loaded-rules` 分支（HEAD `a4bb2bafa`）的 checkout，transcript 取主 repo 與其 worktree：

```bash
python3 plugins/harness/skills/harness-weekly-review/scripts/harness_review.py collect \
  --repo /Users/howie/Workspace/github/heyu/yibi-mvp/.claude/worktrees/trim-always-loaded-rules \
  --days 14 --no-ci --out snap-fix.json
```

| entrypoint | session 數 | 有載入專案指令 | 看得到 rule 14 |
|---|---:|---:|---:|
| `cli` | 28 | 28 | 28 |
| `sdk-cli` | 2 | 2 | 2 |
| `sdk-py` | 96 | 0 | 0 |
| `(unknown)` | 1 | 0 | 0 |
| 合計 | 127 | 30 | 30 |

「看得到 rule 14」欄是推導值：快照記錄 rule 14 共 30 個 session，而 rule 只計入有載入專案指令的 session
（共 30 個），所以每個有載入專案指令的 session 都有它。同一份快照中 7 條每次必載的 rule 皆為 30 個 session，
`excluded_sessions` 為 0，`nested_memory_events` 為 1161。

所以佔比的分母是「有載入專案指令的 session 數」，報告另依 entrypoint 列出兩個數字。「有載入專案指令」的
判定是：`instructions` 列出至少一個本 repo 內、非使用者層的檔案。只列出使用者層檔案的 session 不進分母，
它的 path-scoped 載入也不進分子，只記進 `excluded_sessions`，否則佔比可超過 100%。`sdk-py` session 為什麼不載入
專案指令不在本 change 範圍；報告讓它看得見即可。

## D4 — 來源完整性與格式對照

沿用 `make_source`。下列情況都使本來源不完整：

- 任一檔案讀取失敗、任一目錄列不出來
- 任一行不是合法 JSON，或是合法 JSON 但不是物件
- attachment 形狀不符：`nested_memory.path` 或 `instructions.files[].path` 不是字串，或 `files` 不是清單
- 找不到 transcript
- transcript 存在，但觀察期內有時間戳的事件少於 `TRANSCRIPT_MIN_EVENTS`（3）筆。門檻與 `evaluation_scope`
  對 transcript 類建議的要求一致；timestamp 欄位改名時每一行都會被當成沒有時間戳，靠這條抓到
- `rules` 來源不完整

另加格式對照，前提是觀察期內至少有一個 `entrypoint` 等於 `cli` 的 session（精確比對，`sdk-cli` 不算）：

- 沒有任何 `instructions` 事件 → 不完整
- `collect_rules` 判定為每次必載的 rule **一條都沒有**載入 → 不完整

只有部分必載 rule 為 0 次時不判為格式改變：那條 rule 可能是期間才新增或剛改成必載。名稱記進 `always_missing`，
報告列出。被否決的作法：「任一條必載 rule 為 0 次就不完整」，新 merge 一條必載 rule 的那一週會整節量不到。

對照只在全部失效時觸發，不會抓到「部分 session 的格式不同」。後者的偵測依賴報告上的 entrypoint 分母：每次必載
的 rule 佔比若明顯低於 100%，就是訊號。這是已接受的剩餘風險。

目錄列舉錯誤與「找不到 transcript」只記進本來源，不再回傳成 warning，因為 `collect_transcript_blocks` 已經發過；
其他錯誤照常進 `warnings`，使 `collect` 回傳 3。

## D5 — 報告

報告最後新增「rule 載入次數（本期，以 session 計）」：

- 表頭：session 總數、有載入專案指令的 session 數、依 entrypoint 的兩個數字
- `always_missing` 非空時列出：「這些每次必載的 rule 本期 0 次，可能是期間才新增或剛改成必載」
- rule 表：每次必載或前 3 個 `paths:` pattern、session 數、佔比，依 session 數由多到少排列。硬碟上存在但 0 次的
  rule 都列出；有載入紀錄但不在 `collect_rules` 清單的 rule（已刪除，或位於 rules 子目錄）標「不在 collect_rules
  清單」。沒有任何 session 載入專案指令時佔比顯示 `-`
- `nested_memory` 漂移：有載入專案指令的 session 至少 `TRANSCRIPT_MIN_EVENTS` 個、`nested_memory_events` 卻是 0 時，
  path-scoped rule 的次數與佔比改寫「量不到」，表頭說明原因。這不使來源不完整，因為每次必載的 rule 仍可判讀；
  門檻以下的 0 次可能只是期間沒人碰那些路徑，照常顯示。快照沒有 `nested_memory_events` 欄位時照常顯示次數
- 指令檔表（`CLAUDE.md`／`AGENTS.md`，含根目錄）：依 session 數排序
- 來源不完整：只寫「量不到」，並指向報告開頭的「量測不完整」
- 快照沒有 `rule_loads`（本 change 之前的快照）：寫明快照產生於此功能之前、沒有載入紀錄。舊快照不一定有
  「量測不完整」區塊，所以不指向它

## 驗證

- 單元與端對端測試：HWR-DT-080..092、HWR-ST-026..028（見測試檔開頭的覆蓋對映）
- mutation，依時間順序：
  1. 初版實作（commit `e0ef59a`）完成後，對 9 個單點各做一次突變：來源恆完整、使用者層計入、拿掉 cli 對照、對照改以
     任何 session 為前提、worktree 不正規化、報告忽略來源、分母改用全部 session、忽略觀察期、丟掉 nested_memory。
     其中 2 個先存活，因此刪掉無作用的 uuid 去重，並把使用者層指令檔的測試改放在 repo 路徑底下；修改後 9 個都被
     抓到。這一輪沒有留存輸出。
  2. PR #628 review 第 1 輪，pr-test-analyzer 另跑 21 個單點突變，16 個存活。其中 4 個列為必修（finding I-9）：
     M1 佔比不防除以零、M13 `cmd_collect` 傳 `repo` 而非 `main_repo`、M2 `MEMORY_REL` 拿掉 `AGENTS`、M6 不計非物件的行。
  3. PR #628 修正輪，以腳本對 8 個單點各做一次突變（備份在記憶體、確認 anchor 只出現一次、`compile()` 後刪
     `__pycache__` 再跑 `-k RuleLoads`、還原後確認逐位元相同），8 個都被抓到：
     - (a) 佔比拿掉 `if total` 防護 → HWR-DT-092
     - (b) `cmd_collect` 傳 `repo` 而非 `main_repo` → HWR-ST-028
     - (c) `MEMORY_REL` 拿掉 `AGENTS` → HWR-ST-026
     - (d) 非物件的行不計入壞行 → HWR-DT-082
     - (e) 拿掉觀察期內最少事件數 → HWR-DT-088
     - (f) 必載 rule 有任一條 0 次就判為格式改變 → HWR-DT-085
     - (g) worktree 正規化退回「名稱是第一段」 → HWR-DT-091
     - (h) 沒有載入專案指令的 session 也計入分子 → HWR-DT-086
- 真實資料：對 yibi-mvp 兩週 transcript 執行 `collect`（指令與時間見 D3），來源完整、沒有 warning；7 條每次必載的
  rule 皆為 30/30
