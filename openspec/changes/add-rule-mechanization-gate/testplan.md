# add-rule-mechanization-gate — Test Plan

trace: enforced

這份 testplan 是**補寫**的（retro-fit）：測試先於本檔存在（本 change 以 TDD 先紅後綠實作，紅燈與突變證據在 PR #528 本文），此處把已存在的測試綁回 spec scenario，不是事前設計。補寫時盤點出 spec 有 7 個 scenario 沒有專屬測試（含「宣告在 heading 的 hunk 之外」完全沒被測過），已補上；另有 2 個 scenario 原本不在 spec（兩個執行點、mnemonicPrefix），因測試早已存在而補進 spec。PR #528 的 mob review 之後再補 16 個 TC（RMG-DT-026 至 RMG-EP-041），涵蓋引號路徑、使用者 git 設定、copy／binary／空檔、gate 連結的資料來源（index／head）、fence 與改標題的 section 切法，以及先前未被釘死的邊界；其中 git 輸出相關者一律用真實 git 暫存 repo，不手寫 diff。`/pr-cycle-deep` Round 2 的四個 Critical（既有檔 binary、fence 狀態滑移、刪除 fence 內 heading 的改標題豁免、intent-to-add 的 gate）促成「從完整 post-image 計算」的重設計，再補 9 個 TC（RMG-DT-042 至 RMG-DT-050，共 25 個），測試放在新檔 `scripts/tests/test_lint_rule_postimage.py`，全部用 hermetic 的真實 git（autouse fixture 關掉全域與系統設定）。
測試邊界為 `scripts/lint_rule_evidence.py` 的公開介面（`check_rule_mechanization`、`check_rule_evidence`、`main`）與 committed fixture 目錄；不針對內部函式（`_parse_diff` 等）寫 TC，它們的測試是支撐性的，不在綁定範圍。

## Test Seams

| Seam | Public interface | Why here |
|------|------------------|----------|
| mechanization-check | scripts/lint_rule_evidence.py 的 check_rule_mechanization(diff_text, read_gate_file) | 宣告的判定規則（缺宣告、假宣告、連結資格、豁免理由、純 rename）都在這裡；以注入的假檔案系統構造負向案例，不碰真實檔案系統，不 mock 本 repo 模組 |
| lint-cli | scripts/lint_rule_evidence.py 的 main(argv, read_gate_file) | exit code 與 stderr 是 pre-commit 與 CI 實際依賴的契約；兩個執行點（staged、range）與 OSError 轉 exit 2 只能在這一層觀察 |
| evidence-check | scripts/lint_rule_evidence.py 的 check_rule_evidence(diff_text) 與 warn_rule_evidence(diff_text) | 證明宣告檢查與既有證據檢查互相獨立，且證據 lint 的既有行為不因本 change 改變 |
| fixture-corpus | scripts/tests/fixtures/rule_mechanization/ 的 committed diff | 正向對照本身的完整性：每個擋下形狀都有 fixture，注入錨點缺失時對照會失敗而不是空洞通過 |

## TC Table

| TC-ID | Kind | Seam | Scenario Slug | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|------|------|---------------|--------------|-----------|------|--------------|-------|-----------|-----------------|
| RMG-DT-001 | auto | mechanization-check | section-with-a-valid-gate-link-passes | 有效 gate link 的 section 無任何 finding | DT | High | 假檔案系統含目標檔 | 對 good fixture 跑純函式與 main | good_valid_link.diff、good_fence_and_table_examples_ignored.diff | 純函式回空清單，main exit 0 |
| RMG-DT-002 | auto | mechanization-check | section-without-a-declaration-is-reported | 既有檔新增 section 缺宣告被點名 | DT | High | 既有 rule 檔 diff | 新增 heading 與證據標記但無宣告 | 13-bash-anti-patterns.md 新增 Added Section | 錯誤清單非空且含該 heading |
| RMG-DT-003 | auto | mechanization-check | declaration-quoted-in-a-code-fence-does-not-count | code fence 內的宣告語法不算宣告 | EP | High | 宣告只出現在 fenced block | 新增含 fence 範例的 section | text fence 內的 gate 註解 | 仍被報告缺宣告 |
| RMG-DT-004 | auto | mechanization-check | two-declarations-in-one-section-are-rejected | 同 section 兩個宣告互相矛盾或重複 | DT | Medium | 既有 rule 檔 diff | 連結加豁免、連結加連結各一次 | 兩組宣告 | 兩組都回錯誤，訊息含宣告個數 |
| RMG-VL-005 | auto | mechanization-check | link-to-a-nonexistent-path-is-an-error | dangling link 為 error 並點名路徑 | EP | High | 目標路徑不存在 | 對 dangling fixture 跑 main，另對參數化路徑跑純函式 | scripts/does_not_exist.py、scripts/missing.py | exit 1，stderr 含該路徑 |
| RMG-VL-006 | auto | mechanization-check | link-to-another-rule-file-is-rejected | 連到 rule 檔被拒絕，理由是資格不是存在性 | EP | High | 假檔案系統含該 rule 檔 | 連結 13-bash-anti-patterns.md 與 17-shell-script-authoring.md | 存在但不合格的 rule 檔 | 錯誤訊息含 rule 檔與不算 gate |
| RMG-VL-007 | auto | mechanization-check | link-to-a-missing-symbol-is-an-error | symbol 不存在或只是前綴時為 error | EP | High | 目標檔存在 | 連結帶 no_such_fn 與只是前綴的 check_rule | scripts/lint_rule_evidence.py 加 symbol | 兩者皆報錯，訊息含 symbol |
| RMG-VL-008 | auto | mechanization-check | unknown-reason-is-rejected | 豁免 reason 不在封閉列舉 | EP | High | 說明夠長 | 豁免宣告 reason 為 other | reason other 加長說明 | 錯誤訊息含 other 與封閉列舉 |
| RMG-VL-009 | auto | mechanization-check | placeholder-explanation-is-rejected | 佔位或過短的說明被拒 | BVA | Medium | reason 合法 | 說明依序為佔位字樣、過短、空字串 | TBD、TODO、N/A、none、太短了、空字串 | 全部回錯誤 |
| RMG-DT-010 | auto | mechanization-check | complete-exemption-passes | 三個合法 reason 配完整說明通過 | EP | Medium | 說明至少 12 個非空白字元 | 三個 reason 各一次，另跑 good fixture | judgment、no-observable-signal、hook-cost | 無 finding |
| RMG-DT-011 | auto | lint-cli | new-rule-file-without-declarations-fails | 新 rule 檔缺宣告 exit 1 | DT | High | 新檔 fixture | main 讀 fixture | bad_missing_declaration_new_file.diff | exit 1 |
| RMG-DT-012 | auto | lint-cli | new-section-in-existing-rule-file-fails | 既有檔新增 section 缺宣告 exit 1，不再有 warn 層 | DT | High | 既有檔 diff 檔案 | main 讀 diff | 無宣告的新 section | exit 1 |
| RMG-DT-013 | auto | mechanization-check | declaration-outside-the-headings-hunk-is-reported-missing | 宣告在別的 hunk 時保守地報缺宣告 | DT | Medium | 兩個 hunk 的 diff | heading 在第一個 hunk，宣告在第二個 | Heading Above Existing Body | 純函式回錯誤，main exit 1 |
| RMG-DT-014 | auto | mechanization-check | rename-into-the-rules-directory-is-treated-as-new | 帶內容變更的 rename 進 rules 視為新檔 | EP | High | rename 且有 hunk | 內容含 section 但無宣告 | scripts/notes.md 改名為 renamed-in.md | 回錯誤 |
| RMG-DT-015 | auto | lint-cli | pure-rename-into-the-rules-directory-is-rejected | 純 rename 進 rules fail-closed | DT | High | 100% 相似度，無 hunk | 純函式、fixture、真實 git mv 的 staged 與 range 各跑一次 | bad_pure_rename_into_rules.diff 與真實 git mv | 回恰好一個錯誤，main exit 1 |
| RMG-DT-016 | auto | mechanization-check | pure-rename-that-stays-inside-the-rules-directory-is-not-flagged | 目錄內改名與無關 rename 不報 | EP | Medium | 三組純 rename | rules 內改名、移出 rules、與 rules 無關 | 三組路徑 | 皆無錯誤 |
| RMG-DT-017 | auto | lint-cli | new-rule-file-without-any-section-needs-a-file-level-declaration | 無 section 的新檔要檔案層級宣告 | DT | High | 只有 H1 的新檔 | 缺宣告跑 main；有檔案層級宣告跑純函式 | bad_new_file_no_sections.diff 與帶宣告的平面檔 | 缺宣告 exit 1，有宣告則無錯誤 |
| RMG-EG-018 | auto | mechanization-check | evidence-marker-does-not-satisfy-the-declaration | 證據標記不能代替宣告 | DT | High | section 有 Source PR 標記 | 不加宣告 | Source: PR #339 | 仍報缺宣告 |
| RMG-EG-019 | auto | evidence-check | declaration-does-not-satisfy-the-evidence-marker | 宣告不能代替證據標記 | DT | High | 新檔有有效宣告但無證據 | 同時跑兩個檢查 | 帶 gate link 的新檔 | 宣告檢查無錯，證據檢查仍有錯 |
| RMG-EG-020 | auto | evidence-check | pure-rename-is-reported-once-by-the-declaration-check | 純 rename 只由宣告檢查報一次 | DT | Medium | 純 rename 進 rules | 跑證據檢查與其 warn | 100% 相似度 rename | 證據檢查與 warn 皆為空，宣告檢查恰好一個錯誤 |
| RMG-EG-021 | auto | lint-cli | unverifiable-gate-link-exits-2 | 非不存在的 OSError 使 main exit 2 | EP | High | 讀檔函式 raise PermissionError | 注入會 raise 的讀檔函式；另測預設讀檔函式 | PermissionError | exit 2，stderr 含 FAIL，stdout 無 OK；預設讀檔函式不吞錯 |
| RMG-VL-022 | auto | fixture-corpus | injection-anchor-absent-fails-the-control | 注入錨點找不到時對照失敗而非空洞通過 | EP | High | 沒有二級標題的文字 | 對該文字注入 | 只有 H1 的文字 | raise LookupError |
| RMG-VL-023 | auto | fixture-corpus | each-blocking-shape-has-its-own-fixture | 每個擋下形狀各有 committed fixture | BVA | High | fixture 目錄 | 列舉 bad fixture 並與形狀集合比對 | 十五個形狀 | 集合完全相等，無缺漏無多餘 |
| RMG-DT-024 | auto | lint-cli | both-execution-points-run-the-declaration-check | staged 與 range 兩個執行點都跑宣告檢查 | DT | High | tmp git repo | 未宣告的新 rule 檔先 staged，再 commit 後跑 range | 28-staged.md 與 26-range.md | 兩個模式都 exit 1 |
| RMG-DT-025 | auto | lint-cli | staged-mode-survives-diff-mnemonicprefix | mnemonicPrefix 下 staged 模式仍有效 | DT | High | repo 內開啟 diff.mnemonicPrefix | staged 未宣告的新 rule 檔 | diff.mnemonicPrefix true | exit 1 而不是靜默通過 |
| RMG-DT-026 | auto | lint-cli | non-ascii-and-special-character-paths-are-checked | 非 ASCII 與特殊字元檔名不可讓整個檔案對兩個 lint 隱形 | DT | High | 暫存 git repo，檔名含 CJK、雙引號、tab | 未宣告的新檔 staged 與 range 各跑一次；CJK 純 rename 進 rules；git 預設引號的 diff 檔；解碼器單元；staged diff 不引號非 ASCII | 規則.md、a"b.md、tab 檔名、筆記.md | exit 1 且輸出真實檔名；同檔名補宣告後 exit 0；`-c core.quotePath=false` 拿掉時 staged diff 測試轉紅 |
| RMG-EG-027 | auto | lint-cli | undecodable-quoted-path-exits-2 | 格式錯誤的引號路徑大聲失敗而不是被略過 | EP | High | diff 檔含格式錯誤的引號路徑 | main 讀該 diff 檔；解碼器收三種壞輸入 | 未結尾引號、未知跳脫、不完整八進位 | exit 2、stderr 含 FAIL、stdout 無 OK；解碼器 raise ValueError（格式正確但非 UTF-8 的位元組改由 RMG-DT-049 保留並檢查） |
| RMG-DT-028 | auto | lint-cli | user-diff-configuration-cannot-hide-a-change | 使用者的 git 設定不可讓 staged 模式變成 no-op | DT | High | repo 設定 color.ui=always、diff.external 或 textconv | 先斷言未加旗標的 git diff 確實被改壞，再跑 main；最後換成宣告齊全的內容 | 三種設定各一 | 未宣告 exit 1，宣告齊全 exit 0（後者能擋住 textconv 把新檔變成空檔的誤擋） |
| RMG-DT-029 | auto | lint-cli | copy-into-the-rules-directory-is-rejected | copy 進 rules 不可變成看不到內容，也不可因 `diff.renames=copies` 而誤擋 | DT | High | diff.renames=copies，來源檔同時被修改 | 先斷言 git 真的輸出無 hunk 的 copy，再跑 main；另以真實 git copy fixture、rules 內 copy、rules 外 copy 跑純函式 | 宣告與未宣告各一；bad_copy_into_rules.diff | 未宣告 exit 1 且點名 section，宣告齊全 exit 0；hunk-less copy 回一個錯誤；rules 內 copy 也是新檔；移出 rules 不報 |
| RMG-DT-030 | auto | lint-cli | binary-new-rule-file-is-rejected | 含 NUL 的新 rule 檔被擋，證據 lint 行為不變 | DT | High | 暫存 git repo | staged 與 range 各一次；對照 rules 外的 binary | 31-bin.md 含 NUL | exit 1 且輸出含路徑與二進位；證據 lint 回空；rules 外不報 |
| RMG-DT-031 | auto | lint-cli | empty-new-rule-file-is-rejected | 空的新 rule 檔被擋，證據 lint 行為不變 | DT | High | 暫存 git repo | staged 與 range 各一次；對照 rules 外的空檔 | 32-empty.md | exit 1 且輸出含路徑與空；證據 lint 回空；rules 外不報 |
| RMG-DT-032 | auto | lint-cli | staged-mode-reads-gate-links-from-the-index | staged 模式的 gate 連結讀 index 不讀工作樹 | DT | High | 暫存 git repo，gate script 只在磁碟上 | 連結先指向未 stage 的 script，再 stage，再改工作樹內容、再刪除工作樹檔案 | scripts/new_gate.py::gate | 未 stage 時 exit 1 並點名路徑；stage 後 exit 0；工作樹改壞或刪除仍 exit 0 |
| RMG-DT-033 | auto | lint-cli | range-mode-reads-gate-links-from-the-head | range 模式的 gate 連結讀 `--head` 的樹 | DT | High | 暫存 git repo，checkout 在別的 commit | head 含 gate 而 checkout 不含；head 不含而 checkout 含 | 兩個分支各一 | 前者 exit 0，後者 exit 1 |
| RMG-DT-034 | auto | lint-cli | diff-file-mode-reads-gate-links-from-the-working-tree | diff 檔模式沒有 git 脈絡，讀工作樹 | DT | Medium | 暫存 repo 作為 REPO_ROOT | 同一個 diff 檔在 script 不存在與存在時各跑一次 | scripts/new_gate.py | 先 exit 1，後 exit 0 |
| RMG-EG-035 | auto | lint-cli | git-failure-while-reading-a-gate-exits-2 | 讀 gate 時 git 失敗、解不開的 revision、未合併的 index 都 exit 2 | EP | High | 暫存 git repo | 注入會 raise 的 git 呼叫；讀不存在的 revision；製造真實合併衝突後讀該檔 | 假的 OSError、全 0 的 SHA、衝突中的 scripts/g.py | main exit 2 且無 OK；reader 對後兩者 raise OSError |
| RMG-VL-036 | auto | mechanization-check | link-to-a-directory-is-treated-as-absent | 連到目錄或 glob 視為不存在，檔名含 glob 字元仍精確解析 | EP | Medium | 已 commit 的 scripts 目錄與 x[1].py | 對 index 與 HEAD 兩種來源各讀目錄、glob、不存在的檔、方括號檔名 | scripts/sub、scripts/*.py、scripts/x[1].py | 前三者 None，最後一個回內容 |
| RMG-EP-037 | auto | mechanization-check | heading-inside-a-code-fence-is-not-a-section | fence 內的 heading 不是 section | EP | High | 既有 rule 檔 diff | 新增一個已宣告 section，內含三種 fence 範例；另測 fence 關閉後的 heading 與 tilde fence 內的宣告 | backtick、tilde、四個 backtick 包三個 | 宣告檢查與證據 warn 皆為空；fence 之後的 heading 仍被點名；tilde fence 內的宣告不算 |
| RMG-DT-038 | auto | mechanization-check | retitled-heading-is-not-a-new-section | 改標題不是新 section，但成對才豁免 | DT | High | 含被移除行的 diff | 改標題；層級改變；多出一個新 heading；被移除的 heading 在別的 hunk；committed good fixture | 五組 diff | 改標題無錯誤；其餘三組各回一個點名的錯誤；fixture 經純函式與 main 皆通過 |
| RMG-DT-039 | auto | mechanization-check | every-section-in-a-hunk-is-checked | 同一個 hunk 的每個 section 各自檢查 | DT | High | 既有 rule 檔 diff | 先宣告後未宣告、先未宣告後宣告、兩個各自宣告；另跑 committed bad fixture | 兩個 section 的 hunk | 恰好一個錯誤且點名未宣告者；兩個皆宣告無錯誤；fixture 經純函式與 main 皆被擋 |
| RMG-BVA-040 | auto | mechanization-check | exemption-explanation-length-boundary | 說明長度下限是 12 個非空白字元 | BVA | Medium | reason 合法 | 11 個、含空白共 12 但非空白 11、前後空白墊長、12 個、12 個含空白 | abcdefghijk 等五組 | 前三組被擋，後兩組通過 |
| RMG-EP-041 | auto | mechanization-check | each-eligibility-condition-is-individually-enforced | 每個資格條件各自有一個只有它能擋的案例 | EP | Medium | 假檔案系統含這些「存在但不合格」的檔案 | 連結子目錄 SKILL.md、tasks 下非 tests 的檔案、含反斜線的路徑、只是後綴的 symbol | scripts/sub/SKILL.md 等四組 | 全部被拒；拿掉任一資格條件至少一列轉成通過 |
| RMG-DT-042 | auto | lint-cli | rule-file-containing-a-nul-byte-is-rejected | 既有 rule 檔含 NUL 被 git 判為 binary 時，新增的 section 不可隱形，宣告齊全也不能放行 | DT | High | 暫存 git repo，既有已宣告 rule 檔 | 加入 NUL 與未宣告 section；加入 NUL 與已宣告 section | 01-a.md 含 NUL 兩種 | 兩者皆 exit 1，第一個的 stderr 含 NUL |
| RMG-DT-043 | auto | lint-cli | a-binary-attribute-does-not-hide-or-falsely-block-a-rule-file | `.gitattributes` 的 binary / -diff 不可讓 rule 檔隱形，也不可誤擋合法內容；其他 binary 不被傾印 | DT | High | `.gitattributes` 標記 `.claude/rules/*.md` | 未宣告 section 與已宣告 section 各一次（兩種屬性）；另在 diff 內放真正的二進位檔 | binary、-diff 兩個屬性；assets/logo.bin | 未宣告 exit 1，已宣告 exit 0；rules 外的二進位檔 exit 0 |
| RMG-DT-044 | auto | lint-cli | fence-state-comes-from-the-whole-file-not-the-hunk | fence 狀態對整份檔案連續追蹤：舊的結尾 fence 被對齊進 hunk 時新 section 不消失；fence 內的 heading 不是 section | DT | High | 暫存 git repo，既有檔最後是 code block | 改最後一個 code block 並新增未宣告 section；同形狀已宣告；新檔 fence 內含 `## When to use` | 滑進 hunk 的 fence、fence 內的範例 heading | 未宣告 exit 1，宣告齊全 exit 0，fence 範例 exit 0 |
| RMG-DT-045 | auto | lint-cli | retitle-exemption-requires-an-identical-body-and-a-real-heading | 改標題豁免要求相同內文與真 heading | DT | High | 暫存 git repo，既有 legacy section 無宣告 | 只改標題；刪掉 fence 內的範例 heading 並新增未宣告 section；整段換掉內文 | `### Old Title`、fence 內的 `### Example` | 只改標題 exit 0；另兩者 exit 1，補宣告後 exit 0 |
| RMG-DT-046 | auto | lint-cli | intent-to-add-gate-is-not-an-existing-gate | staged 模式的 gate 讀 `git write-tree`，intent-to-add 與未追蹤皆為 dangling，合法空檔仍成立 | DT | High | 暫存 git repo | 同一個連結分別搭配 `git add`、`git add -N`、未追蹤、合法 staged 的空檔 | scripts/gate.py | add 與空檔 exit 0，intent 與未追蹤 exit 1 |
| RMG-DT-047 | auto | lint-cli | declaration-below-an-inserted-heading-counts-even-if-not-added | 完整 post-image 下，插在既有已宣告內文之上的 heading 不誤報 | DT | Medium | 既有 rule 檔含證據標記與宣告 | 在其上插入新 `##` heading | 80-z.md | exit 0 |
| RMG-DT-048 | auto | lint-cli | content-lines-that-look-like-diff-headers-are-content | 看起來像檔頭的內文行不吞掉後面的 heading，也不使 lint exit 2 | DT | High | 暫存 git repo | 新增 `++ note` 後接未宣告 section；移除 `-- "x" y`；把 `-- "x" y` 換成 `++ "x" y`（先斷言 git 真的輸出成對的假檔頭） | q.sql、90-h.md | 未宣告 exit 1；後兩者 exit 0 |
| RMG-DT-049 | auto | lint-cli | non-utf8-input-neither-crashes-nor-bypasses | 非 UTF-8 內容與檔名被檢查而不是崩潰或略過；訊息輸出不因 surrogate 崩潰 | EP | High | 暫存 git repo；非 UTF-8 檔名以 `hash-object` 加 `update-index` 放進 index；另有 diff 檔形式的引號路徑 | 暫存 `caf\xe9` 的無關檔；暫存 `.claude/rules/\xff\xfe.md` 無宣告；diff 檔含 `"b/\377\376.md"`；解碼器直接收 `\377` | 三種非 UTF-8 輸入 | 無關檔 exit 0；兩個未宣告的 rule 檔 exit 1 且無 UnicodeEncodeError；解碼器保留原位元組 |
| RMG-DT-050 | auto | lint-cli | range-mode-sees-the-same-post-image-as-staged-mode | range 模式讀 `--head` 的完整 post-image，與 staged 模式同一判定 | DT | High | 暫存 git repo，已 commit 的三個既有 rule 檔 | 一個 commit 同時含 NUL、滑進 hunk 的 fence、刪除 fence 內 heading 三種形狀，再各自獨立一次 | 三個形狀 | 合併與各自皆 exit 1 |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| section-with-a-valid-gate-link-passes | covered | RMG-DT-001 | Auto |
| section-without-a-declaration-is-reported | covered | RMG-DT-002 | Auto |
| declaration-quoted-in-a-code-fence-does-not-count | covered | RMG-DT-003 | Auto |
| two-declarations-in-one-section-are-rejected | covered | RMG-DT-004 | 補寫時新增的專屬測試 |
| link-to-a-nonexistent-path-is-an-error | covered | RMG-VL-005 | 補寫時新增的專屬測試，含 main 的 stderr 點名路徑 |
| link-to-another-rule-file-is-rejected | covered | RMG-VL-006 | 補寫時新增的專屬測試 |
| link-to-a-missing-symbol-is-an-error | covered | RMG-VL-007 | Auto |
| unknown-reason-is-rejected | covered | RMG-VL-008 | 補寫時新增的專屬測試 |
| placeholder-explanation-is-rejected | covered | RMG-VL-009 | Auto |
| complete-exemption-passes | covered | RMG-DT-010 | Auto |
| new-rule-file-without-declarations-fails | covered | RMG-DT-011 | 補寫時新增的專屬測試 |
| new-section-in-existing-rule-file-fails | covered | RMG-DT-012 | Auto |
| declaration-outside-the-headings-hunk-is-reported-missing | covered | RMG-DT-013 | 補寫時發現 spec 有寫卻從沒被測過，已補測試；重設計後只適用不帶整份檔案的 diff（`-U0` 的 diff 檔、合成 diff） |
| rename-into-the-rules-directory-is-treated-as-new | covered | RMG-DT-014 | Auto |
| pure-rename-into-the-rules-directory-is-rejected | covered | RMG-DT-015 | 含真實 git mv 的 staged 與 range |
| pure-rename-that-stays-inside-the-rules-directory-is-not-flagged | covered | RMG-DT-016 | Auto |
| new-rule-file-without-any-section-needs-a-file-level-declaration | covered | RMG-DT-017 | 補寫時新增 main 的負向專屬測試 |
| evidence-marker-does-not-satisfy-the-declaration | covered | RMG-EG-018 | Auto |
| declaration-does-not-satisfy-the-evidence-marker | covered | RMG-EG-019 | Auto |
| pure-rename-is-reported-once-by-the-declaration-check | covered | RMG-EG-020 | Auto |
| both-execution-points-run-the-declaration-check | covered | RMG-DT-024 | 補進 spec 的 scenario，測試早已存在 |
| staged-mode-survives-diff-mnemonicprefix | covered | RMG-DT-025 | 補進 spec 的 scenario，測試早已存在 |
| unverifiable-gate-link-exits-2 | covered | RMG-EG-021 | 原 scenario 名稱過時（repository root），已改名 |
| entry-point-short-circuit-turns-the-controls-red | manual | — | MV-001；需要對 production 入口做突變，不是 pytest 能在自己身上做的 |
| injection-anchor-absent-fails-the-control | covered | RMG-VL-022 | Auto |
| each-blocking-shape-has-its-own-fixture | covered | RMG-VL-023 | Auto |
| non-ascii-and-special-character-paths-are-checked | covered | RMG-DT-026 | 真實 git；PR #528 review 的 Critical |
| undecodable-quoted-path-exits-2 | covered | RMG-EG-027 | 行為已改：只有格式錯誤的引號 exit 2，非 UTF-8 位元組改為保留並檢查（RMG-DT-049） |
| user-diff-configuration-cannot-hide-a-change | covered | RMG-DT-028 | 三種設定各自單點突變驗證過 |
| copy-into-the-rules-directory-is-rejected | covered | RMG-DT-029 | 真實 git 的 copy 輸出 |
| binary-new-rule-file-is-rejected | covered | RMG-DT-030 | 真實 git |
| empty-new-rule-file-is-rejected | covered | RMG-DT-031 | 真實 git |
| staged-mode-reads-gate-links-from-the-index | covered | RMG-DT-032 | 真實 git；PR #528 review 的 Critical |
| range-mode-reads-gate-links-from-the-head | covered | RMG-DT-033 | 真實 git |
| diff-file-mode-reads-gate-links-from-the-working-tree | covered | RMG-DT-034 | 文件化的行為 |
| git-failure-while-reading-a-gate-exits-2 | covered | RMG-EG-035 | Auto |
| link-to-a-directory-is-treated-as-absent | covered | RMG-VL-036 | Auto |
| heading-inside-a-code-fence-is-not-a-section | covered | RMG-EP-037 | Auto |
| retitled-heading-is-not-a-new-section | covered | RMG-DT-038 | 含 committed good fixture |
| every-section-in-a-hunk-is-checked | covered | RMG-DT-039 | 含 committed bad fixture |
| exemption-explanation-length-boundary | covered | RMG-BVA-040 | Auto |
| each-eligibility-condition-is-individually-enforced | covered | RMG-EP-041 | Auto |
| rule-file-containing-a-nul-byte-is-rejected | covered | RMG-DT-042 | 真實 git；Round 2 Critical A |
| a-binary-attribute-does-not-hide-or-falsely-block-a-rule-file | covered | RMG-DT-043 | 真實 git；兩種屬性、含「不傾印其他 binary」對照 |
| fence-state-comes-from-the-whole-file-not-the-hunk | covered | RMG-DT-044 | 真實 git；Round 2 Critical B |
| retitle-exemption-requires-an-identical-body-and-a-real-heading | covered | RMG-DT-045 | 真實 git；Round 2 Critical C 與 deferred #534 第 3 項 |
| intent-to-add-gate-is-not-an-existing-gate | covered | RMG-DT-046 | 真實 git；Round 2 Critical D |
| declaration-below-an-inserted-heading-counts-even-if-not-added | covered | RMG-DT-047 | 完整 post-image 帶來的語意變化 |
| content-lines-that-look-like-diff-headers-are-content | covered | RMG-DT-048 | deferred #534 第 1 項 |
| non-utf8-input-neither-crashes-nor-bypasses | covered | RMG-DT-049 | deferred #534 第 4 項 |
| range-mode-sees-the-same-post-image-as-staged-mode | covered | RMG-DT-050 | 真實 git |

## Manual Verification

- [ ] MV-001 AC-9（scenario: entry-point-short-circuit-turns-the-controls-red）：把 main() 在讀 diff 之前改成 return 0，確認十五個 bad fixture 的 main() 測試轉紅，並以反向替換還原。已在實作期間做過（PR #528 本文的突變 A，21 個紅燈），human quick pass 仍待確認；它驗證的是對照本身有效，無法由會被突變的測試自己斷言。

## Missing Coverage

- 突變 A 到 J 的結果只以人工執行與 PR 本文記錄，沒有自動化進 CI：把「突變後測試必須轉紅」做成 CI gate 是另一個 change 的範圍。
- 連結目標與該 rule 是否真的相關，不在本 change 的驗證範圍（已接受的殘餘風險，追蹤於 issue #531）。
- 重設計新增行為的單點突變（NUL 檢查、`--text` 重讀、`write-tree` gate reader、fence 全檔追蹤、改標題內文比對、hunk 行數）已人工執行，7 個突變全被擊殺；同樣沒有自動化進 CI。
- `.claude/rules/` 子目錄內的 rule 檔對兩個 lint 都不可見（deferred #534 第 2 項）不在本次範圍。

## Redundant TCs

無。參數化的 fixture 測試（`test_bad_fixture_is_rejected_by_pure_function`、`test_bad_fixture_is_rejected_by_main_entry`）同時覆蓋十五個擋下形狀，但各 scenario 都另有專屬 TC，不算重複。

## Traceability Matrix

TC 與 scenario 的對應以 TC Table 及 pytest docstring 的 `tc:` / `spec:` 為唯一資料來源。
測試檔：scripts/tests/test_lint_rule_evidence.py、scripts/tests/test_lint_rule_postimage.py（完整 post-image 的真實 git 測試）；現有 pytest testpaths 已包含 scripts/tests。
支撐性測試（不綁 TC）：parser 的三個測試（純 rename 記錄、帶 hunk 的 rename 只算一個、鄰近檔案不被吞掉）、`scripts/tests/test_pr_retrospective_evidence_gate_anchors.py` 的文件與常數對照測試。
