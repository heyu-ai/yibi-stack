# add-weekly-review-rule-loads — Test Plan

trace: enforced

這份 testplan 是**補寫**的（retro-fit）：測試在實作之後寫成，不是 red-first。為了證明測試守得住行為，
實作完成後對 9 個單點各做一次 mutation，全數被下表的測試抓到（見 design.md「驗證」）。本檔把已存在的
測試綁回 spec scenario。

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

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| worktree-and-main-count-as-one-file | covered | HWR-DT-080, HWR-ST-026 | Auto |
| repeated-load-in-one-session | covered | HWR-ST-026 | 同 session 重載與跨檔重複事件 |
| user-level-file-inside-repo | covered | HWR-ST-026 | User 檔放在 repo 路徑底下，只能靠 type 排除 |
| sdk-session-without-instructions | covered | HWR-ST-026 | Auto |
| renamed-instructions-attachment | covered | HWR-DT-081 | Auto |
| sdk-only-window | covered | HWR-DT-081 | Auto |
| unreadable-or-truncated-transcript | covered | HWR-DT-082 | Auto |
| zero-load-rule-is-listed | covered | HWR-DT-083, HWR-ST-027 | Auto |
| incomplete-source-hides-table | covered | HWR-DT-083 | Auto |
| snapshot-before-this-change | covered | HWR-DT-083 | Auto |

## Missing Coverage

- 9 個單點 mutation 只以人工執行並記錄於 design.md，沒有自動化進 CI。
- 「transcript 格式只在部分 session 改變」不會被格式對照抓到，屬已接受的殘餘風險（見 PR #628 的 Review Contract）。

## Redundant TCs

- 無
