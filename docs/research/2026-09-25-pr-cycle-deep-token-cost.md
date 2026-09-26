# pr-cycle-deep／spectra-amplifier 的 token 成本：量測、已做的修正與待裁決方案

**日期**：2026-09-25
**背景**：使用者問 `/pr-cycle-deep` 與 `/spectra-amplifier` 為什麼大量消耗 token。本文記錄量測方法、
根因、這個 PR 已經做的兩項修正（Step 1.5 改 script、fix 階段切 context），以及兩項研究
（常駐 context 瘦身方案、`testplan.md` 的實際使用狀況）。
**前作**：`docs/research/2026-05-24-rules-english-recall-audit-token-optimization.md`
（rules 英文化的 token 取捨；本文處理的是另一個軸：載入範圍與 context 生命週期）。

標記慣例：**實測** = 本文作者或研究 subagent 實際跑過指令得到的數字；**推論** = 由實測推導、
未直接量測；**未查證** = 研究 subagent 回報、本文未獨立重現。

---

## 1. 量測：成本的乘數是「turn 數 × context 長度」

方法（實測）：掃描 `~/.claude/projects/*/*.jsonl`，只認真正的 `Skill` tool_use 或 slash command
呼叫（skill 清單裡出現的字串不算），把每個 assistant turn 的
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` 與 `output_tokens` 加總，
subagent transcript（`<session>/subagents/*.jsonl`）另外計算。

| 指標（最近 8 個 session） | 有跑 pr-cycle-deep 的 session | 有跑 spectra-amplifier 的 session |
|---|---|---|
| 主 context turn 數 | 99–367 | 117–299 |
| 主 context 累計 input | 20M–204M | 28M–113M |
| 峰值 context | 322k–947k | 333k–968k |
| 第一個 turn 的 context（還沒開始做事） | 75k–164k | 106k–163k |
| output | 58k–275k（佔 input 0.1–0.3%） | 46k–519k |
| subagent 累計 input | 最多 70M（單一 session 7 個 subagent） | 3M–83M |

注意：session 總量包含同一 session 內做的其他事情，無法精確拆出「只屬於該 skill」的部分；
結論只依賴「input 遠大於 output」這個在每一筆都成立的趨勢。

根因（實測 + 讀 SKILL.md）：

1. **整個生命週期在同一個主 context**：review、fix、CI、re-review、merge 全部累積在同一個
   context，每一次 tool call 都要重讀整段。
2. **只跑一行指令也開 subagent**：舊版 Step 1.5 開 3 個 Task agent，各自只跑
   `gh pr diff`、`gh pr checks`、`amplifier-verify.py`，每個都要重新載入基底 context。
3. **基底 context 大**：常駐載入的 rules 與 CLAUDE.md 約 190KB；碰到 `skills/**` 還會再載入
   rule 11（80KB）。
4. **SKILL.md 本身 71KB**，整個 session 都留在 context 裡。
5. spectra-amplifier：frontmatter 固定 `effort: high`；`qa-test-designer` 用 `model: opus` +
   `effort: high` 且「不讀寫檔案」，TC 表在 lead context 裡進出 2–3 次。

## 2. 本 PR 已做的修正

| 項目 | 做法 | 驗證 |
|---|---|---|
| Step 1.5 | `scripts/pre_review_check.py` 一次 Bash call 取代 3 個 Task agent；完整輸出寫 `.pr-review/pre-review-check.md`，stdout 只印 4 行 | 22 個測試；把「no checks reported」判斷短路成永遠放行後，EG-002／EG-003 共 4 個測試轉紅；對真實 PR #469 端對端跑過 |
| 切 context | Step 6 fix 改派 subagent，lead 自己看 `git log`、自己重跑 CI（只 gate exit code）；Step 5 起寫 `.pr-review/state.md` checkpoint；新增 `--resume` | convergence contract 36 個測試全過；SKILL.md 1305 → 1302 行 |

被否決的做法：在 SKILL.md 寫「在這裡執行 `/compact`」。`/compact` 是內建 CLI 指令，agent 無法
自行觸發，寫了等於沒寫。所以改成「subagent 吸收高 turn 數的階段」加上「checkpoint 讓人類在既有的
停頓點選擇 compact 或開新 session」。

尚未處理的次要項目：Step 3 各 voice 的 Stage 3 render（lead 讀 JSON、再寫 compact markdown）是
確定性轉換，可以改成 script；Claude voice 的 4 個 subagent 可依 diff 內容決定要不要開。

## 3. 研究：縮小常駐 context（原方案 #7）

### 3.1 會卡住的治理約束（實測）

- `scripts/check_always_loaded_growth.py:226` 判斷式是 `if growth != 0`，**縮小也會 FAIL**。
  不過它是 `add-retro-evidence-gate` change 的自我約束，沒有接進 CI 或 pre-commit
  （`.pre-commit-config.yaml` 與 `.github/workflows/ci.yml` 都沒有呼叫它）。
- `scripts/lint_rule_evidence.py`：新的 `.claude/rules/*.md` 檔案缺證據標記會直接 error，
  所以拆出來的新 scoped rule 必須帶 `(Source: PR #NNN` 或 `<!-- verified: ... -->`。
- `scripts/install-rules-to-repo.sh` 寫死只把 13/15/16 複製到其他 repo（未查證行號），拆檔時要一起改。
- 已有先例目錄 `docs/rules-reference/`（auto-handover 曾搬到這裡），適合放搬出來的事故敘事。

### 3.2 關鍵限制：`paths:` 對 Bash 指令無效

`paths:` 只在 Read／Edit／Write 碰到匹配路徑時觸發；`git push -f`、`rm -rf` 這類直接下的 Bash
指令不經過任何檔案路徑。所以 rule 15 的 STOP 規則與分類表、rule 13 的 AP1–3、Quoting 1–5、
「pipe 吃掉 exit code」**必須留在常駐**。能 scope 化的只有「寫某類檔案時才需要」的規則。
另有一個未驗證的時序風險：對新檔的第一次 Write，scoped rule 可能在寫完之後才載入。

### 3.3 方案（依「省最多 × 風險最低」排序）

| # | 動作 | 預估省下 | 風險 | 誰決定 |
|---|---|---|---|---|
| A | CLAUDE.md 的 `@tasks/_paths.py`、`@scripts/lint_skill_bash.py`、`@.claude/rules/` 改成 backtick（agent 只需要知道路徑） | 0 或約 5.5k token（主 session 是否展開 `@` 未實測；subagent 實測未展開） | 零 | agent 可做 |
| B | rule 02 加 `paths: ["**/*.py"]`（內容幾乎全是寫 Python 的規則） | 約 5k | 低；會觸發 growth check（見 3.1） | agent 可做，growth check 需裁決 |
| C | rule 13 的「寫腳本才需要」段落（trap ERR、restore、stderr 慣例、realpath、`pwd -P`、GIT_DIR、Quoting Rule 7 等，約 21KB）拆到 `13b-shell-scripting.md`，scope 到 `**/*.sh`、`Makefile`、`.claude/hooks/**` | 約 6k | 中（寫入時序） | agent 可做 |
| D | rule 16 主體 scope 到 `**/settings*.json`，常駐只留一行「不可提議中段萬用字元或 verb 層級萬用字元」 | 約 3.9k | 低-中（repo 外路徑能否匹配未實測） | agent 可做 |
| E | rule 15 的事故流程（release 共用 checkout、救回誤 commit、revert checklist、merge 後清理）搬到對應 skill 或 `docs/rules-reference/`；STOP 規則與分類表保留 | 約 5.7k | 中 | agent 可做 |
| F | 13/02/15 各段的 Source／Evidence 敘事搬到 `docs/rules-reference/`，只留指標 | 約 4.3k | 低；但搬進 docs 的英文 prose 要不要改成繁中需要裁決 | 語言需裁決 |
| G | CLAUDE.md 的 make install 系列 gotcha 路由到 scoped rule（可用 `claude-md-prune` skill） | 約 2.9k | 低 | agent 可做 |
| H | rule 11 中「make install 不可從 worktree 執行」那段（約 19.7KB，與 skill 撰寫無關）移到 `Makefile`／`scripts/assert_not_worktree.sh` scoped rule | 碰 skills 的 session 省約 5.6k | 低 | agent 可做 |
| I | harness plugin 的 SessionStart 注入（約 5.3KB，約 95% 與 rule 13 重複）在 repo 已有 rule 13 時跳過 | 約 1.5k | 中；plugin 改動需 lockstep bump | agent 可做（PR） |
| J | 刪除全域 `~/.claude/CLAUDE.md` 與 repo 重複的段落 | 約 1.3k | 低；影響其他 repo | **使用者裁決** |
| K | growth check 改成允許淨減（`> 0`） | — | 改的是尚未 archive 的 change 的行為 | **使用者裁決** |

整體估算（推論）：指令層目前約 54k token，做完 A–I 後約 21k，第一個 turn 從 110–165k 降到約
75–130k。其餘的量來自 system prompt、工具清單、skill 清單與 agent 類型描述，不在本方案範圍。

### 3.4 rule 13 與 rule 16 的矛盾：以 rule 16 為準（已修正）

rule 13 的 Quoting Rule 5 與全域 CLAUDE.md 都建議把 `Bash(git -C *)` 加進 allow-list，
rule 16 則把 `Bash(git -C * status)` 列為 Red Flag 1。依 `/lessons` 的過去經驗判定 **rule 16 正確**：

- `git-commit-allow-list-middle-wildcard`（yibi-mvp PR #436，三家 mob review 各自獨立指出）與
  `git-commit-allow-list-never-permanent`（yibi-stack）：`git -C *` 的 `*` 會吞掉後面所有參數，
  `git -C /x push --force origin main` 也會匹配。`Bash(git -C *)` 比被列為 Red Flag 的
  `Bash(git -C * status)` 還寬，等同 Red Flag 2（verb 層級萬用字元）。
- `bash-simple-expansion-allow-entry-not-structure`（conf 9，7 格 probe matrix）：rule 13 加這條的動機
  是壓掉 `simple_expansion` 誤報。但實測顯示跳框與否取決於「該 verb 有沒有對應的 allow entry」，
  正解是「verb 在第一個 token + 字面絕對路徑」，不需要開一條萬用規則。
- 查證 rule 16 時，另外發現 rule 16 自己的「安全範例」也有兩處錯誤：
  - `cc-allowlist-git-output-write-vector`（yibi-mvp，conf 8）指出 `Bash(git diff:*)`／`git log:*`
    有 `--output=<file>` 寫檔向量；本機以 git 2.55.0 重測成立（兩者都寫出了檔案）。
  - `Bash(git fetch:*)` 可經 `--upload-pack=<cmd>` 執行指令，這個 repo 的 `setup-review-dir.sh` 註解
    （PR #175）早已實測過，但 rule 16 仍把它列為安全。

已修正：rule 13 的範例改成 per-repo 精確 prefix；rule 16 的安全範例表、Red Flag 2 修法、remediation
範例、`/less-permission-prompts` 改寫表都拿掉 `log:*`／`diff:*`／`fetch:*`；順帶修正過時的「Rule 14」
引用。常駐行數淨增 0。

**仍需使用者處理**：全域 `~/.claude/settings.json:60` 實際放行了 `Bash(git -C *)`，而 repo 的 deny 規則
`Bash(git push --force*)` 只擋以 `git push` 開頭的形式，擋不到 `git -C <path> push --force`。
全域 CLAUDE.md 的 Bash Patterns 段也還在建議這條。兩者都屬使用者的個人設定，agent 不自行修改。

## 4. 研究：`testplan.md` 有沒有被用到（原方案 #6）

範圍：yibi-stack（8 份 testplan）與 ainization-skill（5 份）。yibi-mvp 不在本機磁碟上，**無法查證**。

### 4.1 TC-ID 在測試碼中的名目命中率（實測）

- yibi-stack：17 個 change 只有 8 份 testplan，共 220 個 TC，在測試碼找得到 97 個（44%）。
- ainization-skill：5 份 testplan 共 188 個 TC，找得到 112 個（60%）。
- **命中率偏高**：`SMK-001` 這類通用 ID 在多個測試 fixture 裡都有；`PRC-*` 被兩個 change 共用；
  skill-trigger-eval 的 SEVAL ID 同名但測的東西不同（例如 SEVAL-DT-003 在 testplan 是「negative
  未觸發計為 passed」，測試實際測「低於 baseline-tolerance 判定回歸」）。
- 找不到的 TC 大宗是 `[doc]`／`[manual]` 類。

### 4.2 誰會讀 testplan.md

- `plugins/sdd/scripts/check_spec_coverage.py`：**完全不讀 testplan**（實測：檔案內 `testplan` 出現 0 次），
  只比對 spec slug 與 `spec: cap#slug` docstring。因此 `spectra-amplifier/SKILL.md:500` 的
  「testplan.md 所有 TC 均有對應測試（check_spec_coverage.py 驗證）」是**不實宣稱**（實測）。
- CI、pre-commit、Makefile 都沒有呼叫 `amplifier-verify.py` 或 `check_spec_coverage.py`（實測）。
- `amplifier-verify.py`（pr-cycle-deep Step 1.5）是唯一會解析 testplan 的程式，但它做的是
  「Coverage 表 Missing／Partial 列的靜態檢查」與「新增測試的 docstring 標記格式檢查」，
  **從不檢查每個 TC 都有對應測試**（未查證行號，研究 subagent 引 `amplifier-verify.py:714-783`）。
- `spectra-apply` 的 SKILL.md 不提 testplan（未查證）。
- 真正的下游消費路徑是 tasks.md 引用 TC-ID（bound-review-loop、pr-control-log 各 26 處），
  實作者讀 tasks.md 時會看到。

### 4.3 維護狀況（實測，git log）

- 多數 change 的 testplan 與測試在同一個 squash commit，看不出誰先寫。testplan 明確先寫的例子：
  retro-evidence-gate、financial-registry、mycelium-cli。
- testplan 建立之後幾乎沒有再更新。financial-registry 實作時改用 `FREG-*` 前綴，testplan 仍是
  `REG-*`，16 個 TC 全部對不上。

### 4.4 結論與建議

**部分有用，偏形式主義。** 在 testplan 先寫的 change 裡，`[mech]` 類 TC 大多真的變成測試，
TC 前綴也成了 docstring 的命名來源；但沒有任何自動化檢查 TC 是否被實作，`[doc]`／`[manual]`
TC 幾乎都沒落地，編號脫鉤後也沒人維護。

建議（待使用者裁決）：

1. **`qa-test-designer` 直接寫檔**（值得做、風險低）：testplan 的讀者只有 regex 與人，lead 不需要
   把整張 TC 表留在 context。代價是 Step 2b／2c 要一起移進 agent，並補上 rule 11 的三條失敗路徑。
2. **不建議整個移除 Step 2**，改成降級：只產 `[mech]` TC 並加 slug 欄（讓 amplifier-verify 的
   docstring 檢查能生效）；`[doc]`／`[manual]` 縮成 Coverage 表的備註列。
3. **修正 `spectra-amplifier/SKILL.md:500` 的不實宣稱**，或真的讓某支工具去比對 TC-ID。否則
   testplan 會一直被當成「有保障」，實際上沒有任何東西在把關。
