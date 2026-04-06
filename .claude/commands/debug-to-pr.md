# Debug Fix → Pull Request 流水線

Debug 完成後，將修復轉為乾淨的 PR。確保只有 fix-related 檔案被提交，排除探索性修改。

## Step 1: 辨識修改類型

```bash
git status
git diff --stat
```

將修改分為：

- **Fix files**: 實際修復 bug 的檔案
- **Debug artifacts**: 暫時加的 log、print、test scripts（不該 commit）
- **Unrelated changes**: 順手改的東西（另開 PR 或 stash）

列出分類結果，請使用者確認。

## Step 2: 確認/建立 Feature Branch

```bash
CURRENT=$(git branch --show-current)
echo "Current branch: $CURRENT"
```

- 如果在 `main`：建立 `fix/<描述>` branch
- 如果已在 feature branch：確認 branch 名稱合理
- **重要**：確認 upstream 不是追蹤 `origin/main`（`git branch -vv`）

## Step 3: Code Quality Check

```bash
uv run pytest
```

- 如果失敗：修好後再繼續

## Step 4: Selective Staging

只 stage fix-related 檔案：

```bash
# 列出建議 stage 的檔案
git add <fix-file-1> <fix-file-2> ...
git diff --cached --stat
```

**排除**：

- Debug log（`print()` 暫時加的）
- `.env` 變更
- 無關的格式化改動

## Step 5: Commit & Push

使用 conventional commit 格式：

```bash
git commit -m "fix(scope): 描述修復內容"
git branch -vv  # 確認 upstream
git push -u origin <branch>:<branch>
```

## Step 6: Create PR

```bash
gh pr create --title "fix(scope): 描述" --body "$(cat <<'EOF'
## Summary
- Root cause: <root cause 描述>
- Fix: <修復方式>

## Test plan
- [ ] `uv run pytest` passes
- [ ] Manual verification: <驗證步驟>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

回報 PR URL。

## Step 7: Lesson Learned（可選）

詢問使用者是否要記錄 lesson learned：

- Root cause 是什麼？
- 什麼 check 可以更早發現？
- 是否需要加 regression test？
