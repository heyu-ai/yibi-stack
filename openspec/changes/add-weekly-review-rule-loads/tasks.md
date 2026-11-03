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
