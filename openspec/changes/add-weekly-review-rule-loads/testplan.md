# add-weekly-review-rule-loads — Test Plan

trace: enforced

HWR-DT-080..083 與 HWR-ST-026..027 是**補寫**的（retro-fit）：測試在實作之後寫成，不是 red-first，改以
mutation 確認守得住行為（見 design.md「驗證」）。HWR-DT-084..092 與 HWR-ST-028 是 PR #628 review 的回歸測試：
行為類 finding 先寫測試、確認在修正前的產品碼以斷言失敗，再修產品碼；HWR-DT-092 與 HWR-ST-028 守的是既有行為
（修正前即通過），以 mutation 確認有效。

HWR-DT-093..102 與 HWR-ST-029..030 是 PR #628 review 第 2 輪（R2-1..R2-9）重新設計後的回歸測試（紅燈行見
tasks.md 第 6 節）。

PR #628 的完整 diff 重審（第 2 輪之後重新開始的 R1）後 owner 裁決縮小宣稱（design.md D7）：拿掉所有格式漂移推論與 worktree 根目錄推論，改以
表頭原始計數交給人判讀。這一輪改寫了 HWR-ST-026、HWR-DT-081、082、083、085、087、089、096、097、099、100、101、
102 與 HWR-ST-029，新增 HWR-DT-107..110 與 HWR-ST-031..032，刪除 HWR-DT-098 與 HWR-DT-103..106（行為已拿掉，
新行為由 HWR-DT-081、089、101 守住）。改寫與新增的測試先在修正前的產品碼執行，紅燈行見 tasks.md 第 7 節；
HWR-DT-107 與 HWR-ST-032 守的是修正前就成立的行為（修正前即通過），以 design.md「驗證」第 6 點的 mutation (b)、(f)
確認有效。

測試邊界為 `harness_review.py` 的公開介面 `resolve_repo_path`、`collect_worktree_roots`、`collect_rule_loads`、
`collect_transcript_blocks`、`render_rule_loads` 與 CLI 入口 `main`；transcript 一律以 `tmp_path` 下的真實 jsonl
檔構造。替身只有兩個：HWR-DT-102 把外部邊界 `run_cmd` 換成失敗的 git；HWR-ST-031 在檔案系統層包住
`pathlib.Path.open`，在第二次開同一個 transcript 前追加一行被截斷的紀錄，重現兩次讀檔之間的落差。

## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| path-normalization | harness_review.resolve_repo_path(path, main_repo, worktree_roots) | 主 checkout 與 worktree 合併計數、最長的已知 worktree 名稱、對不上的 worktree 路徑、排除同前綴的別的 repo，都在這裡判定 |
| worktree-roots | harness_review.collect_worktree_roots(main_repo) | worktree 名稱只取自 git worktree list 與 `.claude/worktrees/` 第一層，以及兩者的失敗處理 |
| rule-load-collector | harness_review.collect_rule_loads(projects_dir, main_repo, rules, *, since, now, worktree_roots, worktree_root_errors) | 計數規則、分母、原始計數與來源完整性都在 collector 內；以真實檔案系統構造 transcript，worktree 名稱由測試注入 |
| rule-load-report | harness_review.render_rule_loads(snap) | 表頭原始計數、「注意」一行、「0 次」與「量不到」的區分只在報告層看得到 |
| cli | harness_review.main(argv) 的 collect 與 report 子命令 | 確認 collector 接進快照、warnings 含所有不完整原因、報告讀得到；只有端對端才能抓到漏接線 |

## TC Table

| TC-ID | Kind | Seam | Scenario Slug | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|------|------|---------------|--------------|-----------|------|--------------|-------|-----------|-----------------|
| HWR-DT-080 | auto | path-normalization | worktree-and-main-count-as-one-file | 主 checkout 與已知 worktree 的路徑對到同一相對路徑，別的 repo 不算 | EP | High | tmp 下建 repo 目錄，已知名稱 feat | 對五種路徑呼叫 resolve_repo_path | 主 checkout、worktree 內檔案、worktree 根目錄、同前綴的別的 repo、家目錄路徑 | 前兩者回 `.claude/rules/a.md`，其餘回 None，且都不是對不上的 worktree 路徑 |
| HWR-ST-026 | auto | rule-load-collector | worktree-and-main-count-as-one-file | 兩種 attachment 都計入，以 session 計，使用者層與觀察期外不計，依 entrypoint 分母，原始計數去重 | DT | High | 主 checkout 與 worktree 各一份 transcript | 呼叫 collect_rule_loads | 重載、重複事件、位於 repo 底下的 User 檔、觀察期外事件、sdk-py session | 計數、分母與 entrypoint 表完全符合預期，instructions_events 3、nested_memory_events 3，來源完整 |
| HWR-DT-081 | auto | rule-load-collector | renamed-instructions-attachment-stays-complete | 不以載入次數推論格式漂移；instructions 事件為 0 時報告加「注意」 | DT | High | 四組 transcript | 健康、attachment 改名、instructions 沒有 rules 路徑、只有 sdk-py | 四組 jsonl | 四組都完整且沒有 warning；改名組 instructions_events 0 並有「注意」；缺 rule 組 always_missing 列出；只有 sdk-py 組有「注意」 |
| HWR-DT-082 | auto | rule-load-collector | unreadable-or-truncated-transcript | 讀取失敗與壞資料使來源不完整，每個原因都回傳成 warning | EP | High | 六組輸入 | rules 不完整、截斷行、非物件的行、目錄列不出來、讀不到的檔、沒有 transcript | 各一 | 全部不完整，warnings 等於 source.errors；截斷前資料保留 |
| HWR-DT-083 | auto | rule-load-report | raw-counters-in-header | 表頭的原始計數與固定註明；0 次與不在清單的檔案都列出；不完整時直接列出原因；舊快照另寫 | DT | High | 手寫快照 | 完整、always_missing 為空、不完整（兩個原因）、刪掉 rule_loads 各一次 | 含 0 次 rule 與不在清單 rule 的快照 | 表頭含所有計數與固定句；不完整時列出兩個原因、沒有計數與表、沒有「見上方」 |
| HWR-ST-027 | auto | cli | zero-load-rule-is-listed | collect 把 rule_loads 寫進快照，report 印出載入表 | ST | High | 真實 git repo 與 transcript | main collect 後 main report | 必載與 path-scoped rule 各一 | 快照來源完整；報告含該節與 0 次的 path-scoped rule |
| HWR-DT-084 | auto | rule-load-collector | session-started-before-window | 跨越觀察期起點的 session 整個算進來，佔比不超過 100% | BVA | High | 一份 transcript | 呼叫 collect_rule_loads 後 render | instructions 在起點前、nested_memory 在期內的 session；全部事件在起點前的 session | 分母 2、scoped 1 次、佔比 50%；期前 session 不計 |
| HWR-DT-085 | auto | rule-load-collector | newly-added-always-loaded-rule | 必載 rule 為 0 次只列進 always_missing | DT | High | 兩條必載 rule，只載入一條 | 呼叫 collect_rule_loads 後 render | cli session 載入 always.md | 來源完整、always_missing 為 new.md，報告表頭列出 |
| HWR-DT-086 | auto | rule-load-collector | user-only-instructions-not-in-denominator | 只列使用者層檔案的 instructions 不算有載入專案指令 | EP | High | 兩個 session | 呼叫 collect_rule_loads | 只有 User 檔的 instructions 加 nested_memory；正常 session | 分母 1、scoped 不計、excluded_sessions 1 |
| HWR-DT-087 | auto | rule-load-collector | rule-in-rules-subdirectory | rules 子目錄內的 rule 照樣計數並標明不在清單 | EP | Medium | 一個 session | 呼叫 collect_rule_loads 後 render | nested_memory 載入 `.claude/rules/sub/deep.md` | 計 1 次，載入範圍欄標「不在 collect_rules 清單：可能已刪除、位於 rules 子目錄，或屬於子專案」 |
| HWR-DT-088 | auto | rule-load-collector | no-events-in-window | 觀察期內有時間戳的事件不足時來源不完整 | BVA | High | 四份 transcript | 呼叫 collect_rule_loads | 沒有 timestamp、全部在起點前、期內 2 筆、期內 3 筆 | 前三者不完整並寫出筆數；3 筆完整 |
| HWR-DT-089 | auto | rule-load-collector | nested-drift-stays-complete | nested_memory 改名時不推論，計數照實顯示 | DT | High | 兩組 transcript，各 3 個有載入專案指令的 session | 呼叫 collect_rule_loads 後 render | nested_memory 改名；正常 | 改名組完整、scoped 0 次 0%、表頭 nested 0 筆、沒有「量不到」；正常組 3 次 100% |
| HWR-DT-090 | auto | rule-load-collector | malformed-attachment-shape | attachment 形狀不符時來源不完整 | EP | High | 健康 session 加一筆壞 attachment | 呼叫 collect_rule_loads | path 是物件、files 是物件 | 兩者皆不完整，warning 寫出形狀不符且等於 source.errors |
| HWR-DT-091 | auto | rule-load-collector | worktree-name-with-slash | 名稱含 / 的已知 worktree 正確正規化 | EP | High | worktree `feat/x` 的 transcript | 呼叫 collect_rule_loads | rule、根目錄 CLAUDE.md、docs/CLAUDE.md | rule 計入；CLAUDE.md 與 docs/CLAUDE.md 各 1；沒有 x/CLAUDE.md |
| HWR-DT-092 | auto | rule-load-report | render-without-project-instruction-sessions | 沒有 session 載入專案指令時不除以零 | BVA | Medium | 手寫快照 | 呼叫 render_rule_loads | sessions_with_instructions 為 0、一條必載 rule | 該列為 0 次、佔比 `-` |
| HWR-ST-028 | auto | cli | worktree-and-main-count-as-one-file | 從 git worktree 執行 collect 時讀主 repo 的 transcript | ST | High | 真實 git repo 與 worktree | 在 worktree 執行 main collect | transcript 放在主 repo slug 下 | 來源完整、always.md 計 1 次 |
| HWR-DT-093 | auto | rule-load-collector | window-has-an-end | 觀察期有結束時間 | BVA | High | 兩份 transcript | 呼叫 collect_rule_loads | 期內 session 加一個全在 now 之後的 session；只有 now 之後的事件 | 第一份只計 1 個 session；第二份期內 0 筆、不完整 |
| HWR-DT-094 | auto | rule-load-collector | attachment-shape-variants-are-incomplete | attachment 形狀的各種變形都判為不完整 | EP | High | 健康 session 加一筆壞 attachment | 對 8 種變形各呼叫一次 | attachment 為字串或清單；files 缺漏、{}、""、物件；項目非物件；項目 path 非字串 | 對照完整；8 種皆不完整且 warning 寫出形狀不符 |
| HWR-DT-095 | auto | rule-load-collector | out-of-repo-instructions-not-in-denominator | 只列 repo 外 Project 檔的 instructions 不算有載入專案指令 | EP | High | 兩個 session | 呼叫 collect_rule_loads | instructions 只有 `/elsewhere/CLAUDE.md` 加 nested_memory；正常 session | 分母 1、scoped 不計、excluded_sessions 1 |
| HWR-DT-096 | auto | rule-load-collector | instructions-events-count-every-attachment | instructions_events 也數只列 User 檔的 attachment | EP | Medium | 一個 cli session、沒有必載 rule | 呼叫 collect_rule_loads 後 render | instructions 只有 User 檔 | 來源完整、instructions_events 1、沒有「注意」 |
| HWR-DT-097 | auto | rule-load-collector | unreadable-or-truncated-transcript | 讀檔、壞行、列目錄、找不到 transcript 的 warning 與 collect_transcript_blocks 逐位元相同 | EP | Medium | 四組輸入 | 對同一份資料呼叫兩個 collector | 截斷行；讀不到的檔；列不出來的子目錄；沒有 transcript | warnings 等於 source.errors，且每一筆都在 collect_transcript_blocks 的回傳裡 |
| HWR-ST-029 | auto | cli | unreadable-or-truncated-transcript | cmd_collect 的快照 warnings 含 rule_loads 的所有原因 | ST | High | 真實 git repo、一份讀不到的 transcript | main collect | 兩份 transcript，一份 chmod 000 | rule_loads 不完整、快照 warnings 含「讀取失敗」且包含 source.errors 的每一筆 |
| HWR-DT-099 | auto | rule-load-collector | unresolved-nested-paths-are-counted | nested_memory 路徑形狀整批改變時照實計數 | EP | High | 三組 transcript，各 3 個有載入專案指令的 session | 呼叫 collect_rule_loads 後 render | nested path 為相對路徑、file:// URI、只有 repo 外 | 來源完整、nested_memory_events 0、nested_unresolved_events 等於事件數、scoped 0 次、表頭列出兩個計數 |
| HWR-DT-100 | auto | path-normalization | authoritative-worktree-roots | 以注入的 worktree 名稱正規化；子專案 rule 保留自己的路徑 | EP | High | 主 checkout 與 worktree wt 的 transcript | 呼叫 resolve_repo_path 與 collect_rule_loads | 名稱 feat 與 feat/x 並存；worktree 根目錄本身；mobile/ 子專案的 rule 與 CLAUDE.md | feat/x/CLAUDE.md 對到 CLAUDE.md；mobile/.claude/rules/m.md 與 mobile/CLAUDE.md 各 2 次 |
| HWR-DT-101 | auto | rule-load-collector | deleted-worktree-counts-as-unresolved | 已刪除的 worktree 不推論根目錄，路徑只計入 unresolved_worktree_paths | EP | High | 已刪除的 feat/x 的 transcript，寫在目錄名稱對得上的 `--claude-worktrees-feat-x`，不注入名稱 | 呼叫 resolve_repo_path、collect_rule_loads 後 render | rule、根目錄 CLAUDE.md、docs/CLAUDE.md | rules 與 memory_files 皆空、分母 0、nested_unresolved_events 0、unresolved_worktree_paths 3，報告表頭列出 |
| HWR-DT-102 | auto | worktree-roots | first-level-worktree-listing | worktree 名稱只看 git 與第一層目錄；git 失敗時來源不完整 | DT | High | 真實 git repo | 呼叫 collect_worktree_roots，再把結果傳進 collect_rule_loads | 沒有 worktrees 目錄；outer 與 outer/inner 兩個 git worktree；git 不認得的 walked；沒有 .git 的 plain；巢狀 old/vendor/lib/.git；.cache/.git；檔案 stray.txt；git 失敗 | 沒有目錄時無錯誤；名稱為 outer、outer/inner、walked；git 失敗時有錯誤、來源不完整並回傳 warning |
| HWR-DT-107 | auto | worktree-roots | roots-lookup-failure-is-incomplete | `.claude/worktrees/` 列不出來時記錯誤 | EP | High | 真實 git repo，`.claude/worktrees/walked/.git` | 可讀與 chmod 000 各呼叫一次 collect_worktree_roots | walked | 可讀時名稱 walked 且無錯誤；列不出來時錯誤含目錄路徑與「無法列出」 |
| HWR-DT-108 | auto | rule-load-collector | out-of-window-shape-errors-ignored | 觀察期外 session 的形狀錯誤不檢查 | DT | High | 健康 session 加一個壞 attachment | 呼叫 collect_rule_loads 兩次 | 壞事件的 session 全在期前；壞事件在期前但同 session 期內有事件 | 第一組完整且 sessions 1；第二組不完整、warning 寫出形狀不符 |
| HWR-DT-109 | auto | rule-load-collector | repeated-load-in-one-session | 沒有 uuid 的事件不跨 session 撞號 | EP | Medium | 同一檔案兩個 session | 呼叫 collect_rule_loads | 兩個 session 各有沒有 uuid 的 instructions 與 nested_memory | instructions_events 2、nested_memory_events 2、兩條 rule 各 2 |
| HWR-DT-110 | auto | rule-load-report | no-instructions-events-notice | 「注意」一行的出現條件 | BVA | Medium | 手寫快照 | 呼叫 render_rule_loads 四次 | instructions_events 0 與 1；sessions 0；沒有 instructions_events 欄位 | 只有第一個出現「注意」；舊快照的計數顯示「未記錄」 |
| HWR-ST-030 | auto | cli | authoritative-worktree-roots | 端對端：cmd_collect 取得真實 worktree 名稱 | ST | High | 真實 git repo 與 `.claude/worktrees/feat/x` worktree | main collect | 該 worktree 的 rule、根目錄 CLAUDE.md、docs/CLAUDE.md | CLAUDE.md 與 docs/CLAUDE.md 各 1、unresolved_worktree_paths 0 |
| HWR-ST-031 | auto | cli | unreadable-or-truncated-transcript | 兩次讀 transcript 之間的落差仍發 warning | ST | High | 真實 git repo 與一份 transcript；檔案層包住 Path.open | main collect | 第二次開檔前追加一行被截斷的紀錄 | collect_transcript_blocks 來源完整；rule_loads 不完整；快照 warnings 含其原因；exit 3 |
| HWR-ST-032 | auto | cli | roots-lookup-failure-is-incomplete | 只有 rule_loads 會發現的原因也進快照 warnings | ST | High | 真實 git repo、chmod 000 的 `.claude/worktrees/`、期內形狀不符的事件 | main collect | 一份 transcript | rule_loads 的形狀不符與列目錄錯誤都在快照 warnings |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| worktree-and-main-count-as-one-file | covered | HWR-DT-080, HWR-ST-026, HWR-ST-028 | ST-028 從 git worktree 執行 |
| rule-in-rules-subdirectory | covered | HWR-DT-087 | Auto |
| session-started-before-window | covered | HWR-DT-084 | Auto |
| window-has-an-end | covered | HWR-DT-093 | Auto |
| repeated-load-in-one-session | covered | HWR-ST-026, HWR-DT-109 | 同 session 重載、跨檔重複事件、沒有 uuid 的事件 |
| user-level-file-inside-repo | covered | HWR-ST-026 | User 檔放在 repo 路徑底下，只能靠 type 排除 |
| authoritative-worktree-roots | covered | HWR-DT-100, HWR-DT-102, HWR-ST-030 | ST-030 以真實 git worktree 端對端 |
| worktree-name-with-slash | covered | HWR-DT-091 | Auto |
| subproject-rules-keep-their-path | covered | HWR-DT-100 | probe_a 的情境 |
| deleted-worktree-counts-as-unresolved | covered | HWR-DT-101 | transcript 目錄名稱刻意對得上，守「不以目錄名稱推回」 |
| first-level-worktree-listing | covered | HWR-DT-102 | 巢狀 .git、以 . 開頭的名稱、檔案 |
| roots-lookup-failure-is-incomplete | covered | HWR-DT-102, HWR-DT-107, HWR-ST-032 | git 失敗與列目錄失敗 |
| sdk-session-without-instructions | covered | HWR-ST-026 | Auto |
| user-only-instructions-not-in-denominator | covered | HWR-DT-086 | Auto |
| out-of-repo-instructions-not-in-denominator | covered | HWR-DT-095 | Auto |
| instructions-events-count-every-attachment | covered | HWR-DT-096 | Auto |
| unresolved-nested-paths-are-counted | covered | HWR-DT-099 | probe.out 的三組 |
| renamed-instructions-attachment-stays-complete | covered | HWR-DT-081 | Auto |
| nested-drift-stays-complete | covered | HWR-DT-089 | Auto |
| newly-added-always-loaded-rule | covered | HWR-DT-085 | Auto |
| sdk-only-window | covered | HWR-DT-081 | Auto |
| unreadable-or-truncated-transcript | covered | HWR-DT-082, HWR-DT-097, HWR-ST-029, HWR-ST-031 | ST-031 重現兩次讀檔之間的落差 |
| no-events-in-window | covered | HWR-DT-088 | Auto |
| malformed-attachment-shape | covered | HWR-DT-090 | Auto |
| attachment-shape-variants-are-incomplete | covered | HWR-DT-094, HWR-ST-032 | 含 pr-test-analyzer N7、N8 |
| out-of-window-shape-errors-ignored | covered | HWR-DT-108 | PR #628 review F-1 |
| raw-counters-in-header | covered | HWR-DT-083 | Auto |
| no-instructions-events-notice | covered | HWR-DT-081, HWR-DT-110 | Auto |
| zero-load-rule-is-listed | covered | HWR-DT-083, HWR-ST-027 | Auto |
| incomplete-source-lists-reasons-inline | covered | HWR-DT-083 | Auto |
| snapshot-before-this-change | covered | HWR-DT-083 | Auto |
| render-without-project-instruction-sessions | covered | HWR-DT-092 | Auto |

## Missing Coverage

- mutation 只以一次性腳本執行並記錄於 design.md「驗證」，沒有自動化進 CI。
- 格式漂移不自動偵測（design.md D7）。測試只確認漂移時來源仍完整、原始計數照實列出；能不能從計數看出漂移，
  取決於人比對前一週，沒有測試能鎖住。
- 壞行與讀檔失敗找不到所屬 session，所以觀察期外的檔案有截斷行時，該節仍會量不到，直到檔案超出保留期；
  這是刻意的取捨（可能屬於觀察期內的 session），沒有反向測試。

## Redundant TCs

- 無
