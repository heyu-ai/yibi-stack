## Context

`scripts/lint_rule_evidence.py` 目前對 `.claude/rules/*.md` 只問「這個教訓有證據嗎」（證據標記：probe、incident PR、`Source: PR #NNN` 等）。它不問「這件事為什麼沒有被做成 gate」。`pr-retrospective` 的 Promotion Gate G1 負責問這題，但 G1 是 agent 自評的散文，沒有任何機械檢查確認它被誠實套用。

現有 lint 的結構可以直接重用：`_parse_diff` 把 unified diff 切成 per-file、per-hunk 的新增行；`_missing_evidence_in_chunk` 以「新增的 heading」為錨點，逐 hunk 判斷該 section 內有無標記；`_evidence_eligible_lines` 濾掉 table row 與 fenced code block；`_is_newly_protected` 處理 rename 進來的檔案；`main()` 回傳 exit code（0 通過、1 有 error、2 設定錯誤）。diff 以 `--unified=0` 產生，所以 section 內容只看得到「同一 hunk 內新增的行」。

約束：兩個前置事實不能被本 change 破壞。(1) 證據標記行為由未 archive 的 `add-retro-evidence-gate` 定義，本 change 不得改變它。(2) 該 change 的自我約束「always-loaded 面淨增為零」同樣適用於本 change：不在 01/03/13/15/16 新增文字。

## Goals / Non-Goals

**Goals:**

- 新增 rule section 必須帶可機械驗證的宣告：連結到一個真實存在的 gate，或從封閉列舉選一個無法機械化的理由。
- 假宣告（連結指向不存在或不合格的目標）與缺宣告分開處理：假宣告在所有層級都是 error。
- 每個被宣稱會擋下的壞輸入形狀，都有 committed fixture 作為正向對照，並經由 production 入口 `main()` 驗證。

**Non-Goals:**

- 不回溯補既有 section、不批次轉換既有 rule 為 gate。
- 不驗證被連結的 gate 是否真的涵蓋該 rule 的語意。這是已知殘留，由 `harness-weekly-review` 的觸發率量測承接，本 change 不處理。
- 不做 `/pr-review-cycle` 的 mutation check script，不自動產生 hook。
- 不改變證據標記的接受形式或其分層。

## Decisions

### 宣告語法使用 HTML 註解，與證據標記同形

宣告寫成 `<!-- gate: scripts/lint_rule_evidence.py::check_rule_evidence -->` 或 `<!-- gate: none (reason: judgment) — <說明> -->`。選 HTML 註解的原因：不影響 render、與既有 `<!-- verified: probe -->` 一致、且可用單一 regex 錨定。被否決：frontmatter 欄位（section 層級放不進 frontmatter，且 rule 檔 frontmatter 已被 `lint_rule_frontmatter.py` 管控 key 集合）；獨立 JSON 索引檔（宣告與內容分離，必然漂移）。

### 路徑驗證以注入的讀檔函式完成，純函式不碰檔案系統

`check_rule_mechanization(diff_text, read_gate_file)` 為純函式入口。`read_gate_file(path) -> str | None`：檔案存在回內容、不存在回 `None`、其他 OS 錯誤直接 raise `OSError`。測試以字典假實作注入；production 以 `REPO_ROOT` 為基準實作。這延續既有檔案「只對真實檔案斷言的 lint 無法測自己的失敗路徑」的設計：負向案例必須能用合成 diff 加假檔案系統構造。`main()` 把 `OSError` 轉成 exit 2 加 `[FAIL]`，不可吞成「連結有效」。

### 合格 gate 目錄為封閉清單且不含 rule 與 SKILL.md

合格集合：`scripts/`、`.claude/hooks/`、`.pre-commit-config.yaml`、`.github/workflows/`，以及 `scripts/` 與 `tasks/` 底下的 `tests/` 目錄。判斷以正規化後的相對路徑前綴比對，路徑含 `..` 或為絕對路徑一律拒絕（避免跳出 repo 的假連結）。`.claude/rules/*.md` 與任何 `SKILL.md` 明確不合格：rule 指向 rule 不是機械化。被否決：任意存在的檔案皆可（等於沒有把關）；只接受 `scripts/`（會排除 hook 與 CI，而這兩者正是最常見的機械化落點）。

### 缺宣告與假宣告在所有 rule 檔一律為 error

缺宣告與假宣告**都是 error，不分新檔或既有檔**。本 change 起草時，既有 rule 檔新增 section 缺宣告只 warn（沿用 evidence lint 的漸進原則，避免歷史 corpus 一次爆紅）；該殘餘風險經人類審視後**不被接受**，改為 error。歷史 corpus 不會爆紅，因為只掃「新增」的 section，既有 section 不回溯。假宣告（連結指向不存在或不合格目標、豁免理由不在列舉內、說明為佔位字樣、同 section 兩個宣告互相矛盾）本來就不降級：降為 warn 等於教人用亂填通過。被否決：維持既有檔 warn 並等 warn 出現率再收緊（起步期的 warn 在 pre-commit 與 CI 都不擋，等於這段期間新增的 section 沒有任何 gate）。代價：見 Risks 的同 hunk 限制。

### 豁免理由為三值封閉列舉

`judgment`（需要語意判斷，例如 reviewer prompt 是否內嵌未驗證因果假設）、`no-observable-signal`（工具邊界上沒有可偵測的訊號）、`hook-cost`（可偵測但 hook 成本高於效益，例如會封掉逃生路或需從 worktree 註冊）。無 `other`。說明文字至少 12 個非空白字元且不可為 `TBD` / `TODO` / `N/A` / `none`。被否決：開放自由文字（等於 catch-all，任何人隨手填一句即通過）。

### 宣告檢查與證據檢查各自獨立執行

兩者共用 `_parse_diff` 與 `_evidence_eligible_lines`，但判定互不替代：證據標記不滿足宣告，宣告也不滿足證據標記。實作為 `main()` 內並列的兩組呼叫；輸出**不合併**：證據 error 與宣告 error 各印成獨立的 `[FAIL] N 個 ...` 區塊（各附自己的修法提示），`[WARN]` 另行先輸出，任一組有 error 即 exit 1。已知限制：因 `--unified=0`，宣告必須與其 heading 位於同一個 hunk；heading 插入在既有內容之上、宣告落在未變動行時，會被誤判為缺宣告。此為可接受的保守誤報，記入 rule 11 的語法說明。

### 純 rename 進 rules 目錄一律 fail-closed

100% 相似度的 rename 在 git 輸出裡只有 `similarity index 100%` 與 `rename from/to`，沒有 `---` / `+++` / hunk（git 2.56.0 實測）。舊 parser 只在 `+++` 行建立檔案記錄，於是這種 rename 完全沒有記錄，證據與宣告兩個檢查都沒機會跑，整份檔案靜默通過。做法：parser 另外收 `rename from/to`，區塊結束（下一個 `diff --git` 或 EOF）時若沒出現過 `+++` 就建立 `pure_rename=True` 的記錄；機械化檢查對「進入 `.claude/rules/`」（來源不在該目錄）的純 rename 報 error，目錄內改名與無關的 rename 不報。證據檢查對純 rename 刻意略過，維持既有行為，也避免同一件事被兩個 lint 重複回報。被否決：讀工作樹或 `git show` 取內容（破壞純函式，staged 與 range 兩個執行點要各寫一套 IO）；維持殘留並記載（「看不到」等於「通過」，正是 gate 最不該有的形狀）。要求使用者在同一個 commit 補上證據標記與宣告，rename 加上這次改動就有 hunk，後續走一般檢查。

### 讀 diff 與讀 gate 的方式不受使用者環境影響（PR #528 mob review 之後）

mob review 以真實 git 重現了數個「lint 讀到的輸出形狀與手寫 fixture 不同」的缺口，共同根因是 lint 把 git 的輸出當成固定格式，而那份輸出其實由使用者的設定與檔案內容決定。處置：

- **引號路徑**：git 預設把非 ASCII 與特殊字元路徑輸出成 C-style 引號（`"b/\350\246\217.md"`），舊 parser 留著開頭的 `"`，路徑正則對不上，整個檔案靜默通過。`_run_git_diff` 加 `-c core.quotePath=false`，另有 `_unquote_c_path` 解碼仍會被引號的字元（tab、`"`、`\`），解不開（非 UTF-8、跳脫不完整）就 raise `ValueError`、`main()` 回 exit 2。兩層都要：只靠旗標，diff 檔模式（別處產生的 diff）與特殊字元仍會漏；只靠解碼，旗標拿掉也看不出來，所以各有測試釘住。
- **輸出形狀釘死**：`--no-color --no-ext-diff --no-textconv`（`color.ui=always`、`diff.external`、textconv 都會改寫輸出，使 `+## heading` 讀不到）與 `-M`（`diff.renames=copies` 會把「複製進 rules 且來源同時被修改」變成沒有 hunk 的 copy）。**被否決：`--no-renames`**，它會讓目錄內的純 rename 變成一個沒宣告的新檔，違反「目錄內改名不報錯」。
- **看不到內容一律 fail-closed**：純 rename 之外，沒有 hunk 的 copy、`Binary files ... differ`、空的新檔（只有 `new file mode` + `index`）同樣沒有可讀的內容。parser 以 `_BlockHeader` 收集每個區塊的標頭資訊，沒有 `+++` 時建立 `unseen` 記錄（四種原因）；進入 `.claude/rules/` 者報 error，copy 不看來源是否在 rules 內（目標是新檔）。證據 lint 對這四種維持原行為（略過）。
- **gate 連結對「將被 commit / 被審查的內容」驗證**：舊實作讀工作樹，所以只存在於磁碟、沒 stage 的 script 會讓 dangling link 通過，反過來已 stage 但磁碟上不在的有效連結會被誤擋。staged 模式讀 index（`git ls-files -z --stage`）、range 模式讀 `--head` 的樹（`git ls-tree -z`），兩者再 `git cat-file blob`；diff 檔模式沒有 git 脈絡，仍讀工作樹（文件化）。只有「路徑不存在」是答案，git 失敗、未合併的 index entry 一律 raise `OSError` 轉 exit 2。路徑精確比對（目錄與 glob 展開出的別的檔案都算不存在）。被否決：讓三種模式共用工作樹讀取（驗證的對象與被 commit 的內容脫鉤）；`git show :<path>`（無法分辨「不存在」與其他失敗，只能解析 stderr，而 git 的訊息有在地化）。實測 `--literal-pathspecs` 不改變任何輸出（git 的 pathspec 比對本來就先試字面相等），所以不加，由精確比對負責。

### section 的切法：fence 內不算、改標題不算、每個都要檢查

兩組檢查共用 `_sections_in_chunk`，因此下列規則同時作用於證據與宣告：

- **fence 狀態逐行追蹤**（`_FenceTracker`：``` 與 ~~~，關閉條件依 CommonMark，較長的外層 fence 不被內層提早結束）：fence 內的 `## ...` 是範例，不是 section。舊實作把它們當成 section，產生一個「宣告放哪都救不了」的錯誤。`_evidence_eligible_lines` 也改用同一個 tracker，使宣告在 `~~~` fence 內同樣不計。
- **改標題**：同一個 hunk 移除了同層級 heading 時，新增的 heading 視為改標題；每個被移除的 heading 只豁免一個同層級的新增 heading（一對一消耗），層級不同或沒有成對的移除仍算新 section。這維持「不回溯補既有 section」的 Non-goal。
- **Setext 與縮排 heading 刻意不支援**：`.markdownlint.yaml` 為 `default: true`，MD003（heading 風格一致）會先擋下 ATX 檔案裡的 setext heading，而 rule 檔全是 ATX；實作它只會增加一條從不被走到的路徑。理由記於 lint docstring、rule 11 與 spec，避免日後被當成漏洞重複回報。
- **每個 section 各自檢查**：同一個 hunk 的多個 section 都要檢查（過去沒有測試能分辨「只檢查第一個／最後一個」）。
- **移除 `_PLACEHOLDER_EXPLANATIONS`**：每個佔位字樣都短於 12 個字元，長度檢查已涵蓋；那份清單藏在長度檢查之後、永遠走不到。

### 正向對照 fixture 依形狀分開、含真實資料對照與入口短路驗證

`scripts/tests/fixtures/rule_mechanization/` 放十五個 `bad_*.diff`（新檔缺宣告、既有檔缺宣告、純 rename 進 rules、無 section 的新檔、dangling link、link 到 rule、缺 symbol、未知 reason、佔位說明、雙重宣告，以及 PR #528 review 之後新增的同 hunk 兩個 section、引號路徑的新檔、binary 新檔、空的新檔、沒有 hunk 的 copy；後四者為真實 git 輸出）與數個 `good_*.diff`（含一個改標題）。每個 bad fixture 以兩種路徑斷言被擋：純函式回傳非空，以及 `main([fixture_path])` 回傳非零。真實資料對照：測試在執行時複製 `.claude/rules/` 下一份真實 rule 檔，在斷言錨點存在之後注入未宣告 section，再產生 diff 餵給 lint；錨點找不到時測試失敗而非跳過。形狀刻意分散（新檔、既有檔、rename 進來），避免七個對照其實同構。另以突變驗證：把 `main()` 短路成回傳 0，確認 fixture 測試轉紅；每次突變只改一件事，還原用反向替換而非 `git checkout`。

### SKILL.md 與 rule 11 同步

`pr-retrospective` Step 5 的 rule 草稿模板新增宣告欄位，使 agent 產出的建議文字自帶宣告，並以既有的 anchor 測試模式鎖住該段落。宣告語法與合格 gate 清單寫入 `.claude/rules/11-skill-authoring.md`（以 `paths: skills/**` 觸發，非常駐）。對 `~/.claude/CLAUDE.md` 與常駐 rule 不新增文字。

## Implementation Contract

**Behavior.** 執行 `python3 scripts/lint_rule_evidence.py`（staged 模式）或加 `--base <A> --head <B>`（range 模式）時，除既有證據檢查外，對 `.claude/rules/*.md` 新增的 `##` / `###` section 逐一檢查機械化宣告。輸出沿用既有格式：缺宣告與假宣告皆為 `[FAIL] N 個 ...` 後列出每個問題（缺宣告的訊息為 `<path>：新增 section「<heading>」缺少機械化宣告`）與修法提示（列出兩種宣告語法）。證據檢查原有的 `[WARN]` 行為不變。

**Interface.**

- `check_rule_mechanization(diff_text: str, read_gate_file: Callable[[str], str | None]) -> list[str]`：回傳 error 訊息清單。涵蓋：任何 rule 檔（新或既有）新增 section 的缺宣告；任何 rule 檔內的假宣告。不存在 warn 版本的入口。
- `_parse_diff` 回傳的 `_FileDiff` 帶 `unseen: str | None`（`"pure_rename"` / `"copy"` / `"binary"` / `"empty"`：沒有可讀內容行的檔案；`pure_rename` 為由它導出的 property）與逐 hunk 的 `removed_headings`：證據檢查略過 `unseen`，機械化檢查對進入 `.claude/rules/` 者報 error，`removed_headings` 供改標題判斷。引號路徑解不開時 `_parse_diff` raise `ValueError`。
- 宣告 regex 為模組常數；豁免理由集合為模組常數 `_EXEMPT_REASONS = frozenset({"judgment", "no-observable-signal", "hook-cost"})`；合格目錄清單為模組常數。
- `main()` 的 exit code 契約不變（0 / 1 / 2），新增：`read_gate_file` raise `OSError`（含讀 index / head 時 git 失敗）或 diff 裡有解不開的引號路徑時回 2。`read_gate_file` 預設值依輸入而定：staged 讀 index、range 讀 `--head`、diff 檔讀工作樹；注入的假實作優先於預設值。

**Failure modes.**

- 連結目標不存在、不合格、缺 symbol：error，訊息含連結原文與原因（不存在 / 不合格目錄 / 缺 symbol）。
- 路徑檢查遇到 `OSError`（非不存在）：exit 2，不得印 `[OK]`。repo root 由腳本自身位置推導，沒有獨立的「無法判定」失敗模式。
- 豁免 reason 不在列舉、說明為佔位或過短：error。
- 同 section 同時有連結與豁免，或有兩個連結：error（互相矛盾）。
- 刻意靜默的情況：只有「已存在 section 未變動」不被掃描，這是設計而非遺漏。

**Acceptance criteria.**

1. `uv run pytest scripts/tests/test_lint_rule_evidence.py` 全綠，且包含 `fixtures/rule_mechanization/` 內十五個 bad fixture 各自經純函式與 `main()` 兩條路徑的斷言。
2. 突變 A：`main()` 在讀 diff 前 `return 0` → fixture 測試至少 7 個轉紅。突變 B：把合格目錄清單加入 `.claude/rules/` → 「link 到 rule」fixture 轉紅。突變 C：`read_gate_file` 的 `OSError` 被吞成 `None` → exit 2 的測試轉紅。三者皆單點突變，並在突變前斷言 anchor 已套用。
3. `make ci` 全綠（`git add` 之後再跑，避免 untracked 新檔被 hook 略過）。
4. 以本 repo 現有 HEAD 對 `origin/main` 跑 range 模式：不得因既有未動內容新增任何 warn 或 error。
5. `git diff origin/main -- .claude/rules/01-language-and-tone.md .claude/rules/03-security.md .claude/rules/13-bash-anti-patterns.md .claude/rules/15-irreversible-operations.md .claude/rules/16-allowlist-hygiene.md` 為空（常駐面淨增為零）。

**Scope boundaries.** In scope：`scripts/lint_rule_evidence.py`、其測試與 fixture、`pr-retrospective` SKILL.md Step 5 模板及 anchor 測試、rule 11 的語法說明。Out of scope：既有 rule 補宣告、gate 語意覆蓋驗證、`harness-weekly-review` 量測、`/pr-review-cycle` mutation check、hook 自動產生、`.pre-commit-config.yaml` 的 `files:` 範圍變更（現有範圍已涵蓋 `.claude/rules/*.md`）。

## Risks / Trade-offs

- [連結可被指向「存在但不相干」的 gate 而通過] → 已列為 Non-Goal 殘留；由 `harness-weekly-review` 的 gate 觸發率量測承接，且 spec 明文限定「只證明存在且屬 gate 類別」，避免讀者誤以為已驗證語意。
- [`--unified=0` 造成同 hunk 限制，產生保守誤報] → 於 rule 11 語法說明記載；誤報方向是多報而非漏報，可接受。
- [純 rename 進 rules 目錄原本看不到] → 已改為 fail-closed（見 Decisions）。合法的 `git mv` 進 rules 目錄會被擋，但這本來就罕見且該被審視；修法是同一個 commit 補上證據標記與宣告。
- [同一個盲點在 `.claude/hooks/` 仍存在：證據 lint 對新 hook 的檢查看不到純 rename] → 已知殘留，不在本 change 範圍（證據 lint 對純 rename 刻意維持既有行為）；記於 rule 11，另案處理。
- [既有檔缺宣告改為 error 後，同 hunk 限制會把「heading 插在既有內文之上、宣告落在未變動行」誤判為缺宣告並擋下 commit] → 修法是把宣告緊接在 heading 之後（本來就是慣例位置）；誤報方向是多報而非漏報；限制記於 lint docstring 與 rule 11。
- [fence 狀態在 `--unified=0` 的 hunk 內只看得到半個 fence 時會反過來（例如只新增了結尾的 ```）] → 與「宣告必須與 heading 同 hunk」同類：hunk 內看不到完整脈絡，無法在不讀整個檔案的前提下解決；實務上新增一整個 fenced 範例時開關都在同一個 hunk。已記於 `_FenceTracker` 的 docstring。
- [staged / range 模式因此多出對 git 的 IO（`ls-files` / `ls-tree` / `cat-file`），每個 gate 連結多一到兩次子程序] → 只有宣告了連結的 section 才會觸發，數量級是個位數；換來驗證對象與被 commit 的內容一致。diff 檔模式不受影響。
- [讀 gate 時 git 失敗現在是 exit 2（過去讀工作樹只會是「存在 / 不存在」）] → 這是刻意的：無法驗證不等於通過，也不等於 dangling；CI 缺物件（shallow checkout）時 `_range_diff` 早已 exit 2，行為一致。
- [與 `add-retro-evidence-gate` 同改一支腳本，merge 衝突] → 建議該 change 先 archive；本 change 只新增函式與並列呼叫，不改動其函式本體。
- [reason 列舉三值可能不夠] → 新增值需改常數、spec 與 fixture，這個摩擦是刻意的：新增理由必須經過 review，不能在 rule 檔裡就地發明。
