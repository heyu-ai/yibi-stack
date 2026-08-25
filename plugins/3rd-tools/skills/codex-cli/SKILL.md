---
name: codex-cli
type: tool
scope: global
description: 讓 Claude 規劃工作、分派 OpenAI Codex CLI 實際寫 code（-s workspace-write），再由 Claude 收貨驗收：查 git diff、跑全量 CI、把 finding 回饋給 Codex 修（最多 2 輪）。派工前會算出本次任務適用的 CLAUDE.md 與 .claude/rules/ 路徑清單附進 packet，要求 Codex 自行讀取並聲明讀了哪些。觸發：codex 實作, 派給 codex 寫, 委託 codex, 讓 codex 做, delegate to codex, codex 幫我改這個功能。只想問 Codex 技術問題、沒有 code 要寫請改用 /codex-consult；只想 review 現成 diff 請改用 /codex-review；要多個外部模型 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep。
---

# /codex-cli — 委託 Codex 實作並驗收

Claude 規劃 → Codex 寫 code → Claude 驗收。與同家族兩個 skill 的差別在於 sandbox 模式：
`/codex-consult` 與 `/codex-review` 都是 `-s read-only`，Codex 不能改檔；本 skill 用
`-s workspace-write`，Codex 會真的動你的工作樹。

設計決策與被否決方案見 `docs/codex-cli-delegation-plan.md`。

**本 skill 不做 commit / push / PR** — 改動留在工作樹，由使用者或 `/pr-cycle-*` 接手。

**本 skill 只適用 repo 內、會產生 code 改動、需 CI 驗收的委派。** 唯讀分析、或目標在任何
git repo 之外（例：`~/Documents/` 的文件）不走本 skill——git gate 會卡在「不是 git repo」。
改直接 `codex exec -s workspace-write --skip-git-repo-check -C <最小目錄>`，並把 `-C` 收到
剛好涵蓋讀寫範圍的目錄以收緊 sandbox。<!-- verified: probe, codex-cli 0.142.5 -->

---

## Step 0.1: 確認 codex binary

```bash
which codex 2>/dev/null && echo "CODEX_BIN: found" || echo "CODEX_BIN: not_found"
```

輸出 `not_found` → 停止並告知使用者：「Codex CLI 未安裝。請執行：`npm install -g @openai/codex`」

## Step 0.2: Auth 確認

**分兩次 bash call**（避免 if/elif 觸發確認框）：

```bash
env | grep -qE '^(CODEX_API_KEY|OPENAI_API_KEY)=.' && echo "KEY_AUTH: yes" || echo "KEY_AUTH: no"
```

```bash
test -f ~/.codex/auth.json && echo "FILE_AUTH: yes" || echo "FILE_AUTH: no"
```

判斷規則（讀兩次輸出自行判斷）：

- `KEY_AUTH: yes` → 已認證，繼續
- `KEY_AUTH: no` 且 `FILE_AUTH: yes` → 已認證，繼續
- 兩者皆 `no` → 停止並告知：「請執行 `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY`。」

## Step 0.3: Branch gate

```bash
git branch --show-current
```

| 輸出 | 動作 |
|------|------|
| `main` / `master` | **停止**：「不可在 `main` 上派工給 Codex。請先開 feature branch 或 worktree。」 |
| 空字串（detached HEAD） | **停止**：「目前是 detached HEAD，改動無處可歸。請先 checkout 一個 branch。」 |
| 其他 branch 名 | 繼續 |

理由：Codex 會直接改工作樹，`main` 上的誤改難以區分與還原（見 `.claude/rules/15`）。

## Step 0.4: 工作區乾淨 gate

```bash
if ! PORCELAIN=$(git status --porcelain); then echo '[FAIL] git status 失敗，無法確認工作區狀態' >&2; exit 1; fi
if [ -n "$PORCELAIN" ]; then echo '[FAIL] 工作區有未提交的改動，請先 commit 或 stash——否則收貨時無法分辨哪些改動是 Codex 做的' >&2; exit 1; fi
```

**兩道判斷缺一不可，而且它們擋的是不同的東西**：

| 判斷 | 擋住什麼 | 為什麼單獨不夠 |
|------|----------|----------------|
| `if ! PORCELAIN=$(...)` | 非零退出（repo 損壞、權限問題） | 無輸出**且非零退出**會被讀成「乾淨」，於是在壞掉的 repo 上開啟 workspace-write |
| `[ -n "$PORCELAIN" ]` | 工作區真的髒 | **`git status --porcelain` 乾淨或髒都 exit 0**，訊號在 stdout 不在退出碼 |

第二道是本 skill 早期版本缺的那道，且缺得很隱蔽：只寫 `if ! git status --porcelain` 看起來
像在檢查工作區，實際上它對「工作區有未提交改動」這個它要擋的情況**永遠不觸發**。實測：

```console
$ git status --porcelain      # dirty tree
 M a.txt
?? b.txt
$ echo $?
0
```

散文寫「輸出非空即停止」不能取代機械判斷——這道 gate 是 `-s workspace-write` 信任邊界的
主要緩解之一，不能只靠 agent 讀 stdout 自行判斷。

凡是「退出碼恆 0、訊號在 stdout」的指令（`git status --porcelain`、`git diff --name-only`、
`grep -l`）都適用同一條：**擷取輸出再判斷內容，不要只用 `if !` 包住它**。

這道 gate 是 Step 4 收貨查核的前提：只有從乾淨狀態出發，工作樹的狀態才等於「Codex 的改動」。

## Step 0.5: 偵測 repo 的全量 CI 指令

```bash
ROOT=$(git rev-parse --show-toplevel)
git -C "$ROOT" ls-files Makefile .pre-commit-config.yaml package.json
```

`-C "$ROOT"` 不可省：`git ls-files` 的 pathspec 是 **cwd-relative**，從子目錄執行會回空清單，
於是在一個三者俱全的 repo 裡靜默走到「全都沒有」那一列。

若上一步輸出含 `Makefile`：

```bash
ROOT=$(git rev-parse --show-toplevel)
grep -n '^ci:' "$ROOT/Makefile"
```

（無 `Makefile` 時 grep 會回報找不到檔案，屬預期；依上一步的清單判斷即可。）

| 偵測結果 | CI 指令 |
|----------|---------|
| `Makefile` 存在且有 `ci:` target | `make ci` |
| 無 `ci:` target，但有 `.pre-commit-config.yaml` | `uv run pre-commit run --all-files` |
| 以上皆無，但有 `package.json` | `npm test`（先確認 `scripts.test` 存在） |
| 全都沒有 | `[WARN]` 告知使用者「找不到全量 CI 指令，Step 5 將只能靠人工驗收」，並詢問要用哪個指令 |

把選定的指令記為 `{{ci_command}}`，Step 3 的 packet 與 Step 5 都會用到。**不可自行縮小成
單一 pytest 路徑或只掃改動檔的 ruff**——那是子集，過了不代表 repo 全量會過。

## Step 0.6: 解析 skill 資源路徑與暫存目錄

後續每一步都要用到兩個路徑，在此一次算出。**兩個都必須記成字面絕對路徑再往下走**——
Claude Code 的每個 bash call 是獨立 subprocess，shell 變數不跨 call，把 `$SKILL_ROOT`
寫進 Step 3 的指令只會展開成空字串。

**（a）skill 資源根目錄**（`contract.md` 與 `scripts/` 的所在）。三個安裝來源都要試，
不能只看 `~/.agents/skills/`：

```bash
CODEX_CLI_CACHED=$(python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.claude'/'plugins'/'installed_plugins.json').read_text(encoding='utf-8')); print(next((e.get('installPath','') for e in d.get('plugins',{}).get('3rd-tools@yibi-stack',[]) if e.get('installPath')), ''))" 2>/dev/null)
if [ -r "${CODEX_CLI_CACHED:-/nonexistent}/skills/codex-cli/contract.md" ]; then SKILL_ROOT="$CODEX_CLI_CACHED/skills/codex-cli"; elif [ -r "$HOME/.agents/skills/codex-cli/contract.md" ]; then SKILL_ROOT="$HOME/.agents/skills/codex-cli"; elif [ -r "plugins/3rd-tools/skills/codex-cli/contract.md" ]; then SKILL_ROOT="plugins/3rd-tools/skills/codex-cli"; else SKILL_ROOT=""; fi
if ! test -n "$SKILL_ROOT"; then echo '[FAIL] 找不到 codex-cli 的 contract.md。請執行 claude plugin install 3rd-tools@yibi-stack，或在 yibi-stack checkout 執行 make install' >&2; exit 1; fi
echo "SKILL_ROOT=$SKILL_ROOT"
```

把輸出記為 `{{skill_root}}`。

**候選順序不可對調，且不可只留 `~/.agents/skills/`**：後者只有 `make install` 會建立。
一個照本 skill 自己 README 宣傳的 `claude plugin install 3rd-tools@yibi-stack` 安裝的使用者
根本沒有那個路徑，第一次派工就會停在這道 gate——skill 對它自己文件宣傳的安裝方式不可用。
`installed_plugins.json` 的 `installPath` 才是 plugin 安裝的正常位置，故列為第一候選
（同 `plugins/sdd/skills/spectra-amplifier/SKILL.md` 的既有做法）。

**（b）暫存目錄**（brief / packet / report）：

```bash
if ! ROOT=$(git rev-parse --show-toplevel); then echo '[FAIL] 不在 git repo（Step 0.3 應已擋下）' >&2; exit 1; fi
JOB_DIR="${CLAUDE_JOB_DIR:-$ROOT/tmp/codex-cli}"
if ! mkdir -p "$JOB_DIR"; then echo "[FAIL] 無法建立暫存目錄：${JOB_DIR}" >&2; exit 1; fi
echo "JOB_DIR=$JOB_DIR"
```

把輸出記為 `{{job_dir}}`。

**`$CLAUDE_JOB_DIR` 不可裸用**：它只在 background job session 有值，互動式 `/codex-cli`
（本 skill 最主要的呼叫情境）通常 **unset**，裸用會讓路徑展開成 `/codex-cli-brief.md`
這種絕對路徑，寫入失敗。fallback 用 repo 內的 `tmp/`（已在 `.gitignore`）而**不是**
`mktemp -d`：後者每個 bash call 會產生不同目錄，Step 3 找不到 Step 1 寫的 brief。
同款 fallback 見 `plugins/dev-cycle/skills/issue-triage/SKILL.md`。

---

## Step 1: Claude 規劃並寫 brief

Codex 沒有本次對話的任何歷史，packet 必須自足。先用 Read / Grep / Glob 讀懂相關程式碼，
再用 Write tool 把 brief 寫入 `{{job_dir}}/codex-cli-brief.md`，內容至少涵蓋：

| 區段 | 內容 |
|------|------|
| `## Task` | 一段話說清楚要做什麼、為什麼 |
| `## Files` | 明確的檔案路徑；已存在的檔案附上目前相關程式碼的摘要或行號 |
| `## Acceptance criteria` | 可驗證的條件（哪個測試要過、哪個行為要成立） |
| `## Out of scope` | 明確不要動的東西，避免 Codex 擴大改動範圍 |
| `## Verification` | `執行 {{ci_command}}，全綠才算完成` |

Brief 用繁體中文或英文都可以，但 `## Acceptance criteria` 要具體到能被機械驗證。

## Step 2: 挑出本次任務相關的規則

列出 Step 1 `## Files` 提到的所有路徑（相對 repo root），交給 rule picker：

```bash
ROOT=$(git rev-parse --show-toplevel)
python3 {{skill_root}}/scripts/select_rules.py --repo-root "$ROOT" tasks/foo/db.py
```

把最後一個參數換成本次實際會碰到的路徑（可給多個，空白分隔）。

Exit code 與 stderr 語意（每個 `[WARN]` 各有獨立成因，不可混為一談）：

| 結果 | 意義 | 動作 |
|------|------|------|
| exit 0，stdout 有內容，stderr 空 | 正常 | 把輸出原樣接到 brief 末端（見下一步） |
| exit 0 + `[WARN] ... 沒有 .claude/rules/` | 目標 repo 無規則目錄 | 繼續，但最終報告要說明「這次派工只有 contract 的通用約束」 |
| exit 0 + `[WARN] ... 沒有命中任何 path-scoped rule` | 給的路徑全數落空（多半是拼錯，或這些路徑不在本 repo 任何 `paths:` rule 的涵蓋範圍內） | **停下來檢查路徑**再重跑——packet 會缺少該檔案適用的規範 |
| exit 0 + `[WARN] <rule> frontmatter 不完整` | rule 檔有起始 `---` 但缺結束 `---` | 繼續（該 rule 以全量載入計），但在報告點名該 rule，並回頭修它的 frontmatter |
| exit 0 + `[WARN] <rule> 有 paths: key 但解析不出任何 pattern` | 該 rule 的 `paths:` 寫法無法解析 | 繼續，但在報告點名該 rule，並回頭修它的 frontmatter |
| exit 0 + `[WARN] 無法讀取 <rule>` | 個別 rule 檔讀取失敗 | 繼續，但在報告點名該 rule |
| exit 2 + stderr 含 `repo root 不存在` | repo root 解析錯誤 | 停止並回報 |
| exit 2 + stderr 含 `can't open file` | `{{skill_root}}` 解析錯誤（Step 0.6 應已擋下） | 停止並回頭確認 Step 0.6 的輸出 |

**絕對路徑不會觸發零命中那一列**——`select_rules.py` 的 glob 是非錨定的（pattern 前面允許
任意路徑前綴），所以 `/Users/you/repo/tasks/mycelium/db.py` 照樣命中 `tasks/**`。反過來說，
**別的 repo 的絕對路徑也會靜默命中**，所以路徑一律給相對 repo root 的形式。

把 picker 的輸出用 Write tool 追加到 brief 的 `## Rules you must read` 區段下，格式：

```text
## Rules you must read

<picker 的輸出原樣貼上>

Read each file listed above before you start. Name them in your "## Rules consulted" section.
```

## Step 3: 組 packet 並派工

**先 gate brief 存在**（contract.md 的存在已由 Step 0.6 確認），再合併（契約在前，brief 在後）：

```bash
if [ ! -r "{{job_dir}}/codex-cli-brief.md" ]; then echo '[FAIL] 找不到 brief，Step 1 未完成或寫入失敗' >&2; exit 1; fi
if ! cat "{{skill_root}}/contract.md" "{{job_dir}}/codex-cli-brief.md" > "{{job_dir}}/codex-cli-packet.txt"; then echo '[FAIL] packet 組裝失敗' >&2; exit 1; fi
```

**兩個來源都要各自 gate，`cat` 的退出碼不能當唯一防線**：`>` 會先把輸出檔建出來，`cat`
缺任一檔時只印一行 stderr 並非零退出，**packet 仍然生成，只含另一個來源**。實測：

```console
$ if ! cat /nonexistent/contract.md /etc/hosts > probe.txt 2>&1; then echo "cat: NON-ZERO EXIT"; fi
cat: NON-ZERO EXIT
$ wc -c probe.txt
398 probe.txt          # 檔案照樣建立，只含第二個來源
```

派工前**兩端都要斷言**——只驗開頭不夠：

```bash
head -1 "{{job_dir}}/codex-cli-packet.txt"
```

```bash
grep -c '^## Task' "{{job_dir}}/codex-cli-packet.txt"
```

第一個輸出不是 `# Codex Delegation Contract`，或第二個輸出是 `0` → **停止**，不可派工。

**為什麼要驗第二端**：`head -1` 只證明 contract 在，不證明 brief 併進去了。brief 缺失或
不可讀時 packet 只含 contract，`head -1` 照樣輸出 `# Codex Delegation Contract` 而放行，
於是 Codex 在 `-s workspace-write` 下拿到一份**零 `## Task`、零 `## Files`、零
`## Out of scope`** 的 packet——有邊界但沒有任務，比沒有邊界更難察覺。實測：

```console
$ cat contract.md /nonexistent/brief.md > packet.txt
cat: /nonexistent/brief.md: No such file or directory
$ wc -c packet.txt
4165 packet.txt                      # 只有 contract
$ head -1 packet.txt
# Codex Delegation Contract          # 舊 gate 照樣放行
$ grep -c '^## Task' packet.txt
0                                    # 新 gate 擋下
```

反向的零邊界情境（contract 缺席、只有 brief）由 Step 0.6 的 `-r` gate 擋下——四個禁讀前綴、
禁止 git 操作、語言規範、全量 CI 要求全部消失，而且無聲。

執行（repo root 在同一個 bash block 解析進 `ROOT`，以 `"$ROOT"` 傳入；**不用 placeholder 替換**，
避免 checkout 路徑含特殊字元時逸出；**不用 `timeout`**，stock macOS 沒有這個指令）：

```bash
ROOT=$(git rev-parse --show-toplevel)
codex exec -s workspace-write -C "$ROOT" -c 'model_reasoning_effort="high"' -o "{{job_dir}}/codex-cli-report.md" < "{{job_dir}}/codex-cli-packet.txt"
```

**Exit-code gate**：`codex exec` 非零退出（auth 失效 / network / 中斷）→ 停止並告知使用者：
「codex exec 失敗，請確認 `codex login` 或網路後重試。」**不可把失敗輸出當成實作成果**，
也不可跳到 Step 4 假裝有東西可以收。

clean exit 後讀 `{{job_dir}}/codex-cli-report.md`，那是 Codex 的自述報告。
**它只是待查核的宣稱，不是事實**——Step 4 才是事實。

## Step 4: 以 git 查核實際改動

**第一件事是把 Codex 的產出全部納入 git 視野**，包含新增檔案：

```bash
if ! git add -A; then echo '[FAIL] git add -A 失敗，staged 內容未涵蓋全部改動，不可繼續查核' >&2; exit 1; fi
```

**退出碼要檢查**：`git add -A` 會因 index.lock 競爭、權限、filter 失敗而非零退出，而失敗的
後果全部靜默——`git status --porcelain` 仍會列出那些檔（所以不會誤判 `BLOCKED`），但
`git diff --cached` 是空的（逐檔 review 讀到零行）、`git ls-files` 不含新檔（Step 5 的
`--all-files` CI 掃不到），最後報 `DONE`。

`git diff`（未加 `--cached`）與 `git diff --stat` 都**看不到 untracked 檔案**，而「新增檔案」
正是委託實作最常見的產出形狀（新 module + 新測試）。不先 `git add`，三件事會同時靜默失效：

1. 空判斷把**成功**的委託誤判成 `BLOCKED`
2. 逐檔 review 讀到零行新程式碼，卻回報「已讀完整 diff」
3. Step 5 的全量 CI 掃不到新檔——`CLAUDE.md` 原文：「`--all-files` means all files *git knows
   about* — an untracked new file is invisible to every hook, which then reports `Passed`
   because it never looked. … **`git add` first, then `make ci`.**」

Step 0.4 已保證出發時工作區乾淨，所以 `git add -A` 之後 staged 的內容**就是** Codex 的改動。
本 skill 仍然不 commit——staged 只是讓 git 與 CI 看得見。

```bash
git status --porcelain
```

```bash
git diff --cached --stat
```

| 狀況 | 動作 |
|------|------|
| `git status --porcelain` 為空，但 Codex 報告宣稱完成 | **`BLOCKED`**：回報「Codex 宣稱完成但工作樹沒有任何改動」，附上它的報告全文讓使用者判斷 context 缺什麼。**不可宣稱成功** |
| `git status --porcelain` 非空，但 `git diff --cached --stat` 為空 | **停止**：staging 未生效（上一步的 gate 應已擋下）。**不可**把空 diff 當成「已讀完整 diff」——那會讓整輪 review 與 CI 都掃不到 Codex 的產出 |
| 改動觸及 brief `## Out of scope` 列的檔案 | 在 Step 6 當成 finding 回饋，要求還原 |
| 其他 | 繼續 |

空判斷用 `git status --porcelain` 而不是 diff：它是唯一一個 untracked 與 tracked 都看得到的
探針，也就是唯一能回答「Codex 到底有沒有動過東西」的那個。

接著用 Read tool 讀 `git diff --cached` 的**完整**輸出（不是只看 `--stat`），逐檔檢視。
Codex 報告裡的 `## Rules consulted` 若與 Step 2 的清單有落差，記為 finding。

## Step 5: 跑全量 CI

執行 Step 0.5 決定的 `{{ci_command}}`。**不要接 `| tail`／`| head`**——pipeline 的 exit code
取自最後一段，會把失敗讀成成功（`.claude/rules/13`）。

**Step 0.5 若沒能定出全量 CI 指令**（`[WARN] 找不到全量 CI 指令`，使用者也未指定），這一步
無事可做：直接把最終狀態上限壓在 `DONE_WITH_CONCERNS`，並在報告的驗收欄寫
「未執行（找不到全量 CI 指令）」。**不可**因為「沒有 finding」就報 `DONE`——沒跑過的驗收
不是通過的驗收。

CI 通過後**還要再看一次工作樹**：

```bash
git status --porcelain
```

Step 4 已經 `git add -A`，所以 staged 的是 Codex 的改動，而這裡**尚未 staged 的項目**精確等於
「CI 過程中新產生或被就地改寫的檔案」——兩者不會混淆。輸出非空是預期行為，但那些改動
**必須一併交付**，否則使用者 commit 出來的樹與你驗過的樹不同，CI 端必紅（PR #248 的實帳）。

**探針必須是 `git status --porcelain`，不能用 `git diff --name-only`**：後者只看 tracked 檔的
unstaged 變更，看不到 CI **新產生**的檔（coverage 報告、新的 lock 檔）。而下一行的
`git add -A` 會把那些 untracked 產物一起收進交付——於是它們進了 commit，卻從未出現在你
列給使用者的「被 CI 改過的檔案」清單裡。這與 Step 4 開頭的理由是同一條，只是方向相反。實測：

```console
$ git diff --name-only        # 漏掉 untracked
tracked.txt
$ git status --porcelain      # 兩種都看得到
 M tracked.txt
?? ci-artifact.txt
```

把它們收進來後再往下：

```bash
if ! git add -A; then echo '[FAIL] git add -A 失敗，CI 產生的改動未納入交付' >&2; exit 1; fi
```

在最終報告明確列出哪些檔被 CI 新增或改寫（以上面 `git status --porcelain` 的輸出為準，
不要只列 formatter 改的那些）。

CI 失敗 → 把失敗輸出當成 finding，進入 Step 6。

## Step 6: 回修迴圈（最多 2 輪）

Claude 自己的 review finding 加上 CI 失敗輸出，逐字回饋給 Codex。**不要摘要 finding**——
摘要會丟掉 Codex 修正所需的細節。

用 Write tool 寫 `{{job_dir}}/codex-cli-fix-brief.md`：

```text
## Context

Your previous change is already in the working tree. Do not start over; fix only the findings
below. Everything from the original contract still applies.

## Findings to fix

<逐條 finding，原文照貼；CI 失敗貼失敗輸出>

## Verification

Re-run {{ci_command}} and confirm it passes.
```

重新組 packet 並派工（同 Step 3 的形式，換 brief 檔名）。**Step 3 的兩端斷言在這裡同樣適用**
——回修輪同樣是一次 `-s workspace-write` 派工，少了契約一樣是零邊界，少了 findings 則是
一次沒有任務的派工：

```bash
if [ ! -r "{{job_dir}}/codex-cli-fix-brief.md" ]; then echo '[FAIL] 找不到 fix brief' >&2; exit 1; fi
if ! cat "{{skill_root}}/contract.md" "{{job_dir}}/codex-cli-fix-brief.md" > "{{job_dir}}/codex-cli-fix-packet.txt"; then echo '[FAIL] fix packet 組裝失敗' >&2; exit 1; fi
```

```bash
head -1 "{{job_dir}}/codex-cli-fix-packet.txt"
```

```bash
grep -c '^## Findings to fix' "{{job_dir}}/codex-cli-fix-packet.txt"
```

第一個輸出不是 `# Codex Delegation Contract`，或第二個輸出是 `0` → **停止**，不可派工。

第二端斷言的字串是 `## Findings to fix` 而**不是** Step 3 的 `## Task`——fix brief 用的是
不同的 section 名稱，照抄 Step 3 的字串會讓這道 gate 永遠回 `0`、永遠擋下合法的回修輪。

```bash
ROOT=$(git rev-parse --show-toplevel)
codex exec -s workspace-write -C "$ROOT" -c 'model_reasoning_effort="high"' -o "{{job_dir}}/codex-cli-fix-report.md" < "{{job_dir}}/codex-cli-fix-packet.txt"
```

回修不使用 `codex exec resume`：packet 自足、不依賴 session 狀態，與「Codex 沒有對話歷史」
的前提一致，也避免 `--last` 撿到別的 session。

每輪結束回到 Step 4 重新查核。**最多 2 輪**——第 2 輪後仍有未解 finding 就停止，
不再迴圈，狀態為 `DONE_WITH_CONCERNS`。

## Step 7: 報告

```text
CODEX DELEGATION REPORT
Task: <一句話重述任務>
Rounds: <實際跑了幾輪 codex exec>

--- 改動 ---
<git diff --stat 輸出，加上每個檔案的一句話說明>

--- 規則涵蓋 ---
<Step 2 列出的必讀 rule；Codex 聲稱讀了哪些；有落差就明講>

--- 驗收 ---
指令：{{ci_command}}
結果：<PASS / FAIL + 關鍵輸出>
Formatter 改寫：<被 CI 就地改過的檔案清單，或「無」>

--- 未解 finding ---
<逐條列出，或「無」>

STATUS: DONE | DONE_WITH_CONCERNS | BLOCKED
下一步：<例如「review diff 後 commit」——本 skill 不做 commit / push / PR>
```

`STATUS` 判定：

| 狀態 | 條件 |
|------|------|
| `DONE` | **全量 CI 實際執行過且全綠**，且無未解 finding |
| `DONE_WITH_CONCERNS` | 有改動但仍有未解 finding；或 2 輪後仍未收斂；**或全量 CI 根本沒得跑**（Step 0.5 找不到指令） |
| `BLOCKED` | Codex 沒產生改動、`codex exec` 失敗、或 CI 始終無法通過 |

`DONE` 要求 CI **跑過**而不只是「沒有失敗」——沒跑過的驗收不是通過的驗收，這兩者在報告裡
讀起來一樣，但意思完全不同。不可為了讓報告好看而把 `DONE_WITH_CONCERNS` 寫成 `DONE`。

---

## 建議的 allow-list 條目

依 `.claude/rules/16` 的「動詞鎖在前綴、只在尾端用萬用字元」原則，**只有 rule picker 這一條**
適合永久 allow-list：

```json
"Bash(python3 /Users/<you>/.claude/plugins/cache/yibi-stack/3rd-tools/<ver>/skills/codex-cli/scripts/select_rules.py *)"
```

把 `/Users/<you>/...` 換成 Step 0.6 實際輸出的 `{{skill_root}}`——`~` 在 `Bash()` pattern 裡
**不展開**（rule 16），一條寫 `/Users/<you>/...` 的條目對一個以 `~/...` 呼叫的指令永遠不匹配，
條目形同虛設、每次照樣跳確認框。Step 2 的指令已改用 `{{skill_root}}` 的絕對路徑形式，兩邊
因此可以對上；但 plugin 升版會換掉路徑中的版本號，屆時要一併更新這個條目。

**不要 allow-list `Bash(codex exec:*)`**。它只鎖動詞、`-s` 的值完全不受限，接受之後
以下兩種呼叫都不再跳確認框：

```console
$ codex exec --help | grep -A3 'sandbox'
  -s, --sandbox <SANDBOX_MODE>
          [possible values: read-only, workspace-write, danger-full-access]
      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY DANGEROUS.
```

這是 rule 16 的 Red Flag 2（verb-level wildcard），而 `codex exec` 既非 read-only 也非固定
script path，不符合該規則列出的任何一種安全形式。本 skill 唯一擋在「把工作樹交給外部模型」
之前的互動檢查點就是那個確認框——**建議保留每次確認**。repo 內既有的三條 Codex 路徑
（`codex-consult` / `codex-review` / `pr-cycle-deep`，全為 `-s read-only`）也從未建議過任何
`codex exec` 的 allow-list 條目。

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| Step 0.4 擋住，但那些改動是我要保留的 | `git stash`，派工驗收完再 `git stash pop` |
| Codex 改了 `## Out of scope` 列的**既有**檔案 | `git checkout HEAD -- <path>`（**不是** `git checkout -- <path>`，見下方說明），或在 Step 6 要求它還原 |
| Codex 新增了 `## Out of scope` 範圍外的**新**檔案 | `git rm -f --cached <path>` 後再刪檔；`git checkout HEAD -- <path>` 對 HEAD 中不存在的路徑會 rc=1 且還原不了任何東西 |
| Codex 報告說讀了 rule，但 diff 看起來沒遵守 | 以 diff 為準記為 finding；Codex 的自述不是證據 |
| 想中途看 Codex 在做什麼 | `codex exec` 是同步的，跑完才回；要即時觀察請改用互動式 `codex` |

### 為什麼還原一定要用 `git checkout HEAD --`

Step 4 的第一個動作就是 `git add -A`，而 out-of-scope 的偵測發生在那之後。此時 index 裡
**已經是 Codex 的版本**，而 bare `git checkout -- <path>` 讀的正是 index——它會把 Codex 的
內容再複製回工作樹一次，rc=0、無任何輸出。使用者以為還原了，檔案其實原封不動，接著就
把 out-of-scope 改動 commit 出去。實測：

```console
$ git add -A && git status --porcelain
M  out_of_scope.txt
$ git checkout -- out_of_scope.txt ; echo "rc=$?" ; cat out_of_scope.txt
rc=0
codex-edit                      # 未還原，且完全靜默
$ git checkout HEAD -- out_of_scope.txt ; cat out_of_scope.txt
original                        # 還原成功
```

這條與 `.claude/rules/15-irreversible-operations.md` 的 recovery 段落一致：

> **Recovery: use `git checkout HEAD -- <path>`, not `git checkout -- <path>`.** The bare form
> reads the **index**, not HEAD

同一份 recovery 表也記載了本節第二列的例外：staged add（HEAD 中不存在的新檔）用
`checkout HEAD --` 會失敗，只能從 index 移除後刪檔。
