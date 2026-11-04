## 1. 實測資料形狀

- [x] 1.1 確認每次必載與 path-scoped rule 分別由哪種 transcript attachment 帶入；驗證：design.md D1 的實測表
- [x] 1.2 量出各 entrypoint 的 session 數與載入專案指令的比例；驗證：design.md D3 的實測表

## 2. 實作

- [x] 2.1 新增 `repo_relative` 與 `collect_rule_loads`，接進 `cmd_collect`，快照新增 `rule_loads`；驗證：HWR-DT-080、HWR-ST-026、HWR-ST-027
- [x] 2.2 來源完整性與格式對照（design.md D4）；驗證：HWR-DT-081、HWR-DT-082
- [x] 2.3 報告新增「rule 載入次數」一節（design.md D5）；驗證：HWR-DT-083、HWR-ST-027

## 3. 驗證

- [x] 3.1 對 9 個單點各做一次 mutation（來源恆完整、使用者層計入、拿掉 cli 對照、對照改以任何 session 為前提、
  worktree 不正規化、報告忽略來源、分母改用全部 session、忽略觀察期、丟掉 nested_memory），全數被新測試抓到；
  備註：測試寫在實作之後，不是 red-first，所以改以 mutation 證明測試守得住
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
- [x] 5.2 只有部分必載 rule 為 0 次不判為格式改變，改列 `always_missing`（I-2）；驗證：HWR-DT-085
- [x] 5.3 「有載入專案指令」只認列出本 repo 內非使用者層檔案的 instructions，其他 session 記進
  `excluded_sessions`（I-3）；驗證：HWR-DT-086
- [x] 5.4 rules 子目錄內的 rule 照樣計數，報告標明不在 collect_rules 清單（I-4）；驗證：HWR-DT-087
- [x] 5.5 指令檔表改名為「指令檔（CLAUDE.md／AGENTS.md）」，docstring 與 SKILL.md 涵蓋根目錄（I-5）；驗證：HWR-DT-083
- [x] 5.6 觀察期內有時間戳的事件少於 `TRANSCRIPT_MIN_EVENTS` 時來源不完整（I-6）；驗證：HWR-DT-088
- [x] 5.7 記錄 `nested_memory_events`，漂移時 path-scoped 次數顯示量不到；attachment 形狀不符時來源不完整（I-7）；
  驗證：HWR-DT-089、HWR-DT-090
- [x] 5.8 名稱含 `/` 的 worktree 正規化（I-8）；驗證：HWR-DT-091
- [x] 5.9 補測試缺口 M1、M13、M2、M6（I-9）；驗證：HWR-DT-092、HWR-ST-028、HWR-ST-026、HWR-DT-082
- [x] 5.10 docstring、spec、design D4 改寫為「entrypoint 等於 cli」（I-10）
- [x] 5.11 舊快照與來源不完整的「量不到」各自說明原因（I-11）；驗證：HWR-DT-083
- [x] 5.12 目錄列舉錯誤不重複發 warning、改用旗標判斷「找不到 transcript」，補排序與表頭總數斷言（NIT）；
  驗證：HWR-DT-082、HWR-DT-083
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
  ST-030 `assert None == 0`
- [x] 6.3 格式對照不比對執行 checkout 的必載 rule 名稱（R2-3）；驗證：HWR-DT-098。紅燈：
  `{'complete': False} != {'complete': True}`
- [x] 6.4 attachment 不是物件、`files` 缺漏或不是清單（含 `{}`、`""`）計為形狀不符（R2-4）；驗證：HWR-DT-094。
  紅燈：`AssertionError: attachment-string`（`assert True is False`）
- [x] 6.5 `nested_memory_events` 只數可解析的事件、另記 `nested_unresolved_events`；新增 `RULE_LOAD_MIN_SESSIONS`；
  低於門檻時表頭註明未經對照確認（R2-5、CR-10、NIT）；驗證：HWR-DT-099、HWR-DT-089。紅燈：DT-099
  `AssertionError: relative`（`assert 6 == 0`）；DT-089 新表頭文字不在報告中
- [x] 6.6 補 N9、N10、N11 的區別測試（R2-6）：HWR-DT-081 追加 `always_missing == []`、HWR-DT-095、HWR-DT-096。
  守既有行為，修正前即通過，以 design.md「驗證」第 4 點的 mutation (g)、(h) 證明有效
- [x] 6.7 讀檔失敗與壞行不再重複回傳成 warning（CR-7）；驗證：HWR-DT-097，HWR-ST-029 確認快照 warnings 仍非空。
  紅燈：`assert ['rule 載入：略過 1 行格式錯誤（可能被截斷）的紀錄'] == []`
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
  `assert {} == {'CLAUDE.md': 1, 'backend/CLAUDE.md': 1}`。mutation 見 design.md「驗證」第 5 點
- [x] 6.12 以 2026-11-04 的新快照（snap-fix3）重寫 design D2、D3、proposal、design「驗證」、SKILL.md 與 docstring 的
  數字：`unresolved_worktree_paths` 33 降為 10、根目錄 `CLAUDE.md` 27/30 升為 30/30
