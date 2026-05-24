# 不可逆操作邊界（Irreversible Operations）

v2 文件層規則。以下操作**不得由 agent 自主執行**，必須先向使用者說明操作內容、
預期影響、回滾難度，再由使用者決定是否執行或手動操作。

## 何謂「不可逆操作邊界」

操作滿足以下任一條件即列入本規則：

1. **資料不可回復**：執行後資料永久消失或覆蓋，無法從版本控制或備份快速還原
2. **影響範圍跨越環境**：影響生產環境、遠端倉庫、雲端資源或外部服務
3. **需要明確授權**：釋出套件版本、部署生產服務、修改共用 git history 等需要有意識批准的動作

## Agent 遇到不可逆操作的標準行為

```text
STOP：操作描述
影響：<說明哪些資源受影響、影響範圍>
回滾難度：<高 / 中 / 低 + 說明>
建議：<dry-run 指令> 或 <請使用者手動執行>
```

不要在 bash call 直接執行；用純文字說明後等待使用者確認。

---

## 類別 1：DB / Storage（資料庫與儲存層）

| 操作 | 風險 | 建議做法 |
|------|------|---------|
| `alembic upgrade head` / `alembic downgrade` | schema 變更不可逆；downgrade 可能丟失欄位資料 | 先 `alembic check` 確認遷移腳本，讓使用者在確認後手動執行 |
| `prisma migrate deploy` | 生產 migration 直接套用，無 dry-run | 先 `prisma migrate diff` 顯示 SQL 差異 |
| `flyway migrate` | 同上，直接套用 migration | 先 `flyway info` 確認待執行版本 |
| `DROP TABLE` / `TRUNCATE` / `DELETE` 無 WHERE | 資料永久消失 | 描述 SQL 請使用者手動執行；先用 `SELECT COUNT(*)` 確認影響筆數 |

```bash
# 禁止 agent 自主執行：
alembic upgrade head
prisma migrate deploy
psql -c "DROP TABLE users"
psql -c "DELETE FROM sessions"   # 無 WHERE 條件
```

## 類別 2：Deployment（部署與發布）

| 操作 | 風險 | 建議做法 |
|------|------|---------|
| `kubectl apply` 到 prod namespace | 直接改變生產工作負載 | 先 `kubectl diff` 或在 staging 確認，讓使用者手動 apply |
| `terraform apply`（任何形式，含 `-target`）| 直接變更雲端基礎設施，`-target` 仍可刪除或重建資源 | 先 `terraform plan`，讓使用者 review plan 後手動執行 |
| `gh release create` | 公開釋出套件版本，無法刪除（NPM 72 小時限制，PyPI 永久）| 確認版本號、CHANGELOG、tag 正確後，讓使用者手動執行 |
| `npm publish` | 同上 | 先 `npm pack` 檢查套件內容 |
| `uv publish` | 同上 | 先確認 `dist/` 內容與版本號 |

```bash
# 禁止 agent 自主執行：
kubectl apply -f k8s/prod/
terraform apply
gh release create v1.2.3
npm publish
uv publish
```

## 類別 3：Git Destructive（git 破壞性操作）

| 操作 | 風險 | 建議做法 |
|------|------|---------|
| `git push --force` / `git push -f` | 覆蓋遠端 commit history，影響所有協作者 | 說明需要 force push 的原因，讓使用者手動執行；confirm 是否為個人 branch |
| `git reset --hard <ref>` | 捨棄本地 uncommitted 與 commit 變更 | 先 `git status` + `git log` 確認影響範圍，讓使用者確認後執行 |
| shared branch 的 `git rebase` | rewrite shared history，造成他人需要 force pull | 確認 branch 是否為個人 branch；shared branch 應用 merge 而非 rebase |
| `git filter-branch` / `git filter-repo` | 改寫整個倉庫 history | 幾乎永遠需要使用者明確授權；描述操作讓使用者手動執行 |

```bash
# 禁止 agent 自主執行：
git push --force origin main
git push -f
git reset --hard HEAD~3
git filter-branch --env-filter '...'
```

**例外**：個人 worktree branch 的 `git reset --hard` 若僅影響本地未 push 的變更，
影響範圍小，可在說明後執行。判斷準則：該 branch 是否已 push 到 remote。

### Recovery：用 branch + reset 救回誤推 main 的 commit（仍未 push 才適用）

當使用者在 `main` 直接 commit 後想轉成 PR 流程，**未 push** 之前是完全可逆的。順序很重要：

```bash
# 1) 先用 ref 把 commit 保住（branch 是輕量 ref，不會丟資料）
git branch <feat-name> HEAD

# 2) 再倒 main 回 origin/main（reset --hard 在這步**安全**，
#    因為 commit 已經被 step 1 的 branch 保住）
git reset --hard origin/main

# 3) 切到剛剛保住的 feat branch，從這邊 push + 開 PR
git checkout <feat-name>
git push -u origin <feat-name>
```

**順序為何不能反**：先 `reset --hard` 再 `branch` 會丟掉 commit（HEAD 已倒回，branch
只會指到 reset 後的 HEAD，而非原本誤推 main 的那個 commit）。先 `branch` 後 `reset`
是 atomic 防禦：第 1 步成功 = commit 永遠不會丟，第 2 步失敗也沒事。

**Pre-flight canary（強烈建議在 step 2 前跑一次）**：

```bash
# 先 fetch 確認 remote view 是新的；再列出「main 領先 origin/main 但未在 origin 的 commit」
git -C <repo> fetch origin
git -C <repo> log HEAD..origin/main --oneline   # 應該是空的（origin 沒新 commit）
git -C <repo> log origin/main..HEAD --oneline   # 應該只看到你想保住的 commit
```

若 `origin/main..HEAD` 包含**多於**你想保住的 commit，或包含已經在 `origin/main` 的
commit，**先停下來**——你的 main 可能不是你想的那個狀態。寧可錯失 recovery 機會也不要
誤刪。確認單一目標 commit 後再跑 step 2 的 `reset --hard origin/main`。

**判斷準則**：在跑 step 2 之前必須先確認 `git push` **沒有發生過**（`git log
origin/main..main` 顯示要保住的 commit，且該 commit 在 origin/main 的 history 不存在）。
若已 push，這個 recovery 不適用，要走 PR + revert commit 流程。

實證：yibi-stack PR #36 的初始 commit `18b94f9` 誤推到本地 main，使用此 recovery 安全
轉到 `feat-pr-test-anti-patterns-faq` branch，commit 完整保留並照 `/pr-review-cycle`
流程跑完。

## 類別 4：File Destructive（檔案破壞性操作）

| 操作 | 風險 | 建議做法 |
|------|------|---------|
| `rm -rf <path>` | 遞迴刪除，無法從 Trash 回收 | 先 `ls <path>` 確認內容，讓使用者確認後執行；或改用 `trash` 指令 |
| `find ... -delete` | 批次刪除，影響範圍難以預估 | 先 `find ... -print`（不加 -delete）顯示受影響檔案 |
| `> file` 覆寫已存在的檔案 | 原始內容永久消失 | 先確認是否有備份或 git 版本；用 `>>` append 替代，或先 `cp` 備份 |
| `truncate -s 0 file` | 清空檔案內容 | 先確認檔案用途；說明操作讓使用者確認 |

```bash
# 禁止 agent 自主執行：
rm -rf /path/to/dir
find /path -name "*.log" -delete
> /etc/config.json           # 覆寫已存在設定檔
truncate -s 0 data/prod.db
```

## 類別 5：Cloud（雲端資源）

| 操作 | 風險 | 建議做法 |
|------|------|---------|
| `aws s3 rm --recursive s3://bucket/` | 大量物件永久刪除，無回收站 | 先 `aws s3 ls --recursive` 確認影響範圍，讓使用者確認後執行 |
| `gcloud compute instances delete` | VM 刪除後磁碟資料消失（預設） | 先確認 instance 名稱與 zone，讓使用者手動執行 |
| `gcloud sql instances delete` | 資料庫刪除，即使有備份也需要時間還原 | 幾乎永遠應讓使用者手動執行 |
| `az group delete --resource-group` | 刪除整個 Azure resource group 及其中所有資源 | 描述影響範圍，讓使用者手動執行 |

```bash
# 禁止 agent 自主執行：
aws s3 rm --recursive s3://prod-data/
gcloud compute instances delete my-vm --zone us-central1-a
gcloud sql instances delete prod-db
```

## Git Push 前確認 Upstream Tracking（防意外推到 main）

從 `origin/main` 建立的 feature branch，upstream tracking 預設指向 `origin/main`。
未加 `-u` 直接執行 `git push origin <feature-branch>` 時，
git 依 tracking 設定推到 `origin/main`，繞過 PR review 流程。

**標準做法：push 前執行 `git branch -vv` 確認 upstream**

| upstream 顯示 | push 指令 |
|--------------|---------|
| `[origin/main: ahead N]` | 必須用 `git push -u origin <branch-name>` 建立專屬遠端 branch |
| `[origin/<branch-name>]` | 直接 `git push` 即可 |

```bash
# 確認 upstream 後用 -u 建立遠端 branch
git branch -vv
git push -u origin chore/my-feature-branch
```

這是「影響共享 branch」的不可逆操作：一旦推到 `origin/main`，
所有協作者的下次 `git pull` 都會取得未經 review 的變更。
個人 worktree branch 若未 push，影響範圍小，不在此規則範圍。

## Revert PR Pre-merge Checklist

When creating a revert PR (to undo commits that landed on a shared branch):

1. **Fetch and rebase onto latest `origin/main` before requesting review**:
   ```bash
   git fetch origin
   git rebase origin/main
   ```
2. **Verify diff scope matches stated intent**:
   ```bash
   git diff origin/main HEAD --name-only
   ```
   Should list only the files the revert commit actually touches.
3. **Why**: `origin/main` may have advanced since the revert branch was created (e.g., a security fix landed independently). Without rebase, the stale branch base causes `git diff origin/main HEAD` to include those newer commits in the diff — merging silently reverts them.

**Real incident (PR #55)**: After the revert branch was created, `5725b86` (`security(agy): replace --dangerously-skip-permissions with --sandbox`) landed on `origin/main`. Without rebase, the diff included 3 agy scripts. Mob review caught it; rebase onto `origin/main` fixed the scope back to exactly 6 rule files.

## Scope

本規則適用於所有 Claude Code agent session。不影響使用者自行在 terminal 執行的指令。
純文件規則，v2 不加 `.claude/settings.json` deny list；機械性阻擋列入 v3 規劃。
