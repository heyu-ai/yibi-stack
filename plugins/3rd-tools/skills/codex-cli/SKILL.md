---
name: codex-cli
type: tool
scope: global
description: 讓 Claude 規劃工作、分派 OpenAI Codex CLI 實際寫 code（-s workspace-write），再由 Claude 收貨驗收：查 git diff、跑全量 CI、把 finding 回饋給 Codex 修（最多 2 輪）。派工前會把 repo 的 CLAUDE.md 與 .claude/rules/ 規範打包給 Codex。觸發：codex 實作, 派給 codex 寫, 委託 codex, 讓 codex 做, delegate to codex, codex 幫我改這個功能。只想問 Codex 技術問題、沒有 code 要寫請改用 /codex-consult；只想 review 現成 diff 請改用 /codex-review；要多個外部模型 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep。
---

# /codex-cli — 委託 Codex 實作並驗收

Claude 規劃 → Codex 寫 code → Claude 驗收。與同家族兩個 skill 的差別在於 sandbox 模式：
`/codex-consult` 與 `/codex-review` 都是 `-s read-only`，Codex 不能改檔；本 skill 用
`-s workspace-write`，Codex 會真的動你的工作樹。

設計決策與被否決方案見 `docs/codex-cli-delegation-plan.md`。

**本 skill 不做 commit / push / PR** — 改動留在工作樹，由使用者或 `/pr-cycle-*` 接手。

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
if ! git status --porcelain; then echo '[FAIL] git status 失敗，無法確認工作區狀態' >&2; exit 1; fi
```

**輸出非空即停止**，並告知使用者：「工作區有未提交的改動，請先 commit 或 stash——否則收貨時
無法分辨哪些改動是 Codex 做的。」

`if !` 不可省：`git status` 無輸出**且非零退出**（repo 損壞、權限問題）會被讀成「乾淨」，
於是在一個壞掉的 repo 上開啟 workspace-write。無輸出必須先確認是「成功且乾淨」才算過。

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

---

## Step 1: Claude 規劃並寫 brief

Codex 沒有本次對話的任何歷史，packet 必須自足。先用 Read / Grep / Glob 讀懂相關程式碼，
再用 Write tool 把 brief 寫入 `$CLAUDE_JOB_DIR/codex-cli-brief.md`，內容至少涵蓋：

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
python3 ~/.agents/skills/codex-cli/scripts/select_rules.py --repo-root "$ROOT" tasks/foo/db.py
```

把最後一個參數換成本次實際會碰到的路徑（可給多個，空白分隔）。

Exit code 與 stderr 語意（每個 `[WARN]` 各有獨立成因，不可混為一談）：

| 結果 | 意義 | 動作 |
|------|------|------|
| exit 0，stdout 有內容，stderr 空 | 正常 | 把輸出原樣接到 brief 末端（見下一步） |
| exit 0 + `[WARN] ... 沒有 .claude/rules/` | 目標 repo 無規則目錄 | 繼續，但最終報告要說明「這次派工只有 contract 的通用約束」 |
| exit 0 + `[WARN] ... 沒有命中任何 path-scoped rule` | 給的路徑全數落空（多半是拼錯或給了絕對路徑） | **停下來檢查路徑**再重跑——packet 會缺少該檔案適用的規範 |
| exit 0 + `[WARN] <rule> 有 paths: key 但解析不出任何 pattern` | 該 rule 的 `paths:` 寫法無法解析 | 繼續，但在報告點名該 rule，並回頭修它的 frontmatter |
| exit 0 + `[WARN] 無法讀取 <rule>` | 個別 rule 檔讀取失敗 | 繼續，但在報告點名該 rule |
| exit 2 + stderr 含 `repo root 不存在` | repo root 解析錯誤 | 停止並回報 |
| exit 2 + stderr 含 `can't open file` | skill 未安裝（`~/.agents/skills/codex-cli/` 不存在） | 停止：「請在 yibi-stack 目錄執行 `make install`」 |

把 picker 的輸出用 Write tool 追加到 brief 的 `## Rules you must read` 區段下，格式：

```text
## Rules you must read

<picker 的輸出原樣貼上>

Read each file listed above before you start. Name them in your "## Rules consulted" section.
```

## Step 3: 組 packet 並派工

**先 gate 契約檔存在**，再合併（契約在前，brief 在後）：

```bash
if [ ! -f "$HOME/.agents/skills/codex-cli/contract.md" ]; then echo '[FAIL] 找不到 contract.md，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
```

這道 gate 不可省，而且**不能靠 `cat` 的退出碼補救**：`>` 會先把輸出檔建出來，`cat` 缺檔時
只印一行 stderr 並非零退出，**packet 仍然生成，只含 brief**。實測：

```console
$ if ! cat /nonexistent/contract.md /etc/hosts > probe.txt 2>&1; then echo "cat: NON-ZERO EXIT"; fi
cat: NON-ZERO EXIT
$ wc -c probe.txt
398 probe.txt          # 檔案照樣建立，只含第二個來源
```

沒有這道 gate，一個照 `claude plugin install 3rd-tools@yibi-stack` 安裝、從未跑過
`make install` 的使用者（`~/.agents/skills/` 不存在），會在**零邊界**下把 workspace write
交給 Codex——四個禁讀前綴、禁止 git 操作、語言規範、全量 CI 要求全部消失，而且無聲。

```bash
cat ~/.agents/skills/codex-cli/contract.md "$CLAUDE_JOB_DIR/codex-cli-brief.md" > "$CLAUDE_JOB_DIR/codex-cli-packet.txt"
```

派工前再確認 packet 真的以契約開頭：

```bash
head -1 "$CLAUDE_JOB_DIR/codex-cli-packet.txt"
```

輸出不是 `# Codex Delegation Contract` → **停止**，不可派工。

執行（repo root 在同一個 bash block 解析進 `ROOT`，以 `"$ROOT"` 傳入；**不用 placeholder 替換**，
避免 checkout 路徑含特殊字元時逸出；**不用 `timeout`**，stock macOS 沒有這個指令）：

```bash
ROOT=$(git rev-parse --show-toplevel)
codex exec -s workspace-write -C "$ROOT" -c 'model_reasoning_effort="high"' -o "$CLAUDE_JOB_DIR/codex-cli-report.md" < "$CLAUDE_JOB_DIR/codex-cli-packet.txt"
```

**Exit-code gate**：`codex exec` 非零退出（auth 失效 / network / 中斷）→ 停止並告知使用者：
「codex exec 失敗，請確認 `codex login` 或網路後重試。」**不可把失敗輸出當成實作成果**，
也不可跳到 Step 4 假裝有東西可以收。

clean exit 後讀 `$CLAUDE_JOB_DIR/codex-cli-report.md`，那是 Codex 的自述報告。
**它只是待查核的宣稱，不是事實**——Step 4 才是事實。

## Step 4: 以 git 查核實際改動

**第一件事是把 Codex 的產出全部納入 git 視野**，包含新增檔案：

```bash
git add -A
```

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
git diff --name-only
```

Step 4 已經 `git add -A`，所以 staged 的是 Codex 的改動，而這裡的 **unstaged** diff 精確等於
「CI 過程中被就地改寫的檔案」（`ruff-format`、`trailing-whitespace` 等）——兩者不會混淆。
輸出非空是預期行為，但那些改寫**必須一併交付**，否則使用者 commit 出來的樹與你驗過的樹不同，
CI 端必紅（PR #248 的實帳）。把它們收進來後再往下：

```bash
git add -A
```

在最終報告明確列出哪些檔被 formatter 改過。

CI 失敗 → 把失敗輸出當成 finding，進入 Step 6。

## Step 6: 回修迴圈（最多 2 輪）

Claude 自己的 review finding 加上 CI 失敗輸出，逐字回饋給 Codex。**不要摘要 finding**——
摘要會丟掉 Codex 修正所需的細節。

用 Write tool 寫 `$CLAUDE_JOB_DIR/codex-cli-fix-brief.md`：

```text
## Context

Your previous change is already in the working tree. Do not start over; fix only the findings
below. Everything from the original contract still applies.

## Findings to fix

<逐條 finding，原文照貼；CI 失敗貼失敗輸出>

## Verification

Re-run {{ci_command}} and confirm it passes.
```

重新組 packet 並派工（同 Step 3 的形式，換 brief 檔名）。**Step 3 的契約存在 gate 與
`head -1` 斷言在這裡同樣適用**——回修輪同樣是一次 `-s workspace-write` 派工，少了契約
一樣是零邊界：

```bash
if [ ! -f "$HOME/.agents/skills/codex-cli/contract.md" ]; then echo '[FAIL] 找不到 contract.md，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
```

```bash
cat ~/.agents/skills/codex-cli/contract.md "$CLAUDE_JOB_DIR/codex-cli-fix-brief.md" > "$CLAUDE_JOB_DIR/codex-cli-fix-packet.txt"
```

```bash
head -1 "$CLAUDE_JOB_DIR/codex-cli-fix-packet.txt"
```

輸出不是 `# Codex Delegation Contract` → **停止**，不可派工。

```bash
ROOT=$(git rev-parse --show-toplevel)
codex exec -s workspace-write -C "$ROOT" -c 'model_reasoning_effort="high"' -o "$CLAUDE_JOB_DIR/codex-cli-fix-report.md" < "$CLAUDE_JOB_DIR/codex-cli-fix-packet.txt"
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

依 `.claude/rules/16` 的「動詞鎖在前綴、只在尾端用萬用字元」原則：

```json
"Bash(python3 /Users/<you>/.agents/skills/codex-cli/scripts/select_rules.py *)",
"Bash(codex exec:*)"
```

**要讓第一條真的命中，Step 2 的指令必須寫成同一個絕對路徑**——`~` 在 `Bash()` pattern 裡
不展開（rule 16），所以一條寫 `/Users/<you>/...` 的 allow-list 條目對一個以 `~/...` 呼叫的
指令永遠不匹配，結果是條目形同虛設、每次照樣跳確認框。要嘛把 Step 2 的指令改寫成絕對路徑，
要嘛接受每次確認。

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| Step 0.4 擋住，但那些改動是我要保留的 | `git stash`，派工驗收完再 `git stash pop` |
| Codex 動了 `## Out of scope` 的檔案 | 用 `git checkout -- <path>` 還原該檔（確認沒有你要的改動再做），或在 Step 6 要求它還原 |
| Codex 報告說讀了 rule，但 diff 看起來沒遵守 | 以 diff 為準記為 finding；Codex 的自述不是證據 |
| 想中途看 Codex 在做什麼 | `codex exec` 是同步的，跑完才回；要即時觀察請改用互動式 `codex` |
