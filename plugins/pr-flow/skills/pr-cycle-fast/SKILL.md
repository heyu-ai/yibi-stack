---
name: pr-cycle-fast
type: exec
scope: global
description: PR 生命週期自動化 orchestrator（快速版）：偵測 open PR、並行 code review + CI monitor + conflict detect、auto-fix markdownlint/CI、merge 後自動觸發 /pr-retro 寫 mycelium、最後 /clean-wt。支援中斷後 resume。小型 PR 或追求快速 lifecycle 首選；大型 PR 或 SDD 專案請改用 /pr-cycle-deep；只需平行 code review、不要自動 merge / CI orchestration 請改用 /pr-review-cycle。
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

先定位本 skill 的 scripts 目錄（依序從目前生效的 plugin cache、`make install` symlink、
source checkout 定位，每個候選都直接檢查 script 可讀）：

```bash
PR_FLOW_CACHED=$(python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.claude'/'plugins'/'installed_plugins.json').read_text(encoding='utf-8')); print(next((e.get('installPath','') for e in d.get('plugins',{}).get('pr-flow@yibi-stack',[]) if e.get('installPath')), ''))" 2>/dev/null)
PCF_ROOT=""
if [ -r "${PR_FLOW_CACHED:-/nonexistent}/skills/pr-cycle-fast/scripts/check-cli-capability.sh" ]; then PCF_ROOT="$PR_FLOW_CACHED/skills/pr-cycle-fast"; elif [ -r "$HOME/.claude/skills/pr-cycle-fast/scripts/check-cli-capability.sh" ]; then PCF_ROOT="$HOME/.claude/skills/pr-cycle-fast"; elif [ -r "plugins/pr-flow/skills/pr-cycle-fast/scripts/check-cli-capability.sh" ]; then PCF_ROOT="plugins/pr-flow/skills/pr-cycle-fast"; fi
if ! test -n "$PCF_ROOT"; then echo "[FAIL] 讀不到 pr-cycle-fast check-cli-capability.sh；請執行 claude plugin install pr-flow@yibi-stack，或在 yibi-stack checkout 執行 make install" >&2; exit 1; fi
```

確認 installed CLI **具備本 skill 實際會呼叫的介面**——不是只確認它存在：

```bash
bash "$PCF_ROOT/scripts/check-cli-capability.sh"
```

Exit code 語義：

- **exit 0** — 介面齊備，繼續 Step 1
- **exit 1** — PATH 中沒有 `pr-orchestrator`（未安裝）→ 停止，照 stderr 的安裝指令執行
- **exit 2** — 已安裝但 `--help` 跑不起來（安裝損毀），或缺少 `--repo-root`（版本過舊）
  → 停止，照 stderr 的指令執行。兩者訊息不同且修法不同，不要互相套用

> **為什麼探能力而不是比版本**：`uv tool install git+...` 裝的是 HEAD，版本字串卻取自上次
> release 的 `pyproject.toml`，兩次 release 之間所有 commit 回報同一字串，semver 比對因此
> 無法區分「沒有漂移」與「偵測不到漂移」（issue #256、PR #249）。本 skill 已經知道自己要
> 呼叫 `--repo-root`，直接探測該能力即可，不需要任何版本號。

擷取**目標 repo** 的 checkout 路徑（即目前 session 的 cwd，如 yibi-mvp）：

```bash
REPO_ROOT="$PWD"
```

> **為什麼需要 `REPO_ROOT`**：installed `pr-orchestrator` 雖然從目標 repo 啟動，
> 仍務必用 `--repo-root "$REPO_ROOT"` 明確指定 Git/GitHub 與 auto-fix 的作用範圍，
> 不依賴 CLI process cwd 推斷目標 checkout。

確認 `gh`、`git` 可用：

```bash
if ! command -v gh >/dev/null 2>&1; then echo '[FAIL] 缺少必要工具 gh，請先安裝' >&2; exit 1; fi
if ! command -v git >/dev/null 2>&1; then echo '[FAIL] 缺少必要工具 git，請先安裝' >&2; exit 1; fi
```

若任一失敗：`[FAIL] 缺少必要工具，請先安裝` >&2，停止。

### Step 1 — Detect or Resume

**auto-detect（無引數）**：

```bash
pr-orchestrator detect --repo-root "$REPO_ROOT"
```

`--repo-root "$REPO_ROOT"` 讓 branch/gh 偵測回到目標 repo（見 Step 0 說明）。
明確指定 PR 時同樣帶上：

```bash
pr-orchestrator detect --pr {{pr_number}} --repo-root "$REPO_ROOT"
```

若失敗（多 PR 同分支）：停止，告訴 user 加 `--pr <n>` 重跑。

**resume**：

```bash
pr-orchestrator resume --repo-root "$REPO_ROOT"
```

輸出 PR 號碼與當前 state。若無 active state 檔案：停止並提示先執行 detect。

**讀取 state**：

```bash
pr-orchestrator status --repo-root "$REPO_ROOT"
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
pr-orchestrator transition --pr {{pr_number}} --to REVIEWING --reason "spawning review subagents" --repo-root "$REPO_ROOT"
```

寫出 spawn-manifest（用 `write-manifest` 明確觸發）：

```bash
pr-orchestrator write-manifest --pr {{pr_number}} --repo-root "$REPO_ROOT"
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
pr-orchestrator transition --pr {{pr_number}} --to REVIEW_DONE --reason "all reviewers done" --repo-root "$REPO_ROOT"
pr-orchestrator transition --pr {{pr_number}} --to CI_WAIT --reason "entering CI wait" --repo-root "$REPO_ROOT"
```

### Step 4 — CI Monitor (CI_WAIT)

ci-monitor subagent 的結果決定下一步：

- `CI_PASS` → transition `CI_WAIT → CI_PASS → MERGEABLE`
- `CI_FAIL` → transition `CI_WAIT → AUTO_FIX`（Step 5）
- `CONFLICT` → transition `CI_WAIT → CONFLICT → BLOCKED`

```bash
pr-orchestrator transition --pr {{pr_number}} --to {{next_state}} --reason "{{reason}}" --repo-root "$REPO_ROOT"
```

若 CI_PASS：再 transition → MERGEABLE，停下等待 user ship 確認（Step 6）。

### Step 5 — Auto-Fix Loop (AUTO_FIX)

```bash
pr-orchestrator status --pr {{pr_number}} --repo-root "$REPO_ROOT"
```

> **注意**：auto-fix loop 由 Python CLI 內部管理（`tasks.pr_orchestrator.auto_fix.run()`），skill 只需觸發並等待結果。若 state 回到 CI_WAIT → 回到 Step 4；若 BLOCKED → 顯示 blockers 給 user。

明確觸發方式（transition 到 AUTO_FIX 後執行）：

```bash
pr-orchestrator auto-fix --pr {{pr_number}} --repo-root "$REPO_ROOT"
```

> **務必帶 `--repo-root "$REPO_ROOT"`**：省略時 `auto-fix` 會 fallback 到 `os.getcwd()`。
> 顯式 target 可確保 `git add/commit/push`、fork 安全檢查與 diff 範圍都作用在目標 repo，
> 避免 wrong-repo `git push`。與 Step 1 同源。

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
pr-orchestrator transition --pr {{pr_number}} --to MERGED --reason "user confirmed merge" --repo-root "$REPO_ROOT"
```

### Step 7 — Retro (MERGED → RETRO_DONE)

在同一 session 內觸發 `/pr-retro`：

```bash
pr-orchestrator transition --pr {{pr_number}} --to RETRO_DONE --reason "pr-retro completed" --repo-root "$REPO_ROOT"
```

> 實際執行：在此 step 前，先完整跑完 `/pr-retro`（包含 Step 4b typed lessons add），完成後才 transition 到 RETRO_DONE。

### Step 8 — Clean (RETRO_DONE → CLEANED)

在同一 session 內觸發 `/clean-wt`，清除已 merge 的分支與 worktree。
`/clean-wt` 預設只報告；把它的 SAFE 清單呈現給使用者確認後，才用 `--apply` 實際刪除。

> **本 session 所在的 worktree 不會被清掉**：這個 step 通常就在剛合併完的 worktree 裡執行，
> 而該分支此刻剛好符合 SAFE 條件。`/clean-wt` 一律把**呼叫端所在的分支**歸為 KEEP——否則
> 它會把自己腳下的工作目錄連根移除（實測會讓 cwd 消失）。
> 要一併清掉這個 worktree，請在**主 repo** 目錄另外執行一次 `/clean-wt --apply`。

完成後 transition：

```bash
pr-orchestrator transition --pr {{pr_number}} --to CLEANED --reason "clean-wt done" --repo-root "$REPO_ROOT"
```

State file 從 `.runtime/pr_orchestrator/` 搬到 `~/.claude/pr_orchestrator/<repo>/` 歸檔（Python CLI 自動處理）。

### Step 9 — Report

顯示完整 transition log：

```bash
pr-orchestrator log-view --pr {{pr_number}} --repo-root "$REPO_ROOT"
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
| `[FAIL] 缺少 pr-orchestrator`（exit 1） | 執行 `uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"` |
| `[FAIL] 已安裝的 pr-orchestrator 缺少 --repo-root`（exit 2） | 版本過舊。執行 `uv tool install --force "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.14.0"`；帶 `--force` 是因為它在「已安裝」與「未安裝」兩種狀態下都成立，不需要先判斷目前狀態 |
| `[FAIL] pr-orchestrator <sub> --help 無法執行`（exit 2） | 安裝損毀，非版本問題。同樣以 `--force` 重裝；若仍失敗，先 `uv tool uninstall yibi-stack` 再安裝 |
| `[FAIL] 讀不到 pr-cycle-fast check-cli-capability.sh` | 執行 `claude plugin install pr-flow@yibi-stack`，或在 yibi-stack checkout 執行 `make install` |
| `分支沒有對應的 open PR` | 先 `gh pr create` 建立 PR |
| `多個 PR 對應同分支` | 加 `--pr <n>` 明確指定 |
| State 停在 BLOCKED | 看 blockers 訊息，解除後跑 `/pr-cycle-fast resume` |
| auto-fix 超過 3 次上限 | 手動修 CI 失敗後 push，再跑 `/pr-cycle-fast resume` |
| merge 後找不到 state | 查 `~/.claude/pr_orchestrator/<repo>/` 歸檔 |
