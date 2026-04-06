# 整合遷移計畫：my-skills + my-daily-routine-skill → howie-skills

> 建立日期：2026-04-05

## 決策摘要

| 項目 | 決策 |
|------|------|
| **主體 Repo** | `my-daily-routine-skill`（41 commits, 10+ PRs, 有 CI/CD） |
| **併入 Repo** | `my-skills`（1 commit, 純 Markdown, 無 CI） |
| **最終名稱** | `howie-skills` |
| **安裝機制** | 保留 symlink 到 `~/.agent/skills/` |

**理由**：`my-daily-routine-skill` 有完整的 Python 基建（pyproject.toml、GitHub Actions、tests）和豐富的 git history，是更好的主體。`my-skills` 只有 1 個 commit，內容全部是 Markdown，搬遷成本極低。

---

## Phase 1：程式碼合併（在 branch 上操作）

### Step 1：複製知識型 skill 到 `skills/`

從 `my-skills/skills/` 複製以下目錄到 `my-daily-routine-skill/skills/`：

```bash
# 來源：/Users/howie/Workspace/github/my-skills/skills/
# 目標：/Users/howie/Workspace/github/side-project/my-daily-routine-skill/skills/

cp -r <source>/skills/tdd-kentbeck       <target>/skills/
cp -r <source>/skills/qa-test-design     <target>/skills/
cp -r <source>/skills/detect-ai-slop     <target>/skills/
cp -r <source>/skills/howie-writing-style <target>/skills/
cp -r <source>/skills/local-port-manager  <target>/skills/
```

### Step 2：搬入 `drafts/` 和 `ideas/`

```bash
cp -r <source>/drafts/ <target>/drafts/
cp -r <source>/ideas/  <target>/ideas/
```

### Step 3：合併 Makefile

將 `my-skills` 的 symlink 安裝邏輯（`install`, `install-one`, `status`, `uninstall`, `promote`）合併到現有 Makefile，與原有的 Python 開發指令（`lint`, `format`, `typecheck`, `test`, `check`）共存。

### Step 4：更新 `skills/README.md`

在索引表格中新增 5 個知識型 skill，標記「類型」欄位區分可執行 skill 和知識型 skill。

### Step 5：更新 `CLAUDE.md`

加入：

- `drafts/` 和 `ideas/` 目錄說明
- 知識型 skill vs 可執行 skill 的區別
- `make install` / `make promote` 等新指令
- 開發流程：ideas → drafts → skills

### Step 6：更新 `.gitignore`

加入 `dist/` 和 `_workspace/`（從 my-skills 的 .gitignore 補充）。

### Step 7：提交 PR，合併到 main

---

## Phase 2：GitHub Repo 操作（合併後手動執行）

### Step 8：Rename Repo

```text
GitHub → my-daily-routine-skill → Settings → Repository name → howie-skills
```

- GitHub 會自動建立 redirect（舊 URL 仍可訪問）
- 本地 remote URL 需要更新：

```bash
cd /Users/howie/Workspace/github/side-project/my-daily-routine-skill
git remote set-url origin git@github.com:howie/howie-skills.git
```

- 考慮是否要搬出 `side-project/` 子目錄：

```bash
mv /Users/howie/Workspace/github/side-project/my-daily-routine-skill /Users/howie/Workspace/github/howie-skills
```

### Step 9：Archive 舊 Repo

```text
GitHub → my-skills → Settings → Danger Zone → Archive this repository
```

- Archive 後 repo 變 read-only，但仍可存取
- README 會顯示 "This repository has been archived" 橫幅

### Step 10：更新 symlink

```bash
# 移除舊的 my-skills symlink
cd ~/.agent/skills/
# 確認哪些是指向舊 repo 的 symlink
ls -la | grep my-skills

# 重新安裝（從新 repo）
cd <new-repo-path>
make install
```

### Step 11：驗證

- [ ] `make check` 通過（lint + format + typecheck + test）
- [ ] `make install` 成功建立 symlink
- [ ] `make status` 顯示所有 skill 正確連結
- [ ] 舊 GitHub URL redirect 正常
- [ ] 舊 my-skills repo 已 archive

---

## 回滾方案

如果合併後出問題：

1. `my-skills` 只是 archive，隨時可以 unarchive
2. `my-daily-routine-skill` 的 git history 完整保留，可以 revert merge commit
3. GitHub rename 可以再改回來（redirect 也會自動更新）
