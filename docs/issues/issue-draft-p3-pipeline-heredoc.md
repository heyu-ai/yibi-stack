# `Unhandled node type: pipeline` on heredoc-pipe (`cat <<'EOF' | cmd`)

> Status: posted 2026-05-04 as <https://github.com/anthropics/claude-code/issues/56019>
> This is an archived draft. Content below was already submitted.
> Accuracy note: "semantically equivalent" in the live issue is imprecise -- the redirect
> form requires a temp file as intermediate step. The hook behavior is unaffected.

## Summary

Piping a heredoc directly into a command (`cat <<'EOF' | cmd`) triggers
`Unhandled node type: pipeline` on the confirmation prompt. The redirect form
(`cmd < file`, after writing content to a temp file first) does not trigger.

## Reproduction

```bash
# Triggers "Unhandled node type: pipeline":
cat <<'EOF' | cat
hello world
EOF
```

```bash
# Workaround -- write to a file first, then redirect (no pipeline node):
printf 'hello world\n' > /tmp/repro_input.txt
cat < /tmp/repro_input.txt
```

**Expected**: the heredoc-pipe pattern is a common shell idiom; it should parse consistently
with the redirect form, or at least produce a specific prompt that describes the unsupported
construct.

**Observed**: `cat <<'EOF' | cmd` triggers `Unhandled node type: pipeline`. The redirect form
(`cmd < file`) passes without error.

## Notes

Related: #47701 (closed, framed around `file_redirect`). That report mentions several missing
node type handlers. The `pipeline` failure from heredoc-pipe appears to be a distinct case: the
parser fails at the pipeline node rather than at a redirect node, and the `< file` workaround
works, suggesting the two code paths are separate.

## Environment

- claude-code version: 2.1.118
- OS: macOS 26.4.1 (pre-release, Darwin 25.4.0)
- Shell: /bin/zsh
- Notes: heavy use of git worktrees and multiple language toolchains
