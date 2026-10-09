## 1. 先寫會失敗的正向對照（TDD）

- [x] 1.1 建立 `scripts/tests/fixtures/rule_mechanization/` 並放入九個 `bad_*.diff`（新檔缺宣告、既有檔缺宣告、無 section 的新檔、dangling link、link 到 rule、缺 symbol、未知 reason、佔位說明、雙重宣告），形狀分散於新 rule 檔、既有 rule 檔新增 section、rename 進 `.claude/rules/` 三種來源；完成時目錄內可列出這九種形狀。驗證：`test_every_blocking_shape_has_a_fixture` 斷言九個檔名齊全（Every blocking shape has a committed positive control）。
- [x] 1.2 放入 `good_*.diff`（有效 gate link、完整豁免、code fence 內引用不計、table row 內引用不計）。完成時每個 good fixture 都被預期為零 finding。驗證：`test_good_fixtures_report_nothing` 以純函式與 `main()` 兩條路徑斷言。
- [x] 1.3 在 `scripts/tests/test_lint_rule_evidence.py` 為每個 bad fixture 寫「純函式回傳非空」與「`main([fixture_path])` 回傳非零」兩條斷言，並先確認全部為紅（此時尚未實作）。驗證：`uv run pytest scripts/tests/test_lint_rule_evidence.py -k mechanization` 紅燈輸出貼進 PR 描述。
- [x] 1.4 寫真實資料對照：測試時複製 `.claude/rules/` 下一份真實 rule 檔，先斷言注入錨點存在，再注入未宣告 section 並產生 diff，斷言 lint 回報該 heading。完成時錨點找不到會讓測試失敗而非跳過。驗證：`test_real_rule_copy_with_injected_section_is_flagged`，另有 `test_injection_anchor_missing_fails` 以不含錨點的檔案驗證失敗路徑。

## 2. 宣告偵測

- [x] 2.1 實作「宣告語法使用 HTML 註解，與證據標記同形」：新增宣告 regex 常數，能解析 gate link（含 `::symbol`）與 gate exemption 兩種形式；宣告行在 fenced code block 與 table row 內不計。實作 `check_rule_mechanization` / `warn_rule_mechanization` 的 section 掃描（重用 `_missing_evidence_in_chunk` 的 hunk 內 heading 錨點邏輯）。驗證：Added rule sections carry a mechanization declaration 的四個 scenario 對應測試轉綠（有效 link 通過、缺宣告被報告、code fence 內不計、雙重宣告被拒）。

## 3. 連結解析

- [x] 3.1 實作「路徑驗證以注入的讀檔函式完成，純函式不碰檔案系統」：`read_gate_file(path) -> str | None` 介面，測試以字典假實作注入，production 以 `REPO_ROOT` 為基準。完成時純函式對合成 diff 加假檔案系統即可構造所有負向案例。驗證：不碰真實檔案系統的 `test_dangling_link_is_error` 與 `test_missing_symbol_is_error` 綠燈。
- [x] 3.2 實作「合格 gate 目錄為封閉清單且不含 rule 與 SKILL.md」：A gate link must resolve to an eligible gate——合格集合為 `scripts/`、`.claude/hooks/`、`.pre-commit-config.yaml`、`.github/workflows/` 與 `scripts/`、`tasks/` 下的 `tests/`；含 `..` 或絕對路徑一律拒絕；symbol 以整字比對。驗證：spec 內「eligibility of link targets」表的六列各有一個參數化測試案例。

## 4. 豁免理由

- [x] 4.1 實作「豁免理由為三值封閉列舉」：Gate exemption reasons form a closed set——`judgment`、`no-observable-signal`、`hook-cost`；說明至少 12 個非空白字元且不可為 `TBD` / `TODO` / `N/A` / `none`。驗證：未知 reason、佔位說明被拒、完整豁免通過三個 scenario 對應測試。

## 5. 強制語意與入口接線

- [x] 5.1 實作「缺宣告與假宣告在所有 rule 檔一律為 error」：Missing and false declarations are errors in every rule file——新檔與既有檔缺宣告皆 error、rename 進來視為新檔、假宣告同為 error。驗證：新檔缺宣告、既有檔缺宣告、rename 三個 scenario 對應測試。
- [x] 5.2 實作「宣告檢查與證據檢查各自獨立執行」：The declaration check is independent of the evidence check——在 `main()` 並列呼叫兩組檢查並合併輸出，兩者互不替代。驗證：「證據標記不滿足宣告」與「宣告不滿足證據標記」兩個 scenario 的測試；staged 與 `--base/--head` 兩種模式各跑一次。
- [x] 5.3 實作 The check fails loudly when it cannot verify a link：`read_gate_file` 的非「不存在」`OSError` 由 `main()` 轉成 exit 2 加 `[FAIL]`，不印 `[OK]`。驗證：注入會 raise `OSError` 的假實作，斷言 `main()` 回傳 2 且 stderr 含 `[FAIL]`。

## 6. 突變驗證（每次只改一件事）

- [x] 6.1 突變 A：把 `main()` 改成讀 diff 前 `return 0`，先斷言替換 anchor 已套用，再確認九個 bad fixture 的 `main()` 測試全部轉紅，最後以反向替換還原（不用 `git checkout`）。驗證：紅燈數量與測試名稱貼進 PR 描述。
- [x] 6.2 突變 B：把 `.claude/rules/` 加入合格目錄清單，確認「link 到 rule」fixture 轉紅後還原。突變 C：把 `read_gate_file` 的 `OSError` 吞成 `None`，確認 exit 2 測試轉紅後還原。驗證：各自斷言 anchor 已套用，還原後全套測試重新全綠。

## 7. SKILL.md 與 rule 11 同步

- [x] 7.1 實作「SKILL.md 與 rule 11 同步」：`plugins/growth/skills/pr-retrospective/SKILL.md` Step 5 的 rule 草稿模板新增宣告欄位，使 agent 產出的建議文字自帶 gate link 或豁免宣告；並在 `.claude/rules/11-skill-authoring.md` 記錄宣告語法、合格目錄清單與 `--unified=0` 同 hunk 限制。驗證：在 `scripts/tests/test_pr_retrospective_evidence_gate_anchors.py` 新增 anchor 測試，斷言 SKILL.md 模板含宣告欄位。
- [x] 7.2 確認 plugin 內容改動依專案慣例走 PR 並以 `scripts/sync-plugin-versions.sh` 做 lockstep 版本調整，不自行執行 `make release`。驗證：兩處 `package.json` 與 `.claude-plugin/plugin.json` 版本一致（`git diff` 檢視）。

## 8. 收尾驗證

- [x] 8.1 `git add` 全部新檔後執行 `make ci`（untracked 新檔會被 hook 略過），並以 `git diff --name-only` 確認 formatter 沒有留下未提交改寫。驗證：`make ci` 綠燈輸出。
- [x] 8.2 以 `python3 scripts/lint_rule_evidence.py --base origin/main --head HEAD` 對本分支跑 range 模式：不得因既有未動內容新增 warn 或 error，且本 change 自己新增的 rule 11 section 必須帶有效宣告。驗證：輸出為 `[OK]` 且 warn 數與 `origin/main` 基準相同。
- [x] 8.3 確認常駐面淨增為零：`git diff origin/main -- .claude/rules/01-language-and-tone.md .claude/rules/03-security.md .claude/rules/13-bash-anti-patterns.md .claude/rules/15-irreversible-operations.md .claude/rules/16-allowlist-hygiene.md` 輸出為空。驗證：該指令無輸出。
- [x] 8.4 前置依賴檢查：確認 `add-retro-evidence-gate` 已 archive（`spectra list` 不再列出，且 `openspec/specs/retro-evidence-gate/` 存在）；若尚未，於 PR 描述註明合併順序。驗證：`spectra list` 輸出貼進 PR 描述。

## 9. 既有 rule 檔缺宣告升為 error（人類裁決：不接受 warn 這個殘餘風險）

- [x] 9.1 缺宣告在既有 rule 檔新增 section 也是 error：新增 `bad_missing_declaration_existing_file.diff`，改寫原本斷言 warn 的測試為斷言 error，移除 `warn_rule_mechanization`（不留一個永遠回空清單的入口）。驗證：`test_missing_declaration_in_existing_file_is_error`、`test_missing_declaration_in_existing_file_exits_one`、`test_no_mechanization_warn_function_remains` 與新 fixture 的純函式 / `main()` 兩條路徑測試；先紅後綠。
- [x] 9.2 單點突變 E：把缺宣告的報告改回「只有新檔才報」，確認上述測試轉紅後以反向替換還原。驗證：紅燈 7 個，anchor 命中斷言。
- [x] 9.3 同步 proposal、design、spec、rule 11 與 `pr-retrospective` SKILL.md 的敘述，並在 `git add` 後重跑 `make ci`。驗證：`make ci` 綠燈，且 `grep` 不再有任何文件宣稱既有檔缺宣告只 warn。
