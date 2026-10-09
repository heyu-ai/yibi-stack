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

兩者共用 `_parse_diff` 與 `_evidence_eligible_lines`，但判定互不替代：證據標記不滿足宣告，宣告也不滿足證據標記。實作為 `main()` 內並列的兩組呼叫，輸出合併為同一份 `[WARN]` / `[FAIL]` 清單。已知限制：因 `--unified=0`，宣告必須與其 heading 位於同一個 hunk；heading 插入在既有內容之上、宣告落在未變動行時，會被誤判為缺宣告。此為可接受的保守誤報，記入 rule 11 的語法說明。

### 正向對照 fixture 依形狀分開、含真實資料對照與入口短路驗證

`scripts/tests/fixtures/rule_mechanization/` 放九個 `bad_*.diff`（新檔缺宣告、既有檔缺宣告、無 section 的新檔、dangling link、link 到 rule、缺 symbol、未知 reason、佔位說明、雙重宣告）與數個 `good_*.diff`。每個 bad fixture 以兩種路徑斷言被擋：純函式回傳非空，以及 `main([fixture_path])` 回傳非零。真實資料對照：測試在執行時複製 `.claude/rules/` 下一份真實 rule 檔，在斷言錨點存在之後注入未宣告 section，再產生 diff 餵給 lint；錨點找不到時測試失敗而非跳過。形狀刻意分散（新檔、既有檔、rename 進來），避免七個對照其實同構。另以突變驗證：把 `main()` 短路成回傳 0，確認 fixture 測試轉紅；每次突變只改一件事，還原用反向替換而非 `git checkout`。

### SKILL.md 與 rule 11 同步

`pr-retrospective` Step 5 的 rule 草稿模板新增宣告欄位，使 agent 產出的建議文字自帶宣告，並以既有的 anchor 測試模式鎖住該段落。宣告語法與合格 gate 清單寫入 `.claude/rules/11-skill-authoring.md`（以 `paths: skills/**` 觸發，非常駐）。對 `~/.claude/CLAUDE.md` 與常駐 rule 不新增文字。

## Implementation Contract

**Behavior.** 執行 `python3 scripts/lint_rule_evidence.py`（staged 模式）或加 `--base <A> --head <B>`（range 模式）時，除既有證據檢查外，對 `.claude/rules/*.md` 新增的 `##` / `###` section 逐一檢查機械化宣告。輸出沿用既有格式：缺宣告與假宣告皆為 `[FAIL] N 個 ...` 後列出每個問題（缺宣告的訊息為 `<path>：新增 section「<heading>」缺少機械化宣告`）與修法提示（列出兩種宣告語法）。證據檢查原有的 `[WARN]` 行為不變。

**Interface.**

- `check_rule_mechanization(diff_text: str, read_gate_file: Callable[[str], str | None]) -> list[str]`：回傳 error 訊息清單。涵蓋：任何 rule 檔（新或既有）新增 section 的缺宣告；任何 rule 檔內的假宣告。不存在 warn 版本的入口。
- 宣告 regex 為模組常數；豁免理由集合為模組常數 `_EXEMPT_REASONS = frozenset({"judgment", "no-observable-signal", "hook-cost"})`；合格目錄清單為模組常數。
- `main()` 的 exit code 契約不變（0 / 1 / 2），新增：`read_gate_file` raise `OSError` 時回 2。

**Failure modes.**

- 連結目標不存在、不合格、缺 symbol：error，訊息含連結原文與原因（不存在 / 不合格目錄 / 缺 symbol）。
- 路徑檢查遇到 `OSError`（非不存在）：exit 2，不得印 `[OK]`。repo root 由腳本自身位置推導，沒有獨立的「無法判定」失敗模式。
- 豁免 reason 不在列舉、說明為佔位或過短：error。
- 同 section 同時有連結與豁免，或有兩個連結：error（互相矛盾）。
- 刻意靜默的情況：只有「已存在 section 未變動」不被掃描，這是設計而非遺漏。

**Acceptance criteria.**

1. `uv run pytest scripts/tests/test_lint_rule_evidence.py` 全綠，且包含上列九個 bad fixture 各自經純函式與 `main()` 兩條路徑的斷言。
2. 突變 A：`main()` 在讀 diff 前 `return 0` → fixture 測試至少 7 個轉紅。突變 B：把合格目錄清單加入 `.claude/rules/` → 「link 到 rule」fixture 轉紅。突變 C：`read_gate_file` 的 `OSError` 被吞成 `None` → exit 2 的測試轉紅。三者皆單點突變，並在突變前斷言 anchor 已套用。
3. `make ci` 全綠（`git add` 之後再跑，避免 untracked 新檔被 hook 略過）。
4. 以本 repo 現有 HEAD 對 `origin/main` 跑 range 模式：不得因既有未動內容新增任何 warn 或 error。
5. `git diff origin/main -- .claude/rules/01-language-and-tone.md .claude/rules/03-security.md .claude/rules/13-bash-anti-patterns.md .claude/rules/15-irreversible-operations.md .claude/rules/16-allowlist-hygiene.md` 為空（常駐面淨增為零）。

**Scope boundaries.** In scope：`scripts/lint_rule_evidence.py`、其測試與 fixture、`pr-retrospective` SKILL.md Step 5 模板及 anchor 測試、rule 11 的語法說明。Out of scope：既有 rule 補宣告、gate 語意覆蓋驗證、`harness-weekly-review` 量測、`/pr-review-cycle` mutation check、hook 自動產生、`.pre-commit-config.yaml` 的 `files:` 範圍變更（現有範圍已涵蓋 `.claude/rules/*.md`）。

## Risks / Trade-offs

- [連結可被指向「存在但不相干」的 gate 而通過] → 已列為 Non-Goal 殘留；由 `harness-weekly-review` 的 gate 觸發率量測承接，且 spec 明文限定「只證明存在且屬 gate 類別」，避免讀者誤以為已驗證語意。
- [`--unified=0` 造成同 hunk 限制，產生保守誤報] → 於 rule 11 語法說明記載；誤報方向是多報而非漏報，可接受。
- [100% 相似度的純 rename 沒有 `---` / `+++` 行（git 2.56.0 實測），本 lint 與證據 lint 都看不到] → 已知殘留，記於 rule 11；帶內容變更的 rename 有 hunk，會被視為新檔。要補這個洞需要讀工作樹或解析 `rename from/to` 標頭，另案處理。
- [既有檔缺宣告改為 error 後，同 hunk 限制會把「heading 插在既有內文之上、宣告落在未變動行」誤判為缺宣告並擋下 commit] → 修法是把宣告緊接在 heading 之後（本來就是慣例位置）；誤報方向是多報而非漏報；限制記於 lint docstring 與 rule 11。
- [與 `add-retro-evidence-gate` 同改一支腳本，merge 衝突] → 建議該 change 先 archive；本 change 只新增函式與並列呼叫，不改動其函式本體。
- [reason 列舉三值可能不夠] → 新增值需改常數、spec 與 fixture，這個摩擦是刻意的：新增理由必須經過 review，不能在 rule 檔裡就地發明。
