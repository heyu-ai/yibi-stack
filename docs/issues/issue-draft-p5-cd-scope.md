# Compound `cd && cmd` hook: `git` flagged; `uv`, `find`, `alembic` not flagged

> Status: posted 2026-05-04 as <https://github.com/anthropics/claude-code/issues/56020>
> This is an archived draft. Content below was already submitted.

## Summary

The "changes directory before running git" hook intercepts `cd ... && git ...` patterns.
Other `cd &&` compounds with comparable characteristics -- CWD-dependent behavior, path-resolution
side effects, potentially irreversible operations -- are not intercepted. Raising as a scope
question: is this coverage intentional?

## Reproduction

```bash
# Hook intercepts this (cd-before-git):
cd /tmp && git status

# Hook does not intercept these:
cd /tmp && uv run python -c "print(1)"
cd /tmp && find . -name "*.py" 2>/dev/null
cd /tmp && alembic upgrade head
```

**Expected**: either (a) the hook scope is intentionally limited to `git` commands, in which
case the behavior above is by design; or (b) other `cd &&` patterns with similar risk profiles
are also in scope for detection.

**Observed**: only `cd && git` triggers the hook. The other three forms run without a prompt,
even though `alembic upgrade head` is an irreversible database migration that is equally
sensitive to which directory it runs in.

## Notes

Several existing issues discuss this hook from the opposite direction -- the prompt is too
broad, or misidentifies the risky command: #28240, #30409, #28784, #30213. This report asks
the inverse question: should the hook cover non-git commands where the current working directory
determines behavior or outcome? No position taken; posting to learn whether the current scope
is intentional before raising further.

## Environment

- claude-code version: 2.1.118
- OS: macOS 26.4.1 (pre-release, Darwin 25.4.0)
- Shell: /bin/zsh
- Notes: heavy use of git worktrees and multiple language toolchains
