# `Unhandled node type: string` triggers across 4 distinct bash structures

> Status: posted 2026-05-04 as <https://github.com/anthropics/claude-code/issues/56018>
> This is an archived draft. Content below was already submitted.
> Caveat: Structure (b) repro uses a simplified grep (no `\|`). Whether for-loop +
> line-continuation alone triggers the hook -- without BRE alternation -- was not
> independently verified; see tracking doc for details.

## Summary

The hook message `Unhandled node type: string` appears in the command confirmation prompt for at
least four structurally distinct bash patterns. Each triggers the same message, which makes it
difficult to tell from the prompt which structure is the root cause. Listing them here in case
it helps maintainers identify whether one code path covers all four or each is a separate gap.

## Reproduction

**Structure (a) -- same-type nested quotes: `"outer $(cmd "$VAR")"`**

```bash
echo "value: $(echo "$HOME")"
```

Expected: passes without error, or prompts with a message specific to nested same-type quotes.
Observed: `Unhandled node type: string`

---

**Structure (b) -- `for`-loop with `\` line continuation and a pipe in the body**

```bash
for f in a.txt \
  b.txt; do
  grep -c "hello" "$f" | head -1
done
```

Expected: passes without error, or prompts with a message specific to complex loop bodies.
Observed: `Unhandled node type: string`

---

**Structure (c) -- BRE alternation (`\|`) inside a double-quoted `grep` pattern**

```bash
grep "alpha\|beta" file.txt
```

Expected: passes without error (standard BRE syntax).
Observed: `Unhandled node type: string`

---

**Structure (d) -- reverse same-type nesting: `$(outer "$(inner)")`**

```bash
BASE=$(dirname "$(git rev-parse --git-common-dir)")
```

Expected: passes without error.
Observed: `Unhandled node type: string`

## Notes

Related symptom reports that surface the same message: #42085, #43246, #50144, #55479, #49483.
None of those enumerate which bash structures produce this error. Listing the four structures here
in case it accelerates root-cause analysis.

## Environment

- claude-code version: 2.1.118
- OS: macOS 26.4.1 (pre-release, Darwin 25.4.0)
- Shell: /bin/zsh
- Notes: heavy use of git worktrees and multiple language toolchains
