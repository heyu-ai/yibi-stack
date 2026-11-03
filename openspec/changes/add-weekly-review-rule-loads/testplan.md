# add-weekly-review-rule-loads — Test Plan

trace: enforced

HWR-DT-080..083 與 HWR-ST-026..027 是**補寫**的（retro-fit）：測試在實作之後寫成，不是 red-first，改以
mutation 證明守得住行為（見 design.md「驗證」）。HWR-DT-084..092 與 HWR-ST-028 是 PR #628 review 的回歸測試：
行為類 finding 先寫測試、確認在修正前的產品碼以斷言失敗，再修產品碼；HWR-DT-092 與 HWR-ST-028 守的是既有行為
（修正前即通過），以 mutation (a)、(b) 證明有效。

測試邊界為 `harness_review.py` 的公開介面 `repo_relative`、`collect_rule_loads`、`render_rule_loads` 與
CLI 入口 `main`；transcript 一律以 `tmp_path` 下的真實 jsonl 檔構造，不 mock 本 repo 的函式。

## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| path-normalization | harness_review.repo_relative(path, main_repo) | 主 checkout 與 worktree 合併計數、排除同前綴的別的 repo，都在這裡判定 |
| rule-load-collector | harness_review.collect_rule_loads(projects_dir, main_repo, since, rules) | 計數規則、分母、來源完整性與格式對照都在 collector 內；以真實檔案系統構造 transcript |
| rule-load-report | harness_review.render_rule_loads(snap) | 「0 次」與「量不到」的區分只在報告層看得到 |
| cli | harness_review.main(argv) 的 collect 與 report 子命令 | 確認 collector 接進快照、報告讀得到；只有端對端才能抓到漏接線 |

## TC Table

| TC-ID | Kind | Seam | Scenario Slug | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|------|------|---------------|--------------|-----------|------|--------------|-------|-----------|-----------------|
| HWR-DT-080 | auto | path-normalization | worktree-and-main-count-as-one-file | 主 checkout 與 worktree 路徑對到同一相對路徑，別的 repo 不算 | EP | High | tmp 下建 repo 目錄 | 對五種路徑呼叫 repo_relative | 主 checkout、worktree 內檔案、worktree 根目錄、同前綴的別的 repo、家目錄路徑 | 前兩者回 `.claude/rules/a.md`，其餘回 None |
| HWR-ST-026 | auto | rule-load-collector | worktree-and-main-count-as-one-file | 兩種 attachment 都計入，以 session 計，使用者層與觀察期外不計，依 entrypoint 分母 | DT | High | 主 checkout 與 worktree 各一份 transcript | 呼叫 collect_rule_loads | 重載、重複事件、位於 repo 底下的 User 檔、觀察期外事件、sdk-py session | 計數、分母與 entrypoint 表完全符合預期，來源完整 |
| HWR-DT-081 | auto | rule-load-collector | renamed-instructions-attachment | 格式漂移判為不完整，只有 SDK session 時不誤判 | DT | High | 四組 transcript | 健康、attachment 改名、缺必載 rule、只有 sdk-py | 四組 jsonl | 健康與只有 sdk-py 完整；改名與缺 rule 不完整且錯誤訊息點名原因 |
| HWR-DT-082 | auto | rule-load-collector | unreadable-or-truncated-transcript | 讀取失敗與壞資料使來源不完整 | EP | High | 四組輸入 | rules 不完整、截斷行、讀不到的檔、沒有 transcript | 各一 | 四者皆不完整；截斷前資料保留；沒有 transcript 不重複發 warning |
| HWR-DT-083 | auto | rule-load-report | zero-load-rule-is-listed | 0 次與已不存在的檔案都列出；不完整或舊快照只寫「量不到」 | DT | High | 手寫快照 | 完整、不完整、刪掉 rule_loads 各一次 | 含 0 次 rule 與已不存在 rule 的快照 | 表列正確；後兩者只有「量不到」且無表 |
| HWR-ST-027 | auto | cli | zero-load-rule-is-listed | collect 把 rule_loads 寫進快照，report 印出載入表 | ST | High | 真實 git repo 與 transcript | main collect 後 main report | 必載與 path-scoped rule 各一 | 快照來源完整；報告含該節與 0 次的 path-scoped rule |
| HWR-DT-084 | auto | rule-load-collector | session-started-before-window | 跨越觀察期起點的 session 整個算進來，佔比不超過 100% | BVA | High | 一份 transcript | 呼叫 collect_rule_loads 後 render | instructions 在起點前、nested_memory 在期內的 session；全部事件在起點前的 session | 分母 2、scoped 1 次、佔比 50%；期前 session 不計 |
| HWR-DT-085 | auto | rule-load-collector | newly-added-always-loaded-rule | 只有部分必載 rule 為 0 次不判為格式改變 | DT | High | 兩條必載 rule，只載入一條 | 呼叫 collect_rule_loads 後 render | cli session 載入 always.md | 來源完整、always_missing 為 new.md，報告列出 |
| HWR-DT-086 | auto | rule-load-collector | user-only-instructions-not-in-denominator | 只列使用者層檔案的 instructions 不算有載入專案指令 | EP | High | 兩個 session | 呼叫 collect_rule_loads | 只有 User 檔的 instructions 加 nested_memory；正常 session | 分母 1、scoped 不計、excluded_sessions 1 |
| HWR-DT-087 | auto | rule-load-collector | rule-in-rules-subdirectory | rules 子目錄內的 rule 照樣計數並標明不在清單 | EP | Medium | 一個 session | 呼叫 collect_rule_loads 後 render | nested_memory 載入 `.claude/rules/sub/deep.md` | 計 1 次，載入範圍欄標「不在 collect_rules 清單」 |
| HWR-DT-088 | auto | rule-load-collector | no-events-in-window | 觀察期內有時間戳的事件不足時來源不完整 | BVA | High | 四份 transcript | 呼叫 collect_rule_loads | 沒有 timestamp、全部在起點前、期內 2 筆、期內 3 筆 | 前三者不完整並寫出筆數；3 筆完整 |
| HWR-DT-089 | auto | rule-load-report | nested-memory-drift-shows-unmeasured | nested_memory 漂移時 path-scoped 次數顯示量不到 | DT | High | 三組 transcript | 呼叫 collect_rule_loads 後 render | nested_memory 改名且 3 個 session、正常且 3 個、改名且 2 個 | 第一組量不到並說明；第二組 3 次 100%；第三組照常 0 次 |
| HWR-DT-090 | auto | rule-load-collector | malformed-attachment-shape | attachment 形狀不符時來源不完整 | EP | High | 健康 session 加一筆壞 attachment | 呼叫 collect_rule_loads | path 是物件、files 是物件 | 兩者皆不完整，錯誤寫出形狀不符 |
| HWR-DT-091 | auto | rule-load-collector | worktree-name-with-slash | 名稱含 / 的 worktree 正確正規化 | EP | High | worktree `feat/x` 的 transcript | 呼叫 collect_rule_loads | rule、根目錄 CLAUDE.md、docs/CLAUDE.md | rule 計入；CLAUDE.md 與 docs/CLAUDE.md 各 1；沒有 x/CLAUDE.md |
| HWR-DT-092 | auto | rule-load-report | render-without-project-instruction-sessions | 沒有 session 載入專案指令時不除以零 | BVA | Medium | 手寫快照 | 呼叫 render_rule_loads | sessions_with_instructions 為 0、一條必載 rule | 該列為 0 次、佔比 `-` |
| HWR-ST-028 | auto | cli | worktree-and-main-count-as-one-file | 從 git worktree 執行 collect 時讀主 repo 的 transcript | ST | High | 真實 git repo 與 worktree | 在 worktree 執行 main collect | transcript 放在主 repo slug 下 | 來源完整、always.md 計 1 次 |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| worktree-and-main-count-as-one-file | covered | HWR-DT-080, HWR-ST-026, HWR-ST-028 | ST-028 從 git worktree 執行 |
| worktree-name-with-slash | covered | HWR-DT-091 | Auto |
| rule-in-rules-subdirectory | covered | HWR-DT-087 | Auto |
| session-started-before-window | covered | HWR-DT-084 | Auto |
| repeated-load-in-one-session | covered | HWR-ST-026 | 同 session 重載與跨檔重複事件 |
| user-level-file-inside-repo | covered | HWR-ST-026 | User 檔放在 repo 路徑底下，只能靠 type 排除 |
| sdk-session-without-instructions | covered | HWR-ST-026 | Auto |
| user-only-instructions-not-in-denominator | covered | HWR-DT-086 | Auto |
| renamed-instructions-attachment | covered | HWR-DT-081 | Auto |
| newly-added-always-loaded-rule | covered | HWR-DT-085 | Auto |
| sdk-only-window | covered | HWR-DT-081 | Auto |
| unreadable-or-truncated-transcript | covered | HWR-DT-082 | 含非物件的行與目錄列不出來 |
| no-events-in-window | covered | HWR-DT-088 | Auto |
| malformed-attachment-shape | covered | HWR-DT-090 | Auto |
| zero-load-rule-is-listed | covered | HWR-DT-083, HWR-ST-027 | Auto |
| incomplete-source-hides-table | covered | HWR-DT-083 | Auto |
| snapshot-before-this-change | covered | HWR-DT-083 | Auto |
| nested-memory-drift-shows-unmeasured | covered | HWR-DT-089 | Auto |
| render-without-project-instruction-sessions | covered | HWR-DT-092 | Auto |

## Missing Coverage

- mutation 只以人工或一次性腳本執行並記錄於 design.md「驗證」，沒有自動化進 CI。
- `entrypoint` 欄位本身消失或改值時格式對照靜默失效，只有報告的 `(unknown)` 列可見（PR #628 review 列為不修的 NIT）。
- 「transcript 格式只在部分 session 改變」不會被格式對照抓到，屬已接受的殘餘風險（見 PR #628 的 Review Contract）。

## Redundant TCs

- 無
