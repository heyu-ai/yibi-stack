---
description: 統一清理本地分支與 worktree：自動判斷 merged / gone / 無價值的殘留，證據不足者只報告不刪。取代 clean-merged 與 clean-gone。
model: sonnet
effort: medium
---
<!-- markdownlint-disable-file MD041 -->

# clean-wt

清理本地分支與 worktree。**預設只報告，不刪任何東西**；確認後才加 `--apply`。

## 執行

> **執行注意**：整段邏輯在腳本裡，**逐字執行下面這行，不要自己重寫成 bash**。
> command 檔裡的 bash 區塊會被 agent 「理解意圖後重新生成」而非逐字複製
> （見 CLAUDE.md「slash command bash code block rewritten by agent」），
> 重寫出來的版本會漏掉關鍵步驟——舊的 `clean-gone` 就因此漏掉 `git fetch --prune`，
> 導致 `[gone]` 永遠偵測不到，而「沒有 gone 分支」與「還沒 prune」看起來一模一樣。

先看報告：

```bash
bash commands/scripts/clean_wt.sh
```

把 SAFE 清單原樣呈現給使用者，等他確認後才執行刪除：

```bash
bash commands/scripts/clean_wt.sh --apply
```

`--apply` 只刪 SAFE 分類；BLOCKED / REVIEW 永遠不會被自動刪除。

可選：`--stale-days N` 調整 REVIEW 區的 `[STALE]` 標記門檻（預設 30 天）。

## 分類語意

| 分類 | 意義 | `--apply` 會刪嗎 |
|------|------|-----------------|
| **SAFE** | 有明確證據顯示內容已在 `origin/main` | 會 |
| **KEEP** | open PR，或是目前所在分支 | 不會 |
| **BLOCKED** | 其 worktree 有未提交變更 | 不會 |
| **REVIEW** | 無證據顯示內容已進 main（附年齡與獨有 commit 數供判斷）| 不會 |

## 判斷「內容是否已進 main」的三個證據

腳本用三個**各自獨立**的證據，任一成立才歸為 SAFE：

1. **PR 狀態為 MERGED**（`gh`，權威來源）
2. **tip 是 `origin/main` 的祖先**（`git merge-base --is-ancestor`）
3. **所有 patch 都已在上游**（`git cherry`，patch-id 比對）

三者皆不成立 → REVIEW，只報告不刪。寧可留著也不猜。

### 為什麼不能用三點 diff 判斷

**`git diff main...branch` 不能當作「內容還沒進 main」的證據。** 三點 diff 從
**merge-base** 算起，而 squash merge 不會讓分支的 commit 變成 main 的祖先，merge-base
因此停在合併前——**已經完整合併的分支，三點 diff 仍會顯示全部改動**。

實測（2026-07-15）：`worktree-feat-pin-review-models` 的三點 diff 顯示 7 個檔案「未合併」，
但其內容早已由 PR #229 squash 進 main。戳破它的是 `git rebase`——逐一 cherry-pick 時發現
改動已在上游，全部跳過，分支被清空。

### 為什麼分支乾淨不等於可以刪

**分支比對只看 commit，看不到工作目錄。** 實測（2026-07-15）：
`worktree-skill-governance-path-c` 的分支與 main 零差異，但其 worktree 存有 33 行未提交的
rule 草稿——只憑分支比對就會誤判為可安全刪除。腳本因此對任何 `git status --porcelain`
非空的 worktree 一律標記 BLOCKED。

## 已知限制

- **多 commit 分支被 squash**：`git cherry` 的 patch-id 對不上（上游是一個大 patch，分支是
  多個小 patch），會落到 REVIEW 而非 SAFE。這是往安全方向的誤判——留著，不會誤刪。
- **無 `gh` 時**：只能靠證據 2、3 判斷，已合併但非 fast-forward 的分支會落到 REVIEW。
- **年齡不是刪除依據**：REVIEW 區的 `[STALE]` 只是排序提示。久未更新但有獨有 commit 的分支
  仍需人工判斷——「舊」不代表「沒價值」。

## FAQ

| 問題 | 處理方式 |
|------|---------|
| 報告顯示「無 SAFE」但我確定有分支已合併 | 該分支可能是多 commit squash（見已知限制），或 `gh` 不可用；查 REVIEW 區 |
| BLOCKED 的分支我確定不要了 | 自行確認那些未提交變更後手動處理；腳本刻意不提供 `--force`，避免無法復原的誤刪 |
| 想連遠端分支一起刪 | 本腳本只動本地。遠端分支請用 `gh pr merge --delete-branch` 或手動 `git push origin --delete <b>` |
| 在 worktree 裡執行會怎樣 | 腳本自動切到主 repo 執行（linked worktree 不能 checkout main，且對被佔用的分支 `branch -D` 會失敗）|
