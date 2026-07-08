---
name: pr-cycle-fast
type: exec
scope: global
description: PR 生命週期自動化 orchestrator（快速版）：偵測 open PR、並行 code review + CI monitor + conflict detect、auto-fix markdownlint/CI、merge 後自動觸發 /pr-retro 寫 mycelium、最後 /clean-merged。支援中斷後 resume。小型 PR 或追求快速 lifecycle 首選；大型 PR 或 SDD 專案請改用 /pr-cycle-deep。
---

# /pr-cycle-fast — PR Lifecycle Orchestrator (Fast)

## Usage

```text
/pr-cycle-fast              # 自動偵測目前分支的 open PR，從頭執行
/pr-cycle-fast resume       # 讀取最新 state file，從上次中斷點繼續
/pr-cycle-fast --pr <n>     # 明確指定 PR 號碼
/pr-cycle-fast status       # 顯示目前 state
```

## Steps

### Step 0 — Environment Check

確認 SKILL_REPO 與工具可用：

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; c=json.loads((pathlib.Path.home()/".agents"/"config.json").read_text()); print((c.get("skill_repos") or {}).get("yibi-stack") or c.get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定' >&2; exit 1; fi
```

擷取**目標 repo** 的 checkout 路徑（即目前 session 的 cwd，如 yibi-mvp）：

```bash
REPO_ROOT="$PWD"
```

> **為什麼需要 `REPO_ROOT`**：Step 1 用 `uv run --directory "$SKILL_REPO"` 才能 import
> `tasks.pr_orchestrator`（module 只在 skill repo），但 `--directory` 會把子行程 cwd 換成
> **skill repo**。orchestrator 內的 `git branch --show-current` 只認 cwd 底下的 checkout，
> 也不吃 `GH_REPO`（那是 gh 的遠端 slug，不是本地路徑），若不傳 `--repo-root` 就會誤讀成
> skill repo 的分支。務必用 `--repo-root "$REPO_ROOT"` 明確指向目標 repo。

確認 `gh`、`git`、`uv` 可用：

```bash
gh --version
uv --version
```

若任一失敗：`[FAIL] 缺少必要工具，請先安裝` >&2，停止。

### Step 1 — Detect or Resume

**auto-detect（無引數）**：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator detect --repo-root "$REPO_ROOT"
```

`--repo-root "$REPO_ROOT"` 讓 branch/gh 偵測回到目標 repo（見 Step 0 說明）。
明確指定 PR 時同樣帶上：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator detect --pr {{pr_number}} --repo-root "$REPO_ROOT"
```

若失敗（多 PR 同分支）：停止，告訴 user 加 `--pr <n>` 重跑。

**resume**：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator resume
```

輸出 PR 號碼與當前 state。若無 active state 檔案：停止並提示先執行 detect。

**讀取 state**：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator status
```

將輸出 JSON 的 `current_state` 存入變數，依此進入對應步驟。

### Step 2 — Execute Current-State Action

依 `current_state` 執行對應動作：

| current_state | 動作 |
|--------------|------|
| `DETECTED` | 轉到 Step 3（dispatch review subagents） |
| `REVIEWING` | 讀取 spawn-manifest（Step 3），dispatch 三個並行 subagent |
| `REVIEW_DONE` | 轉到 CI_WAIT（`--to CI_WAIT`），再進 Step 4 |
| `CI_WAIT` | 輪詢 CI（Step 4） |
| `AUTO_FIX` | 執行 auto-fix（Step 5） |
| `CI_PASS` | transition to MERGEABLE（`--to MERGEABLE`），再進 Step 6 |
| `MERGEABLE` | 等待 user 確認 merge（Step 6） |
| `MERGED` | 執行 retro（Step 7） |
| `RETRO_DONE` | 執行 clean（Step 8） |
| `CLEANED` | 完成，報告給 user |
| `BLOCKED` | 顯示所有 blockers，等待 user 解除後 `/pr-cycle-fast resume` |
| `FAILED` | 顯示錯誤，等待人工介入 |

transition 後讀取新 state，自動循環推進，直到 BLOCKED / FAILED / CLEANED / MERGEABLE 停下等待 user。

### Step 3 — Dispatch Review Subagents (DETECTED → REVIEWING)

先 transition 到 REVIEWING：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to REVIEWING --reason "spawning review subagents"
```

寫出 spawn-manifest（用 `write-manifest` 明確觸發）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator write-manifest --pr {{pr_number}}
```

讀取 manifest 路徑（來自 status JSON 的 `artifacts.spawn_manifest`），然後**在同一個 message 內**用 Task tool 一次 dispatch 三個並行 subagent：

> **重要**：所有三個 subagent 必須在同一個 message 中 dispatch（一個 Task tool call 一個），不得拆成多個 turn。

1. **code-review subagent**（`pr-review-toolkit:code-reviewer`）：review PR #{pr_number}，結果寫到 `$REVIEW_DIR`
2. **ci-monitor subagent**（`general-purpose`）：`gh pr checks {{pr_number}} --watch`，完成後回傳 CI_PASS 或 CI_FAIL
3. **conflict-detector subagent**（`general-purpose`）：`gh pr view {{pr_number}} --json mergeable,mergeStateStatus`，回傳 OK 或 CONFLICT

> **若 `pr-review-toolkit:code-reviewer` 不可用**（本專案未安裝外部 pr-review-toolkit plugin）：
> `[WARN]` 改用內建 `/code-review` skill（或 `general-purpose` subagent）執行 report-only code review，
> 並提示使用者安裝以取得完整 review：
> `claude plugin marketplace add anthropics/claude-plugins-official && claude plugin install pr-review-toolkit@claude-plugins-official`。
> ci-monitor / conflict-detector 用內建 `general-purpose`，不受影響。

等待所有三個 subagent 完成後：

- 若有 CONFLICT → transition `CONFLICT` → `BLOCKED`（等人工解）
- 若 code-review 完成 → transition `REVIEWING` → `REVIEW_DONE`
- 再 transition → `CI_WAIT`（Step 4）

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to REVIEW_DONE --reason "all reviewers done"
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to CI_WAIT --reason "entering CI wait"
```

### Step 4 — CI Monitor (CI_WAIT)

ci-monitor subagent 的結果決定下一步：

- `CI_PASS` → transition `CI_WAIT → CI_PASS → MERGEABLE`
- `CI_FAIL` → transition `CI_WAIT → AUTO_FIX`（Step 5）
- `CONFLICT` → transition `CI_WAIT → CONFLICT → BLOCKED`

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to {{next_state}} --reason "{{reason}}"
```

若 CI_PASS：再 transition → MERGEABLE，停下等待 user ship 確認（Step 6）。

### Step 5 — Auto-Fix Loop (AUTO_FIX)

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator status --pr {{pr_number}}
```

> **注意**：auto-fix loop 由 Python CLI 內部管理（`tasks.pr_orchestrator.auto_fix.run()`），skill 只需觸發並等待結果。若 state 回到 CI_WAIT → 回到 Step 4；若 BLOCKED → 顯示 blockers 給 user。

明確觸發方式（transition 到 AUTO_FIX 後執行）：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator auto-fix --pr {{pr_number}} --repo-root "$REPO_ROOT"
```

> **務必帶 `--repo-root "$REPO_ROOT"`**：省略時 `auto-fix` 會 fallback 到 `os.getcwd()`
> ＝ skill repo（因 `--directory` 換了子行程 cwd），auto-fix 的 `git add/commit/push`
> 與 fork 安全檢查、diff 範圍都會作用在 skill repo 而非目標 repo——這是比 detect 更危險的
> wrong-repo `git push`。與 Step 1 同源。

### Step 6 — Ship Gate (MERGEABLE)

⚠️ **Irreversible Operation（Rule 15）**：`gh pr merge` 是不可逆操作。

顯示給 user：

```text
PR #{{pr_number}} 已通過 code review 與 CI。
準備 merge：gh pr merge {{pr_number}} --squash --delete-branch
請確認後手動執行，或輸入 "ship" 確認由 skill 代為執行。
```

若 user 確認後執行：

```bash
gh pr merge {{pr_number}} --squash --delete-branch
```

> **若 repo 裝有 protect-push 等 PreToolUse hook 擋下 `gh pr merge`**：skill 無法代跑，
> 請 user 自行執行 `! gh pr merge {{pr_number}} --squash --delete-branch`，
> 且需從**主 repo 目錄**執行（linked worktree 內會 `'main' is already used by worktree` 失敗）。
> user 手動 merge 完成後，繼續執行下方 transition。

若成功，transition MERGEABLE → MERGED：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to MERGED --reason "user confirmed merge"
```

### Step 7 — Retro (MERGED → RETRO_DONE)

在同一 session 內觸發 `/pr-retro`：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to RETRO_DONE --reason "pr-retro completed"
```

> 實際執行：在此 step 前，先完整跑完 `/pr-retro`（包含 Step 4b typed lessons add），完成後才 transition 到 RETRO_DONE。

### Step 8 — Clean (RETRO_DONE → CLEANED)

在同一 session 內觸發 `/clean-merged`，清除已 merge 的分支與 worktree。

完成後 transition：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator transition --pr {{pr_number}} --to CLEANED --reason "clean-merged done"
```

State file 從 `.runtime/pr_orchestrator/` 搬到 `~/.claude/pr_orchestrator/<repo>/` 歸檔（Python CLI 自動處理）。

### Step 9 — Report

顯示完整 transition log：

```bash
uv run --directory "$SKILL_REPO" python -m tasks.pr_orchestrator log-view --pr {{pr_number}}
```

回報：PR 號碼、merge commit、retro handover ID、clean 結果。

## State Machine（速查）

```text
DETECTED → REVIEWING → REVIEW_DONE → CI_WAIT → CI_PASS → MERGEABLE
                                        ↕
                                     AUTO_FIX (≤3 次)
MERGED → RETRO_DONE → CLEANED
CONFLICT → BLOCKED（人工解）
FAILED（terminal）
```

## Interrupt & Resume

任何時候 session 中斷，state file 保留在 `.runtime/pr_orchestrator/<pr>.json`。
重新開 session 後執行 `/pr-cycle-fast resume` 即可從上次 state 接續。

## 注意事項

- **Subagent in-session-only**：CI monitor subagent 需要 active session；關閉 session 後 polling 停止。Resume 後 skill 會重新 dispatch ci-monitor。
- **Fork PR**：auto-fix 預設拒絕外部 fork PR（`allow_fork_fix=false`）。
- **多 PR 同分支**：`gh pr list --head` 回 ≥2 時 fail-loud，需 `--pr <n>`。

## FAQ

| 問題 | 修復方式 |
|------|---------|
| `[FAIL] skill_repo 未設定` | 在 yibi-stack 目錄執行 `make install` |
| `分支沒有對應的 open PR` | 先 `gh pr create` 建立 PR |
| `多個 PR 對應同分支` | 加 `--pr <n>` 明確指定 |
| State 停在 BLOCKED | 看 blockers 訊息，解除後跑 `/pr-cycle-fast resume` |
| auto-fix 超過 3 次上限 | 手動修 CI 失敗後 push，再跑 `/pr-cycle-fast resume` |
| merge 後找不到 state | 查 `~/.claude/pr_orchestrator/<repo>/` 歸檔 |
