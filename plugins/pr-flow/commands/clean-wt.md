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
> （見 CLAUDE.md「slash command bash code block rewritten by agent」）。
> 這支腳本會刪東西，重寫出來的版本不會有任何測試覆蓋它。
>
> 路徑用 `~/.claude/commands/scripts/`（`make install` 建立的 symlink，指向本 repo）：
> 它與 cwd 無關，在 worktree 裡、在別的專案裡都能解析到。
> 不要改成 repo 相對路徑 `commands/scripts/...`——那只有在 repo root 執行才存在。

先看報告（把使用者傳入的參數原樣轉發）：

```bash
bash ~/.claude/commands/scripts/clean_wt.sh $ARGUMENTS
```

把 SAFE 清單原樣呈現給使用者，**等他確認後**才執行刪除：

```bash
bash ~/.claude/commands/scripts/clean_wt.sh --apply
```

`--apply` 只刪 SAFE 分類；BLOCKED / REVIEW / KEEP 永遠不會被自動刪除。

可選：`--stale-days N` 調整 REVIEW 區的 `[STALE]` 標記門檻（預設 30 天）。

## 分類語意

| 分類 | 意義 | `--apply` 會刪嗎 |
|------|------|-----------------|
| **SAFE** | 有**正面證據**證明內容已在 `origin/main` | 會 |
| **KEEP** | open PR、主 repo 目前 checkout 的分支、或**呼叫端所在的分支** | 不會 |
| **BLOCKED** | 其 worktree 有未提交變更（或狀態讀不到） | 不會 |
| **REVIEW** | 拿不到證據（附年齡與獨有 commit 數供判斷） | 不會 |

## 判斷「內容是否已進 main」的證據

**極性是「預設拒絕」**：只有拿到**正面證據**才歸 SAFE。任何證據拿不到、算不出、工具失敗，
一律往 REVIEW 掉（fail closed）。**「找不到它未合併的證據」不等於「它已合併」**——這兩者的
差別就是資料存亡。

兩個獨立的正面證據，任一成立即 SAFE：

1. **E1 — tip 已是 `origin/main` 的祖先**（`git merge-base --is-ancestor`）
   history 上直接包含，最強的證據。涵蓋 fast-forward 與 merge commit。
2. **E2 — 把分支併回 main 是 no-op**（`git merge-tree --write-tree`，需 git >= 2.38）
   算出「把分支併進 main 會產生的 tree」，若等於 main 現在的 tree，代表分支沒有任何 main
   沒有的內容。這是關於**內容**的正面證明，與 history 形狀無關，因此 squash（單／多 commit）、
   rebase、merge commit 全部涵蓋。

再加一個**輔助**證據，只在 E1／E2 都不成立時才問：

- **E3 — PR 已 MERGED、base 是 `main`、且 `headRefOid` == 本地 tip**（`gh`）
  **必須綁 tip SHA**。用途是救回 E2 的保守誤判：分支 squash 合併後 main 又動到同一個檔案，
  merge-tree 會回報 conflict（見已知限制）。

### 為什麼 PR 狀態不能單獨當證據

`gh pr list --head <branch>` 回答的是「**有沒有一個同名 head-ref 的 PR 被合併過**」，不是
「**這個本地分支現在的內容有沒有被合併**」。

本 repo 的標準流程正是 `gh pr merge --squash --delete-branch`：遠端分支被刪、本地分支還在。
此時在本地分支再加 commit（沒開新 PR），PR 狀態仍是 `MERGED`——若直接據此判為可刪，該分支
會被標記「僅本地」（遠端已刪）然後 `git branch -D`，**沒有遠端可救回，永久遺失**。
綁 `headRefOid` 就是為了讓證據跟著 commit 走，而不是跟著名字走。

### 為什麼不用 `git cherry`

`git cherry` 內部設 `revs.max_parents = 1`，**merge commit 永遠不會被列出**。因此「內容只
存在於 merge commit 裡」（手動衝突解決是最常見的情況）時，`git cherry` 看不到任何 `+`，
讀起來就是「所有 patch 都已在上游」→ 判為可刪 → 永久遺失。

實測（probe，2026-07-15）：分支的非 merge commit 全在上游、唯一內容在 merge commit 裡，
`git cherry` 回報「全部已在上游」，`merge-tree` 回報「仍有獨有內容」（正確）。

`git cherry` 另有一個相反方向的弱點：多 commit 分支被 squash 成一個 commit 時 patch-id
對不上，已合併的分支也會被判成未合併。實測（本 repo）：
`worktree-fix-232-worktree-install-guard` 已由 PR #234 squash 合併，`git cherry` 仍回報 8 個
「未合併」patch；`merge-tree` 正確判定為 no-op。

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

## 已知限制（都是往「留著」的方向，不會誤刪）

- **git < 2.38**：沒有 `merge-tree --write-tree`，E2 不可用，squash 合併的分支會落到 REVIEW。
- **squash 合併後 main 又改到同一個檔案**：merge-tree 回報 conflict → E2 不成立，靠 E3 救回；
  沒有 `gh` 就落到 REVIEW。
- **gh 只抓最近 500 個 PR**：更舊的 PR 查不到 → E3 不成立 → 落到 REVIEW。
- **年齡不是刪除依據**：REVIEW 區的 `[STALE]` 只是排序提示。久未更新但有獨有 commit 的分支
  仍需人工判斷——「舊」不代表「沒價值」。

## 附帶行為

- **fetch 是必要步驟**：沒有 `git fetch --prune`，remote-tracking ref 不會更新，`origin/main`
  停在舊位置，而「分支未合併」與「本地基準過期」看起來一模一樣。
  **`--apply` 模式下 fetch 失敗是致命錯誤**（exit 1，不刪任何東西）：過期的基準可能「證明」
  其實還沒合併的工作已經合併。報告模式只是看，降級成 `[WARN]`。
- **Port 登記清理**：刪分支前會呼叫 `tasks.local_port_manager release` 釋放該分支
  （branch name 即 project key，由 `/newjob` Step 2c 登記）的所有 port。清理失敗只 `[WARN]`，
  不擋刪除。此工具只存在於本 repo，在別的專案執行時安靜跳過。

## FAQ

| 問題 | 處理方式 |
|------|---------|
| 在 worktree 裡執行會怎樣 | 腳本自動切到主 repo 執行（linked worktree 不能 checkout main，且對被佔用的分支 `branch -D` 會失敗）。**呼叫端所在的分支一律歸 KEEP，絕不會被刪**——即使它符合 SAFE 條件 |
| `/pr-cycle-fast` Step 8 在剛合併的 worktree 裡呼叫，安全嗎 | 安全。那個 worktree 此刻剛好符合 SAFE，但呼叫端所在分支永遠是 KEEP。要刪它請在**主 repo** 執行 |
| 報告顯示「無 SAFE」但我確定有分支已合併 | 見已知限制：可能是 git < 2.38、merge-tree 遇到 conflict、或 PR 太舊查不到；查 REVIEW 區人工確認 |
| BLOCKED 的分支我確定不要了 | 自行確認那些未提交變更後手動處理；腳本刻意不提供 `--force`，避免無法復原的誤刪 |
| 想連遠端分支一起刪 | 本腳本只動本地。遠端分支請用 `gh pr merge --delete-branch` 或手動 `git push origin --delete <b>` |
| `--apply` 回 exit 1 | 有項目刪除失敗（常見：worktree 被 lock 或有殘留檔案）。看 stderr 的 `[WARN]`/`[FAIL]`；失敗不會被吞掉 |
