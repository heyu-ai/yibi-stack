---
name: verify-done
type: know
scope: global
description: >
  任務完成前的端對端驗證清單：pre-commit、CI checks、Spectra amplifier、worktree 安全性。
  觸發情境：「verify done」「完成前確認」「任務完成前」「mark done」「宣告完成」「done check」
  「pre-commit 跑完了嗎」「CI 過了嗎」「是否可以 merge」「可以 claim complete 嗎」。
---

# Verify Done

End-to-end verification checklist to run before claiming a task is complete or merging a PR.

## Steps

### Step 1 — CI（全量）

For projects with a `make ci` script (e.g. yibi-stack):

```bash
make ci
```

For projects without `make ci`, run separately:

```bash
pre-commit run --all-files
uv run pytest   # or: npm test / go test ./... / cargo test
```

**PASS**: 所有 hooks 與 tests 回傳 exit 0。
**FAIL**: 列出失敗的 hook 名稱或 test failure，停止不宣告完成。

> `make ci` 內含 `pre-commit run --all-files` + pytest，是 yibi-stack 的標準 push-gate。
> 只跑 `pre-commit run --all-files` 會漏掉 test 失敗；只跑 `--files` 會漏掉 pre-existing 問題。

### Step 2 — PR CI Checks（若 PR 已存在）

If a PR is open for the current branch:

```bash
gh pr checks
```

Exit code semantics:

- **0** = all checks passed
- **8** = checks still pending/running
- **1** = checks failed or tool error

**PASS**: exit 0，所有 checks 完成且無 fail。
**PENDING**: exit 8 — checks 仍在執行，列出 pending check 名稱，等待完成後重新執行 Step 2。不宣告完成。
**FAIL**: exit 1 + check data returned — 列出失敗的 check 名稱，說明哪個 step 有問題。
**TOOL ERROR**: exit 1 + no check data (e.g. auth error on stderr) — 執行 `gh auth status` 確認認證；整體標記 FAIL（工具無法執行）。
**SKIP**: `gh pr checks` 回傳 `no pull requests found`（PR 尚未建立），跳過並標記。

### Step 3 — Spectra Amplifier（若有 Spectra 變更）

First, detect whether openspec changes are present in this branch:

```bash
git diff main...HEAD --name-only
```

If the output contains any path starting with `openspec/`, proceed. Otherwise **SKIP** this step.

For each relevant change visible in `spectra list`:

```bash
spectra status
```

Confirm the change shows `✓ All artifacts complete` in the output (all artifact rows marked ✓).
If any artifact shows ✗ or is missing, `/spectra-amplifier` has not been run to completion.

**PASS**: `spectra status` shows all artifacts complete (✓) for each relevant change.
**FAIL**: Any artifact ✗ or missing — list the change name and missing artifacts. Require running `/spectra-amplifier` before proceeding.
**SKIP**: No `openspec/` paths in the branch diff.

### Step 4 — Worktree 安全性（若要執行 merge / branch 清理）

Before running `gh pr merge`, `git branch -d`, or any merge operation:

```bash
pwd
```

Also run:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
```

**PASS**: `git rev-parse --git-dir` equals `git rev-parse --git-common-dir` (same `.git` directory = main repo, not a linked worktree). Execute merge from here.
**FAIL**: The two paths differ — current session is inside a linked worktree. Stop. Ask the user to run the merge command manually from the main repo directory.

> `gh pr merge` が linked worktree 內執行，若主 repo 已 checkout main，會失敗
> （`fatal: 'main' is already used by worktree`）。需從主 repo 目錄執行。

### Step 5 — 報告結果

逐項列出 PASS / FAIL / PENDING / TOOL ERROR / SKIP，格式如下：

```text
Verify Done Report
==================
Step 1 — make ci:           PASS
Step 2 — gh pr checks:      PASS  (PR #42)
Step 3 — spectra amplifier: SKIP  (no openspec changes)
Step 4 — worktree safety:   PASS  (/Users/.../project)

Overall: PASS — 可以宣告完成 / 執行 merge。
```

若任一步驟 **FAIL** 或 **PENDING**，整體結果為 FAIL，不宣告完成，列出需修復或等待的項目。

## FAQ

| Issue | Fix |
|-------|-----|
| `pre-commit` 找不到 | `uv sync` 重裝依賴 |
| `make ci` 找不到 target | 改跑 `pre-commit run --all-files && uv run pytest` |
| `gh pr checks` 回傳 `no pull requests found` | PR 尚未建立，Step 2 標記 SKIP |
| `gh pr checks` auth error | 執行 `gh auth login` 重新認證 |
| `spectra` command not found | 確認 `uv sync` 已完成且在 yibi-stack 目錄 |
| worktree 內需要 merge | 切到主 repo 目錄後執行 `gh pr merge`（`gh` 指令不支援 `git -C` 代理） |
