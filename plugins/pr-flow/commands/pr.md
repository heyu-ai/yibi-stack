# Create Pull Request

Automates the complete PR workflow: verify quality → commit → push → create/update PR.

## Workflow

### Step 1: Check Current Branch

```bash
git rev-parse --abbrev-ref HEAD
git status
```

- If on `main` or `master`: **STOP** — ask the user to confirm the branch strategy before proceeding.
- If on a feature branch: continue.

### Step 2: Verify Code Quality

```bash
uv run pytest
```

**Stop if any check fails.** Fix issues first, then re-run.

### Step 3: Ensure All Changes Are Committed

```bash
git status
git diff --stat
```

If there are uncommitted changes, stage and commit them with a descriptive conventional commit message:

```bash
git add <relevant files>
git commit -m "type(scope): description"
```

### Step 4: Push Branch to Remote

```bash
git push -u origin HEAD
```

### Step 5: Create or Update Pull Request

Check if a PR already exists:

```bash
gh pr view 2>/dev/null && echo "PR exists" || echo "No PR"
```

If **no PR exists**, create one:

```bash
gh pr create --title "<type>(<scope>): <description>" --body "$(cat <<'EOF'
## Summary
- <bullet points summarizing changes>

## Changes
- <list key files changed and why>

## Test plan
- [ ] `uv run pytest` passes
- [ ] Manual verification: <describe what to verify>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If **PR already exists**, update it:

```bash
gh pr edit --title "<updated title>" --body "<updated body>"
```

### Step 6: Report and Wrap Up

- Output the PR URL.
- Ask: "Would you like to clean up any merged local branches?"
