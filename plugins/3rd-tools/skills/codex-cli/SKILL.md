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
git status --porcelain
```

**輸出非空即停止**，並告知使用者：「工作區有未提交的改動，請先 commit 或 stash——否則收貨時
無法分辨哪些改動是 Codex 做的。」

這道 gate 是 Step 4 收貨查核的前提：只有從乾淨狀態出發，`git diff` 才等於「Codex 的改動」。

## Step 0.5: 偵測 repo 的全量 CI 指令

```bash
git ls-files Makefile .pre-commit-config.yaml package.json
```

若上一步輸出含 `Makefile`：

```bash
grep -n '^ci:' Makefile
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

Exit code 語意：

- **exit 0 + stdout 有內容** → 把輸出原樣接到 brief 末端（見下一步）
- **exit 0 + stderr 有 `[WARN]`** → 該 repo 沒有 `.claude/rules/`，或沒有規則匹配。
  繼續執行，但要在最終報告告訴使用者「這次派工只有 contract 的通用約束」
- **exit 2** → repo root 解析錯誤，停止並回報

把 picker 的輸出用 Write tool 追加到 brief 的 `## Rules you must read` 區段下，格式：

```text
## Rules you must read

<picker 的輸出原樣貼上>

Read each file listed above before you start. Name them in your "## Rules consulted" section.
```

## Step 3: 組 packet 並派工

契約與 brief 合併成 packet（契約在前，brief 在後）：

```bash
cat ~/.agents/skills/codex-cli/contract.md "$CLAUDE_JOB_DIR/codex-cli-brief.md" > "$CLAUDE_JOB_DIR/codex-cli-packet.txt"
```

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

```bash
git status --short
```

```bash
git diff --stat
```

| 狀況 | 動作 |
|------|------|
| diff 為空，但 Codex 報告宣稱完成 | **`BLOCKED`**：回報「Codex 宣稱完成但工作樹沒有任何改動」，附上它的報告全文讓使用者判斷 context 缺什麼。**不可宣稱成功** |
| diff 動到 brief `## Out of scope` 列的檔案 | 在 Step 6 當成 finding 回饋，要求還原 |
| diff 含 `.git/` 以外的預期改動 | 繼續 |

接著用 Read tool 讀**完整** diff（不是只看 `--stat`），逐檔檢視。Codex 報告裡的
`## Rules consulted` 若與 Step 2 的清單有落差，記為 finding。

## Step 5: 跑全量 CI

執行 Step 0.5 決定的 `{{ci_command}}`。**不要接 `| tail`／`| head`**——pipeline 的 exit code
取自最後一段，會把失敗讀成成功（`.claude/rules/13`）。

CI 通過後**還要再看一次工作樹**：

```bash
git diff --name-only
```

輸出非空 → 表示 CI 過程中有 formatter 就地改了檔（`ruff-format`、`trailing-whitespace` 等）。
這是預期行為，但那些改寫**必須一併留在工作樹交付**，否則使用者 commit 出來的樹與你驗過的樹
不同，CI 端必紅。在最終報告明確說明哪些檔被 formatter 改過。

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

重新組 packet 並派工（同 Step 3 的形式，換 brief 檔名）：

```bash
cat ~/.agents/skills/codex-cli/contract.md "$CLAUDE_JOB_DIR/codex-cli-fix-brief.md" > "$CLAUDE_JOB_DIR/codex-cli-fix-packet.txt"
```

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
| `DONE` | CI 全綠且無未解 finding |
| `DONE_WITH_CONCERNS` | 有改動且 CI 綠，但仍有未解 finding；或 2 輪後仍未收斂 |
| `BLOCKED` | Codex 沒產生改動、`codex exec` 失敗、或 CI 始終無法通過 |

不可為了讓報告好看而把 `DONE_WITH_CONCERNS` 寫成 `DONE`。

---

## 建議的 allow-list 條目

依 `.claude/rules/16` 的「動詞鎖在前綴、只在尾端用萬用字元」原則：

```json
"Bash(python3 /Users/<you>/.agents/skills/codex-cli/scripts/select_rules.py *)",
"Bash(codex exec:*)"
```

## 常見問題

| 問題 | 解法 |
|------|------|
| Codex CLI 未找到 | `npm install -g @openai/codex` |
| auth 失敗 | `codex login` 或設定 `CODEX_API_KEY` / `OPENAI_API_KEY` |
| Step 0.4 擋住，但那些改動是我要保留的 | `git stash`，派工驗收完再 `git stash pop` |
| Codex 動了 `## Out of scope` 的檔案 | 用 `git checkout -- <path>` 還原該檔（確認沒有你要的改動再做），或在 Step 6 要求它還原 |
| Codex 報告說讀了 rule，但 diff 看起來沒遵守 | 以 diff 為準記為 finding；Codex 的自述不是證據 |
| 想中途看 Codex 在做什麼 | `codex exec` 是同步的，跑完才回；要即時觀察請改用互動式 `codex` |
