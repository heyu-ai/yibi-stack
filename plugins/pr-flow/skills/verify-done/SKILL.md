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

### Step 1 — Pre-commit（全量）

```bash
pre-commit run --all-files
```

**PASS**: 全部 hooks 回傳 exit 0。
**FAIL**: 列出失敗的 hook 名稱與錯誤訊息，停止不宣告完成。

> 注意：`pre-commit run --files <file>` 只掃指定檔案，CI 跑 `--all-files`。
> 只跑 `--files` 會漏掉未改動但有 pre-existing 問題的檔案，push 後 CI 才炸。

### Step 2 — PR CI Checks（若 PR 已存在）

If a PR is open for the current branch:

```bash
gh pr checks
```

**PASS**: 所有 checks 為 `pass` 或 `success`。
**FAIL**: 列出失敗的 check 名稱，說明哪個 step 有問題。
**SKIP**: 當前 branch 尚未建立 PR，跳過此步驟並標記。

### Step 3 — Spectra Amplifier（若有 Spectra 變更）

If files under `openspec/` were modified in this session:

```bash
spectra status
```

確認每個變更過的 change 已執行過 `/spectra-amplifier`（amplified_at 有時間戳）。

**PASS**: 所有相關 change 已 amplify，或本次沒有 Spectra 變更。
**FAIL**: 列出尚未 amplify 的 change 名稱，要求先跑 `/spectra-amplifier`。
**SKIP**: 本次工作不涉及 `openspec/` 變更。

### Step 4 — Worktree 安全性（若要執行 merge / branch 清理）

Before running `gh pr merge`, `git branch -d`, or any merge operation:

```bash
pwd
```

Confirm output is **not** a path containing `.claude/worktrees/`.

**PASS**: `pwd` 回傳主 repo 根目錄（e.g. `/Users/.../my-project`）。
**FAIL**: 當前在 worktree 內，停止。提示使用者切換至主 repo 目錄後再執行 merge。

> 在 linked worktree 內執行 `gh pr merge` 會因 main 已被 worktree 佔用而 fatal。

### Step 5 — 報告結果

逐項列出 PASS / FAIL / SKIP，格式如下：

```text
Verify Done Report
==================
Step 1 — pre-commit:        PASS
Step 2 — gh pr checks:      PASS  (PR #42)
Step 3 — spectra amplifier: SKIP  (no openspec changes)
Step 4 — worktree safety:   PASS  (/Users/.../project)

Overall: PASS — 可以宣告完成 / 執行 merge。
```

若任一步驟 **FAIL**，整體結果為 FAIL，不宣告完成，列出需修復的項目。

## FAQ

| Issue | Fix |
|-------|-----|
| `pre-commit` 找不到 | `uv sync` 重裝依賴 |
| `gh pr checks` 報 `no pull requests found` | PR 尚未建立，Step 2 標記 SKIP |
| `spectra` command not found | 確認 `uv sync` 已完成且在 yibi-stack 目錄 |
| worktree 內需要 merge | 切到主 repo 目錄，使用 `git -C <main-repo-path> <cmd>` |
