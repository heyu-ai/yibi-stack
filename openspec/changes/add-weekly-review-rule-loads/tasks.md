## 1. 實測資料形狀

- [x] 1.1 確認每次必載與 path-scoped rule 分別由哪種 transcript attachment 帶入；驗證：design.md D1 的實測表
- [x] 1.2 量出各 entrypoint 的 session 數與載入專案指令的比例；驗證：design.md D3 的實測表

## 2. 實作

- [x] 2.1 新增 `repo_relative` 與 `collect_rule_loads`，接進 `cmd_collect`，快照新增 `rule_loads`；驗證：HWR-DT-080、HWR-ST-026、HWR-ST-027。
  備註：`repo_relative` 已於 7.6 移除，測試改呼叫 `resolve_repo_path`
- [x] 2.2 來源完整性與格式對照（design.md D4）；驗證：HWR-DT-081、HWR-DT-082。備註：格式對照已於 7.2 移除（design.md D7）
- [x] 2.3 報告新增「rule 載入次數」一節（design.md D5）；驗證：HWR-DT-083、HWR-ST-027

## 3. 驗證

- [x] 3.1 對 9 個單點各做一次 mutation（來源恆完整、使用者層計入、拿掉 cli 對照、對照改以任何 session 為前提、
  worktree 不正規化、報告忽略來源、分母改用全部 session、忽略觀察期、丟掉 nested_memory），全數被新測試抓到；
  備註：測試寫在實作之後，不是 red-first，所以改以 mutation 確認測試守得住。這一輪沒有留存 mutation 輸出，
  只有本行與 design.md「驗證」第 1 點的文字紀錄
- [x] 3.2 對 yibi-mvp 兩週真實 transcript 執行 collect 與 report；驗證：每次必載的 rule 皆 100%、分母排除 `sdk-py`
- [x] 3.3 既有 harness-weekly-review 測試（133 個，為當時的數量；第 1 輪 review 修正後為 149 個，第 2 輪見 6.10）全數通過；`make ci` 的 pre-commit 全數通過（`git add` 之後跑）。
  `make ci` 整體 exit 2：pytest 4,850 passed、70 failed，70 個全在 `test_red_first_sh.py`，在同一環境以乾淨的
  `origin/main` 跑該檔結果相同（70 failed），與本 change 無關；推測是 background session 設了 `CLAUDE_JOB_DIR`，
  未在一般終端機實測

## 4. 文件

- [x] 4.1 SKILL.md 新增「怎麼讀 rule 載入次數表」，腳本 docstring 補資料來源
- [x] 4.2 補寫 testplan.md（`trace: enforced`）與 proposal 的 `type: feat`，6 個測試以 `spec:`／`tc:` 綁定；
  spec 補上 unreadable-or-truncated-transcript 與 zero-load-rule-is-listed 兩個 scenario；驗證：
  `check_testplan_trace.py --strict --report --change add-weekly-review-rule-loads` 6 個 TC 皆為 bound

## 5. PR #628 review 修正

- [x] 5.1 跨越觀察期起點的 session 以整個 session 計，分子分母同一批（I-1）；驗證：HWR-DT-084
- [x] 5.2 只有部分必載 rule 為 0 次不判為格式改變，改列 `always_missing`（I-2）；驗證：HWR-DT-085。
  備註：7.2 之後 `always_missing` 不論幾條都只作資訊
- [x] 5.3 「有載入專案指令」只認列出本 repo 內非使用者層檔案的 instructions，其他 session 記進
  `excluded_sessions`（I-3）；驗證：HWR-DT-086
- [x] 5.4 rules 子目錄內的 rule 照樣計數，報告標明不在 collect_rules 清單（I-4）；驗證：HWR-DT-087
- [x] 5.5 指令檔表改名為「指令檔（CLAUDE.md／AGENTS.md）」，docstring 與 SKILL.md 涵蓋根目錄（I-5）；驗證：HWR-DT-083
- [x] 5.6 觀察期內有時間戳的事件少於 `TRANSCRIPT_MIN_EVENTS` 時來源不完整（I-6）；驗證：HWR-DT-088
- [x] 5.7 記錄 `nested_memory_events`，漂移時 path-scoped 次數顯示量不到；attachment 形狀不符時來源不完整（I-7）；
  驗證：HWR-DT-089、HWR-DT-090。備註：「顯示量不到」已於 7.2 移除，`nested_memory_events` 改為表頭的原始計數
- [x] 5.8 名稱含 `/` 的 worktree 正規化（I-8）；驗證：HWR-DT-091
- [x] 5.9 補測試缺口 M1、M13、M2、M6（I-9）；驗證：HWR-DT-092、HWR-ST-028、HWR-ST-026、HWR-DT-082
- [x] 5.10 docstring、spec、design D4 改寫為「entrypoint 等於 cli」（I-10）。備註：cli 對照已於 7.2 移除
- [x] 5.11 舊快照與來源不完整的「量不到」各自說明原因（I-11）；驗證：HWR-DT-083。備註：7.4 改為直接列出原因
- [x] 5.12 目錄列舉錯誤不重複發 warning、改用旗標判斷「找不到 transcript」，補排序與表頭總數斷言（NIT）；
  驗證：HWR-DT-082、HWR-DT-083。備註：「不重複發 warning」已由 7.5 取代
- [x] 5.13 對 8 個單點 mutation 確認全數被抓到；驗證：design.md「驗證」第 3 點
- [x] 5.14 以同一份快照重寫 D3、proposal、design「驗證」、SKILL.md 與 docstring 的實測數字（I-12）；
  驗證：design.md D3 的量測指令與時間
- [x] 5.15 `check_testplan_trace.py --strict --report --change add-weekly-review-rule-loads` 全部 TC 皆為 bound

## 6. PR #628 review 第 2 輪修正（owner 裁決重新設計）

行為類項目先寫測試、在修正前的產品碼以斷言失敗（下列「紅燈」），再改產品碼。

- [x] 6.1 觀察期以 `now` 為上界（R2-1）；驗證：HWR-DT-093。紅燈：`assert 2 == 1`（session 數）
- [x] 6.2 worktree 名稱改取自 `git worktree list` 與 `.claude/worktrees/` 的實際目錄（`collect_worktree_roots`），
  `RULE_REL` 收子專案 rule，拿掉「最後一個 `/.claude/rules/`」推論，對不上的非 rule 路徑計入
  `unresolved_worktree_paths`（R2-2、R2-7、R2-8、CR-9）；驗證：HWR-DT-100、HWR-DT-101、HWR-DT-102、HWR-ST-030。
  紅燈：DT-100 `assert 'x' is None`；DT-101 `assert 'x/CLAUDE.md' is None`；DT-102 `assert set() == {'outer', ...}`；
  ST-030 `assert None == 0`。備註：7.1 改為只看第一層目錄，rule 路徑的「第一個 `/.claude/rules/`」推回也移除
- [x] 6.3 格式對照不比對執行 checkout 的必載 rule 名稱（R2-3）；驗證：HWR-DT-098。紅燈：
  `{'complete': False} != {'complete': True}`。備註：格式對照與 HWR-DT-098 已於 7.2 移除
- [x] 6.4 attachment 不是物件、`files` 缺漏或不是清單（含 `{}`、`""`）計為形狀不符（R2-4）；驗證：HWR-DT-094。
  紅燈：`AssertionError: attachment-string`（`assert True is False`）
- [x] 6.5 `nested_memory_events` 只數可解析的事件、另記 `nested_unresolved_events`；新增 `RULE_LOAD_MIN_SESSIONS`；
  低於門檻時表頭註明未經對照確認（R2-5、CR-10、NIT）；驗證：HWR-DT-099、HWR-DT-089。紅燈：DT-099
  `AssertionError: relative`（`assert 6 == 0`）；DT-089 新表頭文字不在報告中。備註：`RULE_LOAD_MIN_SESSIONS` 與
  兩種表頭註明已於 7.2 移除，兩個計數保留為原始計數
- [x] 6.6 補 N9、N10、N11 的區別測試（R2-6）：HWR-DT-081 追加 `always_missing == []`、HWR-DT-095、HWR-DT-096。
  守既有行為，修正前即通過，以 design.md「驗證」第 4 點的 mutation (g)、(h) 確認有效
- [x] 6.7 讀檔失敗與壞行不再重複回傳成 warning（CR-7）；驗證：HWR-DT-097，HWR-ST-029 確認快照 warnings 仍非空。
  紅燈：`assert ['rule 載入：略過 1 行格式錯誤（可能被截斷）的紀錄'] == []`。備註：已由 7.5 取代
- [x] 6.8 以 2026-11-04 的同一份快照重寫 design D3、proposal、design「驗證」、SKILL.md 與 docstring 的數字，註明量的是
  分支 checkout、兩個 incident-log 檔於 2026-11-03 建立、main 為 35／28（R2-9）；修 design D2 的去重矛盾、
  HWR-DT-089 的註解來源、SKILL.md「夠多」改寫門檻（NIT）
- [x] 6.9 spec 新增 10 個 scenario 並更新 AC-2 相關 requirement；testplan 新增 12 個 TC；
  `check_testplan_trace.py --strict --report --change add-weekly-review-rule-loads` 28 個 TC 皆為 bound
- [x] 6.10 9 個單點 mutation 全數被抓到（design.md「驗證」第 4 點）；`pytest scripts/tests/test_harness_weekly_review.py`
  161 passed；`pre-commit run --all-files` 通過（`git add` 之後跑）
- [x] 6.11 已刪除的 worktree 以 transcript 目錄名稱（`<slug>--claude-worktrees-<X>`）推回根目錄：取正規化後恰好
  等於 X 的最短路徑前綴，主 repo 目錄的路徑不套用（design.md D2）；HWR-DT-101 改用對不上的目錄名稱。驗證：
  HWR-DT-103、HWR-DT-104、HWR-DT-105、HWR-DT-106。紅燈：DT-103、DT-104
  `assert {} == {'CLAUDE.md': 1, 'backend/CLAUDE.md': 1}`。mutation 見 design.md「驗證」第 5 點。
  備註：整段推回與 HWR-DT-103..106 已於 7.1 移除（design.md D7 第 4 點）
- [x] 6.12 以 2026-11-04 的新快照（snap-fix3）重寫 design D2、D3、proposal、design「驗證」、SKILL.md 與 docstring 的
  數字：`unresolved_worktree_paths` 33 降為 10、根目錄 `CLAUDE.md` 27/30 升為 30/30。備註：兩個數字來自觀察期
  不同的兩份快照；7.10 以 snap-fix4 全面改寫

## 7. PR #628 完整 diff 重審後縮小宣稱（owner 裁決，design.md D7）

測試先改寫或新增，在修正前的產品碼執行並記下紅燈，再改產品碼。下列紅燈中 `KeyError` 是新欄位尚不存在造成的
失敗，不是斷言失敗；其餘為斷言失敗。

- [x] 7.1 `collect_worktree_roots` 只取 git worktree list 與 `.claude/worktrees/` 第一層含 `.git` 的目錄（略過 `.` 開頭），
  列目錄失敗記錯誤；拿掉 transcript 目錄名稱推回與 `/.claude/rules/` 錨點推回，對不上的路徑只計入
  `unresolved_worktree_paths`（W-1..W-4）。驗證：HWR-DT-101、HWR-DT-102、HWR-DT-107。紅燈：DT-101
  `assert ('.claude/rul...ys.md', False) == (None, True)`；DT-102 `assert {'.cache', 'o...er', 'walked'} == {...}`
  （多出 `.cache` 與 `old/vendor/lib`）。DT-107 守修正前就成立的行為，以 mutation (b) 確認有效
- [x] 7.2 拿掉 cli session 對照、「instructions 沒有 rules 路徑」對照、nested_memory 門檻與 `RULE_LOAD_MIN_SESSIONS`
  （F-2、F-3、F-4）；刪除 HWR-DT-098。驗證：HWR-DT-081、HWR-DT-089、HWR-DT-099。紅燈：DT-081 與 DT-089
  `KeyError: 'instructions_events'`；DT-099 `AssertionError: relative`（仍顯示量不到）
- [x] 7.3 形狀錯誤依 session 暫存，只計觀察期內的 session（F-1）。驗證：HWR-DT-108。紅燈：
  `assert ({'complete': ...可能已改變，本週未量測']} == {'complete': ... 'errors': []}`
- [x] 7.4 快照新增 `instructions_events`；沒有 uuid 的替代 id 含 sessionId 與行號（CR-4）；報告表頭固定列出原始計數與
  「格式漂移不保證偵測」，instructions 事件為 0 時加「注意」一行，不完整時直接列出原因，不在清單的 rule 改標
  「可能已刪除、位於 rules 子目錄，或屬於子專案」（F-5、D-2）。驗證：HWR-ST-026、HWR-DT-083、HWR-DT-087、
  HWR-DT-096、HWR-DT-100、HWR-DT-109、HWR-DT-110。紅燈：ST-026、DT-096、DT-109 `KeyError: 'instructions_events'`；
  DT-083 `AssertionError: instructions 事件 6 筆`；DT-087、DT-100 新標籤不在報告中；DT-110 「注意」不在報告中
- [x] 7.5 `collect_rule_loads` 回傳全部 `source.errors`；讀檔、壞行、列目錄、找不到 transcript 的文字與
  `collect_transcript_blocks` 共用，`cmd_collect` 只去掉逐位元相同者，不依類別略過（F-5）。驗證：HWR-DT-082、
  HWR-DT-097、HWR-ST-029、HWR-ST-031、HWR-ST-032。紅燈：DT-082 與 DT-097 `[] == ['rule 載入：略過 1 行格式錯誤…']`；
  ST-029 rule_loads 的讀取失敗不在快照 warnings；ST-031 `{'rule 載入：略過 …'} <= {…}` 不成立。ST-032 守修正前
  就成立的行為，以 mutation (f) 確認有效
- [x] 7.6 移除只剩測試在用的 `repo_relative`、`transcript_worktree_slug`、`worktree_root_from_dir_slug`（CR-9），
  測試改呼叫 `resolve_repo_path`
- [x] 7.7 spec、testplan、design（新增 D6、D7 並改寫 D2..D5）、proposal、SKILL.md 與 docstring 改寫為縮小後的設計；
  HWR-DT-081 的 docstring、覆蓋對映與 testplan 改為現行行為（D-1）；tasks 3.1 的 mutation 措辭、33→10 的觀察期
  差異、9/1 查證標為一次性量測、proposal 狀態行、sdk-py 敘述的範圍（NIT）
- [x] 7.8 9 個單點 mutation 全數被抓到（design.md「驗證」第 6 點）
- [x] 7.9 `check_testplan_trace.py --strict --change add-weekly-review-rule-loads` exit 0；測試的 `spec:` 綁定與
  spec.md 的 32 個 scenario 兩個方向一致
- [x] 7.10 以 2026-11-04 的 snap-fix4 重寫 design D2、D3、proposal、SKILL.md 的數字：`cli` 24/30、
  `unresolved_worktree_paths` 324（16 個已刪除的 worktree）、`instructions_events` 257、`nested_memory_events` 106
