# Comment draft -- for anthropics/claude-code #43713

> Source: <https://github.com/anthropics/claude-code/issues/43713>
> Status: posted 2026-05-04 -- <https://github.com/anthropics/claude-code/issues/43713#issuecomment-4371496357>
> This is an archived draft. Content below was already submitted.

---

The `Contains expansion` hook also fires on `"${VAR}"` -- the bash form that uses braces to
explicitly delimit the variable name boundary and double quotes to prevent word-splitting. This
form is often cited as the safest variable expansion style, yet it triggers the prompt while the
less-explicit `"$VAR"` (no braces) does not.

**Reproduction**:

```bash
# Triggers "Contains expansion":
test -n "${MY_VAR}" && echo "set" || true

# Does not trigger:
test -n "$MY_VAR" && echo "set" || true
```

**Expected**: both forms are already quoted; neither would cause word-splitting or glob expansion.
The hook should treat them identically.

**Observed**: `"${VAR}"` triggers `Contains expansion`; `"$VAR"` passes without a prompt.

The practical effect is that users who write the more defensive form get more confirmation prompts
than users who omit the braces. Not certain whether this fits within #43713's scope or warrants
a standalone report -- mentioning it here for triage.
