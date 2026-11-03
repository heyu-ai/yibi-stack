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
- [x] 3.3 既有 harness-weekly-review 測試（133 個）全數通過；`make ci` 的 pre-commit 全數通過（`git add` 之後跑）。
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
