## 1. 前置確認

- [x] 1.1 確認 PR #470 已 merge，本分支 rebase 到含 Test Seams 的 origin/main；驗證：`plugins/sdd/references/testplan-template.md` 含 `## Test Seams` 區段與 TC 表 `Seam` 欄，且 `uv run pytest plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_amplifier_verify_seams.py` 全綠

## 2. Checker 核心（先寫失敗測試）

- [x] 2.1 先寫失敗測試，涵蓋「Tests declare TC bindings through a docstring tc line」（以 docstring 的 tc 行作為唯一綁定語法：ast 解析、fixture 字串不算綁定）與「TC table declares a Kind for every test case」（TC 表新增 Kind 欄取代自由文字標記、無 Kind 欄為 legacy）；驗證：`plugins/sdd/scripts/tests/test_check_testplan_trace.py` 中這些案例在實作前為紅燈，紅燈原因是函式尚不存在或斷言失敗，而非 import 錯誤以外的環境問題
- [x] 2.2 實作 `check_testplan_trace.py` 的解析層：從測試檔以 ast 取出 tc／spec 綁定與 test nodeid、從 testplan 取出 TC 表（含 Kind、Seam）、Coverage 表的 TC 對 slug 映射、Manual Verification 項目、`trace: enforced` 宣告；驗證：2.1 的測試全綠
- [x] 2.3 先寫失敗測試再實作純函式 `check_trace`：「Unbound automated test cases are reported as missing」「Bindings to unknown TC-IDs are reported as orphans」（含 FREG／REG 改名案例）「Bindings must agree with the test case's scenario」（含 spec 行缺席案例）「A TC-ID is defined by exactly one testplan」（含 active 對 archived）；驗證：每一種 finding 各有正向與負向測試，且對每個判斷分支各做一次 mutation（拿掉判斷後至少一個測試轉紅），mutation 結果記錄在 PR 描述
- [x] 2.4 先寫失敗測試再實作「Severity ratchets from WARN to FAIL when a change claims completion」：以 testplan 內的 trace 宣告做前向式 opt-in，嚴重度 ratchet 依 tasks.md 完成度與 strict 旗標決定；驗證：spec 的 ratchet 範例表 5 列各對應一個參數化測試案例，含「0 個 checkbox 為 WARN」邊界
- [x] 2.5 先寫失敗測試再實作「Manual verification items have a tracked lifecycle」的 checker 端：strict 模式下未勾選的 MV 項目報 manual-open FAIL，已勾選不報；驗證：對應測試由紅轉綠
- [x] 2.6 實作 CLI 與「Checker exit codes separate findings from configuration errors」：exit 0／1／2 語意，未知 change、repo root 不存在、無法解析 TC 表都是 exit 2 且 stderr 有 `[FAIL]`；驗證：以 subprocess 執行 CLI 的測試覆蓋三種 exit code，且「無法解析的 enforced testplan」案例斷言 exit 2 而不是 0
- [x] 2.7 實作「Report mode lists bindings without modifying files」：報告模式不回寫任何檔案，輸出 TC、Kind、nodeid、狀態；驗證：測試斷言執行前後 `git status --porcelain` 相同且 exit 0，並對本 repo 真實執行一次 `--report`，確認 4 個既有 active change 只產生 WARN

## 3. 各入口接線

- [x] 3.1 讓「Every entry point runs the same checker」在 pr-cycle-deep 成立：checker 放在 sdd plugin，amplifier-verify 以子程序呼叫（以 installed_plugins.json 的 installPath 解析 sdd 根目錄，開發時 fallback 到 plugins/sdd），FAIL 併入 MUST、WARN 併入 SHOULD，找不到 checker 時 exit 2；驗證：`test_amplifier_verify.py` 新增案例覆蓋三種映射與「找不到 checker 即 fail-closed」，並做一次拿掉 fail-closed 分支的 mutation
- [x] 3.2 pr-cycle-deep SKILL.md（人工驗證改為 Manual Verification checklist 的流程端）：Step 11a archive 前以 `--strict --change <name>` 執行 checker，exit 1 即停止；Step 8 human quick pass 列出未勾選的 Manual Verification 項目、結果以 PR comment 留痕並勾選；驗證：`test_convergence_contract.py` 通過（行數上限內），並以 grep 確認 Step 8 與 Step 11a 都出現 checker 呼叫
- [x] 3.3 接上 pre-commit（非 strict，`verbose: true`，觸發檔案為 testplan.md、tasks.md、Python 測試）與 CI（非 strict，全 repo）；驗證：`git add` 後執行 `make ci` 通過，且在暫存的 testplan 副本注入改名的 tc 綁定時，pre-commit hook 輸出 orphan 與 missing

- [x] 3.4 讓「Summary mode keeps FAILs visible without flooding」成立：checker 新增 `--summary`（FAIL 逐行、WARN 每個 change 一行附各 kind 數量），pre-commit hook 改用此模式；驗證：`test_tpt_st_007_summary_collapses_warns_per_change` 與 `test_tpt_st_008_summary_still_lists_every_fail` 由紅轉綠，對本 repo 執行時 79 行 WARN 收斂為 4 行、exit code 不變

## 4. 生成端

- [x] 4.1 讓「Testplan generation follows the single TC-ID convention and writes the file directly」成立：TC-ID 格式以 test-convention 為唯一 owner（qa-test-designer 改用 Convention Detection 選出的約定，Technique 只放 Technique 欄）；qa-test-designer 直接寫 testplan 檔（增加 Write tool，產出 `trace: enforced`、Kind 欄、Manual Verification 區段，只回傳摘要）；同步更新 testplan 模板與 spectra-amplifier Step 2a／2b／2c；驗證：以模板本身跑 checker `--report` 可解析且 exit 0，並以 grep 確認 qa-test-designer.md 不再出現 `[CAP-ABBREV]-[TECHNIQUE-ABBREV]`
- [x] 4.2 讓「Generated tasks put a failing bound test first」成立：tasks.md 產生 red-first 測試任務（每個 US 的第一個任務列出該 US 的 auto TC-ID）；更新 tasks 模板與 spectra-amplifier 的 tasks.md 格式段；驗證：內容 review 確認模板每個 US 區塊第一項為綁定 tc 的失敗測試任務，且與 PR #469 的 red-first gate 用語一致
- [x] 4.3 修正 spectra-amplifier SKILL.md 完工標準中「testplan.md 所有 TC 均有對應測試（check_spec_coverage.py 驗證）」的不實宣稱，改為指向 `check_testplan_trace.py --strict`；更新 bdd-trace-convention.md 與 plugins/sdd/scripts/README.md 說明 tc 行與 checker 用法、以及 host 專案的手動接線步驟；驗證：以 grep 確認 SKILL.md 不再宣稱 check_spec_coverage.py 驗證 TC，且 README 範例指令實際執行成功

## 5. 收尾

- [ ] 5.1 依 lockstep 慣例 bump 版本並更新 CHANGELOG（若 #471 已先 merge 則接續其版號）；驗證：`bash scripts/sync-plugin-versions.sh` 輸出全部 `[OK]`，`make ci` 通過且 `git diff --name-only` 為空
