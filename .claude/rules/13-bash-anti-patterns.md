# Bash Anti-Patterns

## Anti-Pattern 1: Overly Complex Single Command

Complexity score (>=2 of 5 = excessive, must decompose):

1. Multi-line (heredoc or `\` continuation)
2. Nested same-type quotes (`"$(cmd "$VAR")"` or double-quote-within-double-quote)
3. Embedded other language (`python -c`, `node -e`, complex multi-line jq)
4. Multiple `if`/`elif`/`case` branches
5. Complex parameter expansion (`${var//pat/rep}`, indirect `${!var}`)

**Not excessive**: pure git workflow chains (`git add && git commit && git push`),
linear same-type chains (`make lint && make test`). `&&` count alone is not a criterion.

Fix priority:

1. Split into multiple bash calls
2. Extract to a script file (`scripts/foo.sh`, then call `bash scripts/foo.sh`)
3. Use the right tool (JSON → `jq`, paths → `realpath`/`basename`)

**Golden rule: never cram multi-step logic into one line to save a bash call.**

### AP1 Sub-type: for-loop-file-list

Any of these conditions requires extracting to a standalone script:

- for body > 1 line
- for body contains pipe (`|`)
- for body contains `if`/`elif`

```bash
# Wrong: for loop + if + pipe (AP1 score 3/5)
for f in a.py \
         b.py; do
  COUNT=$(grep -c "pattern" "$f")
  if [ "$COUNT" -gt 0 ]; then grep -n "pattern" "$f"; fi
done

# Fix: extract to script
bash scripts/scan_pattern.sh
```

### AP1 Sub-type: Nested Same-type Quotes

`echo "result: $(cmd "$VAR")"` — `$()` inside double quotes uses double quotes again;
the static analyzer reports `Unhandled node type: string`.

```bash
# Wrong
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

# Fix: split into separate bash call
git -C "$MAIN_REPO" rev-parse --short HEAD
```

The standard fix for cd-before-git remains `git -C <path>` (Cases 7/12); the issue is
wrapping it in `echo "$()"`, not `git -C` itself.

## Anti-Pattern 2: Special Unicode in Bash Command Strings

**Scope**: only the bash command string content itself (`echo` strings, variable literals,
filename literals, heredoc content).

**Not restricted**: file content read/written by bash, markdown docs, code comments, commit messages.

Banned in bash command strings: em dash (—), en dash (–), emoji, zero-width spaces.

| Replace | With |
|---------|------|
| skip icon | `[SKIP]` |
| ok icon | `[OK]` |
| warn icon | `[WARN]` |
| fail icon | `[FAIL]` |
| em dash — | `--` |
| en dash – | `-` |

CJK text, full-width punctuation (，、。：「」), and ASCII punctuation are all fine.

## Anti-Pattern 3: Stateful cd

`cd <path> && cmd` has three distinct failure modes with different fixes.

### AP3 Sub-class A: CWD Pollution (no hook; silent blind spot)

**Trigger**: `cd <path> && <non-git command>` — cd changes session CWD; all subsequent
bash calls are affected. Tool `--directory` option avoids this entirely.

Cases: 4 (alembic upgrade), 17/18 (cd + python3 -c async DB query)

```bash
# Wrong: cd pollutes CWD
cd /path/to/backend && uv run python3 scripts/check_stats.py

# Fix A (preferred): use tool-native --directory
uv run --directory /path/to/backend python3 scripts/check_stats.py

# Fix B: subshell isolation (does not pollute outer CWD)
( cd /path/to/backend && uv run python3 scripts/check_stats.py )
```

| Tool | Wrong (cd) | Fix (--directory) |
|------|-----------|-------------------|
| uv run | `cd /p && uv run python3 ...` | `uv run --directory /p python3 ...` |
| pytest | `cd /p && uv run pytest` | `uv run --directory /p pytest` |
| npm | `cd /p && npm test` | `npm --prefix /p test` |

### AP3 Sub-class B: cd-before-git (class C hook attempts to catch)

**Trigger**: `cd <path> && git <anything>` — cd changes CWD before git, causing git to
use an unexpected `.git/hooks` path. Class C hook tries to intercept but is not guaranteed.

Cases: 7 (cd + git status), 9 (cd + git commit heredoc), 12 (cd + git log)

```bash
# Wrong
cd /path/to/repo && git status

# Fix: git -C specifies working directory without changing session CWD
git -C /path/to/repo status
git -C /path/to/repo log --oneline -5
git -C /path/to/repo rev-parse --short HEAD
```

### AP3 Sub-class C: Path Resolution Hiding (built-in prompt removed in 2.1.207 — no mechanical guard left)

**Trigger**: `cd <path> && <command> ... 2>/dev/null` — cd makes relative path resolution
depend on CWD; `2>/dev/null` swallows errors, causing path issues to fail silently.

Cases: 10 (cd + find + 2>/dev/null), 11 (cd + grep), 15 (cd + gh pr view)

```bash
# Wrong
cd /path/to/project && find . -name "*.py" 2>/dev/null

# Fix A: use absolute path; keep error output
find /path/to/project -name "*.py"

# Fix B: use Read/Grep tool (Claude tool layer) with absolute path
# Glob: /path/to/project/**/*.py
```

> **Update (Claude Code 2.1.207)**: the built-in confirmation that used to fire on this pattern
> was removed — the changelog reads "Fixed compound commands with `cd` prompting for permission
> when the only output redirect was to `/dev/null`". AP3-C therefore has **no mechanical guard
> left**: the F1 class no longer prompts, and this repo's own hooks (`bash-ap1-inline-check.sh`,
> `bash-ap2-check.py`) target AP1/AP2 forms, not this one. Agent discipline — absolute path or
> the Read/Grep tool — is now the **sole** defence, which is why this sub-class stays
> highest-priority. (Verified against the official changelog, 2026-07-19.)

### AP3 Summary

| Sub-class | Hook | Cases | Fix |
|-----------|------|-------|-----|
| A: CWD pollution | None (silent) | 4/17/18 | `--directory` flag or subshell |
| B: cd-before-git | Class C (partial) | 7/9/12 | `git -C <path>` |
| C: path resolution hiding | None since 2.1.207 (was Class F1) | 10/11/15 | Absolute path / Read/Grep tool |

## Prefer Claude Built-in Tools for Code Search

When searching code, **prefer Grep/Glob tools over bash `rg`/`grep`/`find`**.

Common violation: `cd $(git rev-parse --show-toplevel) && rg ... 2>/dev/null | head -10`
triggers AP3-A (CWD pollution), AP3-C (`2>/dev/null` hiding), AP1 (output filter `| head`),
and the `$()` subshell structure triggers the Claude Code parser confirmation dialog.

| bash (Wrong) | Claude Tool (Fix) |
|-------------|------------------|
| `cd $(...) && rg -n 'pattern' path/ --type dart 2>/dev/null` | Grep `pattern` in `path/` include `*.dart` |
| `cd $(...) && find path/ -name '*auth*.dart' \| head -10` | Glob `path/**/*auth*.dart` |
| `cd $(...) && rg -rn 'class.*User' path/ --type py 2>/dev/null` | Grep `class.*User` in `path/` include `*.py` |

Advantages: zero CWD dependency, zero PreToolUse hook triggers, no manual `| head` truncation.

**Note**: Grep/Glob tools have a result cap (no "N more results" warning). For complete result
lists (global rename, migration audits), use `rg -l` or `find` with absolute paths, then Read
each file. Grep tool respects `.gitignore`; to search ignored files (`build/`, `vendor/`),
use `rg --no-ignore`.

**Scope**: applies to "find where code is" / "search for pattern" scenarios only.
Use bash when you need bash-specific features (`rg --json`, `find -exec`, `wc -l`), but
follow the AP rules above.

### Codebase Research SOP

When an agent needs to traverse N files for the same operation (read header, search pattern,
check frontmatter), choose the approach by N and complexity:

| Situation | Correct approach | Anti-pattern |
|-----------|-----------------|--------------|
| N ≤ 5 files, read first N lines | N parallel Read calls (`limit: N`) | `for f in ...; do head -N "$f"; done` |
| N ≤ 5 files, search pattern | N parallel Grep calls | `for f in ...; do grep "pat" "$f"; done` |
| N > 5 or complex logic | Extract to `scripts/scan_<thing>.{sh,py}` + single bash call | Inline for-loop with multiple body statements |
| Cross-repo / cross-subtree | Spawn Explore subagent; specify "use Read/Glob/Grep, no bash for-loops" in prompt | Main-session bash multi-file traversal |

**Counter-example** (the for-loop pattern that triggered AP1 + Quoting Rule 5 confirmation
dialog when reading multiple SKILL.md files during codebase research):

```bash
# Wrong: for-loop body > 1 line + "dollar-f" appears twice
for f in /path/a.md /path/b.md /path/c.md; do
  echo "=== $f ==="
  head -15 "$f"
  echo
done
```

Problems: (1) body has 3 statements — AP1 for-loop sub-type; (2) `"$f"` appears twice —
Rule 5 false positive, cannot be prefix-wildcard allow-listed; (3) wrong tool: reading first
N lines of multiple files is a Read tool operation, not a bash task.

Fix: replace with N parallel Read calls (`limit: 15`), one per file.

## 5-Second Self-Check Before Writing Bash

- [ ] Multi-line, heredoc, or `\` continuation?
- [ ] More than two levels of nested quotes?
- [ ] Embedded Python/Node/complex jq?
- [ ] Multiple `if`/`elif`/`case` branches?
- [ ] Complex parameter expansion (`${var//pat/rep}`, indirect `${!var}`)?

>=2 yes → split bash calls / extract script / use the right tool

- [ ] Emoji, em dash (—), en dash (–), or zero-width space in strings?

yes → replace per AP2 table (independent rule; does not count toward threshold above)

- [ ] Command contains `cd <path> &&`?

yes → classify sub-type: git → `git -C`; non-git → `--directory`; with `2>/dev/null` → absolute path.

- [ ] Pure search (find pattern / list files)?

yes → prefer Grep/Glob tool.

## AP2 Auto-Detection

`.claude/hooks/bash-ap2-check.py` is a PreToolUse hook that auto-detects and blocks AP2.
Scope: em dash / en dash / zero-width space / U+2300-U+23FF / U+2600-U+27BF / U+1F000-U+1FAFF.
(U+2400-U+25FF Box Drawing intentionally excluded to avoid false positives from `tree`/`eza`.)

AP1 complexity detection requires reasoning; use the 5-second check. Exceptions: the following
mechanically-detectable sub-types are covered by `bash-ap1-inline-check.sh`:

- `python -c` multi-line, `osascript` heredoc
- `grep "...\|..."` double-quote BRE alternation (Case 25)
- `$(outer "$(inner)")` reverse-nested subshell (Case 26)
- `rg '...\|...'` BRE alternation in ERE tool (Detection 6)

## High-Frequency Violations (AP1 — Decompose Immediately)

These patterns are violations as soon as they appear; no scoring needed.

### `python3 -c "..."` with newlines

```bash
# Wrong: multi-line + embedded Python = score 2
uv run python3 -c "
import asyncio
...
    result = await session.execute(text('''SELECT ...'''))
" 2>&1

# Fix: extract to standalone .py; use --directory instead of cd
uv run --directory /path/to/project python3 scripts/check_stats.py
```

A `# comment` inside `python3 -c` also triggers class B hook
("Newline followed by # inside a quoted argument").

### `osascript << 'TAG'` heredoc

```bash
# Wrong: multi-line heredoc + embedded AppleScript = score 2
osascript << 'ASCRIPT'
tell application "System Events"
    ...
end tell
ASCRIPT

# Fix: extract to .applescript file
osascript scripts/check_windows.applescript
```

`$(cat <<'EOF')` for commit message plain text is exempt; osascript/DSL heredoc is **not**.

### `cd /abs/path && cmd` (Stateful cd)

Quick lookup; see AP3 for details:

- `cd ... && git <cmd>` → `git -C <path> <cmd>` (Sub-class B)
- `cd ... && uv run` → `uv run --directory <path>` (Sub-class A)
- `cd ... && cmd 2>/dev/null` → use absolute path, remove cd (Sub-class C)

### `cat <<'EOF' | command` (heredoc-pipe)

The pipeline AST node exceeds parser capacity, triggering `Unhandled node type: pipeline`
(Case 23). Even at AP1 score 1/5, it must be blocked.

```bash
# Wrong: heredoc piped directly; parser fails at pipeline node
cat << 'ARTIFACT_EOF' | spectra new artifact --stdin
## content ...
ARTIFACT_EOF

# Fix: Write tool to file first; use < redirect
spectra new artifact --stdin < /tmp/artifact_input.md
rm -f /tmp/artifact_input.md
```

### Output filter pipeline `| grep -v "..."`

```bash
# Wrong: bash pre-filter instead of letting Claude read full output
cmd 2>&1 | grep -v "INFO"

# Fix: remove grep filter; Claude receives complete output
cmd 2>&1
```

### A Pipe Masks the Upstream Command's Exit Code (silent false-green gate)

The previous section bans output-filter pipes because Claude cannot see the full output. There is
a **second, sharper** failure: `cmd | tail`/`head`/`grep` reports the **last stage's** exit code,
not `cmd`'s. A failing `cmd` piped into a succeeding `tail` yields exit `0` — so any gate that reads
that status (a background-task wrapper, an `&&` chain, `if cmd | tail; then`) concludes the command
**passed** when it failed.

```bash
# Wrong: make ci fails (Error 1), but tail exits 0, so the pipeline exits 0.
# A background/CI wrapper reading the exit code reports "passed" -- a false green.
make ci 2>&1 | tail -40

# Fix A (preferred): do not put a gate command upstream of a pipe. Truncation is a
# separate concern -- write full output to a file, then Read it with the Read tool.
make ci > /tmp/ci.log 2>&1      # exit code is make ci's; then Read /tmp/ci.log

# Fix B: when you must pipe, make the pipe fail loud on any stage.
set -o pipefail                 # pipeline exits non-zero if ANY stage fails
make ci 2>&1 | tail -40
# or inspect ${PIPESTATUS[0]} explicitly (the upstream command's real status)
```

This is the exit-code twin of the output-filter rule above, and a member of the same
"green comes from asking the wrong question" family as the pre-commit-formatter false-green trap
(a documented CLAUDE.md gotcha): the check runs, reports success, and the success is about the
wrong thing. Before trusting a green from a piped command, ask **whose** exit code you just read.

(Source: PR #299 retro -- `make ci 2>&1 | tail -40` reported exit 0 while `make ci` was Error 1;
the failure was nearly shipped as a passing CI.)

### Before Attributing a Red Result to Your Diff

Three ways a red signal turns out not to be about your change. Check these before debugging your
own diff — and equally, before concluding a local green means anything.

**1. Stray untracked directories on disk.** `pytest` collects from any directory matching its
discovery rules, whether or not git tracks it. Leftover generated directories (historically
`tasks/nightly_agent/tests/`, but any `tasks/*/tests/` from an aborted run) produce failures
indistinguishable from real ones — and they follow the checkout, not the branch.

```bash
git -C <repo> ls-files <failing-dir>        # empty output == git does not track it == likely stray
git -C <repo> clean -ndx <failing-dir>      # preview EXACTLY what removal would delete
```

An empty `git ls-files` proves the path is *untracked*, not that its contents are *safe to
delete* — it is one probe, not a safety proof (see rule 15's `rm -rf` row on why the probes do
not tell you enough). `git clean -fdx` then permanently removes every untracked **and ignored**
file under the path (`.env`, build artifacts) with no Trash, which makes it a
[rule 15](15-irreversible-operations.md) Category 4 operation the agent must **not** run
autonomously. Confirm the `-ndx` preview lists only disposable generated files, then let the user
run `clean -fdx` (or use `trash`).

Note `.gitignore` does not help here: ignored files are still on disk and still collected —
see the `.gitignore` ≠ absent-from-disk rule in
[`02-error-and-import.md`](02-error-and-import.md).

**2. Pre-existing failures unrelated to your change.** `make release` runs `gates.sh`, which runs
`uv run pytest` as a gate under `trap ERR`. Any pre-existing failure — including stray-directory
noise from case 1 — aborts the release mid-flight before any commit or tag exists. Confirm a zero-
failure baseline *before* starting a release, not after it rolls back.

**3. macOS-green does not imply Linux-green.** A local `make ci` pass on macOS says nothing about
platform-specific assumptions (BSD vs GNU flags, `realpath` availability, font lists, locale).
Watch the remote run before declaring the task done:

```bash
# Filter to THIS branch's latest run -- an unfiltered `--limit 1` returns the most recent run
# across ALL branches/workflows and can watch someone else's. Split the subshell out of the outer
# double-quotes too (rule 13 Quoting Rule 2: `gh run watch "$(...)"` trips `Unhandled node type: string`).
BRANCH=$(git branch --show-current)
RUN_ID=$(gh run list --branch "$BRANCH" --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID"
# Simplest when a PR exists: gh pr checks <N> --watch
```

This is distinct from the `git add`-before-`make ci` divergence documented in `CLAUDE.md` — that
one is about git's index, this one is about the platform.

### `rg '...\|...'` BRE alternation in ERE tool (silent empty results)

`grep` default BRE: `\|` is alternation. `rg` uses Rust ERE: `|` is alternation, `\|` is
literal pipe. Migrating `grep` patterns to `rg` silently returns 0 results with no error.

| Tool | Alternation | `\|` means |
|------|------------|-----------|
| `grep` (BRE) | `\|` | alternation |
| `grep -E` | `\|` | literal pipe |
| `rg` | `\|` | literal pipe |

```bash
# Wrong: rg with BRE syntax searches for literal pipe, not alternation
rg -rl '五層\|Event Storm\|ezSpec' /path

# Fix A (preferred): use Grep tool (| for alternation)
# Grep tool: 五層|Event Storm|ezSpec  in /path

# Fix B: rg ERE syntax
rg -rl '五層|Event Storm|ezSpec' /path

# Fix C: multiple -e flags
rg -l -e '五層' -e 'Event Storm' -e 'ezSpec' /path
```

`bash-ap1-inline-check.sh` Detection 6 auto-detects and blocks this pattern.

## AP1 Auto-Fix Triggers

When any of the following applies, **stop and invoke the `bash-to-script` subagent** to
extract the bash logic into a standalone script under `scripts/`:

1. `for` loop body contains pipe or `if` (Cases 21/22)
2. heredoc followed by `| command` (Case 23)
3. inline `python -c` with newlines (hook already catches; subagent can generate `.py` directly)
4. inline `osascript` heredoc (same)

Example prompt:

```text
Task: extract this bash to a script for scanning EdgeInsets patterns across files.
bash:
  for f in a.dart b.dart; do
    grep -n "EdgeInsets" "$f" | grep -v "YibiSpacing"
  done
```

The subagent will: read existing naming in `scripts/`, choose a filename, write a clean script
(shebang, `set -euo pipefail`, no AP1 violations), and report `CREATED: scripts/xxx.sh` and
`INVOKE: bash scripts/xxx.sh`.

**Not applicable**: Cases 25/26 (quoting fix), Cases 20/23 (split bash call). These do not
need the subagent; just apply the corresponding fix directly.

## exec wrapper Penetrates deny rule (2026-05)

Claude Code deny rules now see through `env`/`sudo`/`watch`/`ionice`/`setsid`:

```bash
# These are also blocked by deny rules
sudo rm -rf /dangerous/path
env DANGEROUS_VAR=1 bash script.sh
```

Do not assume a wrapper bypasses a deny rule. When blocked, follow rule 15 standard behavior:
describe the operation and ask the user to run manually.

## Moved to Rule 17 (Shell Script Authoring)

These sections now live in [`17-shell-script-authoring.md`](17-shell-script-authoring.md), which
loads only when a shell script, hook, Makefile, or CI config is touched. Titles are unchanged:

- `|| exit 0` / `|| true`; `file:line`-only diagnostic filters; grepping a success banner
- `realpath` on macOS; `pwd -P` and file symlinks; `GIT_DIR` / `GIT_WORK_TREE` overriding `git -C`
- process-substitution multi-line reads; `trap ERR` rollback; never `&&`-gate a restore
- exemption regex precision; AP2 exemption verb-prefix lock
- diagnostics to stderr; `[SKIP]` vs `[WARN]`; tracking-ID sentinels; jq `--arg` empty string
- single-quote semantics (hook note); `\$` in skill bodies; Gemini / agy CLI gotchas
- Quoting Rule 6 (Python comment `"`) and Quoting Rule 7 (bare `$VAR` + non-ASCII)

## Complete Methodology

Full cross-project version: skill `bash-anti-patterns` (includes before/after examples,
agent self-check checklist, technical background, optional PreToolUse hook).

---

## Shell Quoting Hygiene

> **Note**: This section was originally rule 14 and was merged into rule 13 in PR-B to reduce always-loaded token count.

Six quoting error categories from Cases 3/8/16/17/24/25/26; hook classes E (`simple_expansion`), D (parser failure), or E-false-positive.

## Quoting Rule 1: Quote Variables Inside Subshells

`$VAR` inside `$(cmd $VAR)` without quotes causes word-split on paths with spaces.
Hook reports `simple_expansion`.

```bash
# Wrong: $MAIN_REPO unquoted inside $()
echo "path: $(ls $MAIN_REPO/docker-compose.yml 2>/dev/null || echo 'not found')"

# Fix: split into separate bash call
ls "${MAIN_REPO}/docker-compose.yml" 2>/dev/null || echo 'not found'
```

Scope: any `$(cmd $VAR ...)` form — always quote as `"$VAR"` or `"${VAR}"`.

## Quoting Rule 2: `"$(cmd)"` — Outer Double-Quote Wrapping Subshell

Outer double-quote containing `$(...)` subshell; parser cannot handle this structure,
reports `Unhandled node type: string`. **Triggers even if there are no inner quotes.**

```bash
# Wrong A: inner quotes inside subshell
echo "Main updated to: $(git -C "$MAIN_REPO" rev-parse --short HEAD)"

# Wrong B: no inner quotes (still triggers)
git -C "$(git rev-parse --show-toplevel)" branch --show-current

# Fix (both cases): split into temp variable + separate bash call
WT=$(git rev-parse --show-toplevel)
git -C "$WT" branch --show-current

HEAD=$(git -C "$MAIN_REPO" rev-parse --short HEAD)
echo "Main updated to: $HEAD"
```

## Quoting Rule 3: Use Single Quotes for grep BRE Alternation

`grep "pat1\|pat2"` — `\|` inside double quotes; analyzer cannot classify the backslash-escaped
`|` in a string node, reports `Unhandled node type: string`. Triggers even at AP1 score 1/5 (Case 25).

```bash
# Wrong: double-quote BRE alternation
grep -i "media\|cdn\|delivery" file.txt

# Fix A (preferred): single-quote BRE
grep -i 'media\|cdn\|delivery' file.txt

# Fix B: ERE (-E flag)
grep -Ei 'media|cdn|delivery' file.txt
```

Scope: any `grep "...\|..."` — always use single quotes or `-E` flag.

## Quoting Rule 4: `$(outer "$(inner)")` — Must Split bash Call

Outer `$()` wrapping double-quote wrapping inner `$()` is the reverse of Rule 2; parser
fails the same way (Case 26).

```bash
# Wrong
MAIN_REPO=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")

# Fix: two separate bash calls
GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN_REPO=$(dirname "$GIT_COMMON")
```

Rule 2 direction: `"..." → $() → "$VAR"`. Rule 4 direction: `$() → "$(inner)"`. Same root cause.

**Inside a worktree-isolated session Claude Code itself may refuse, not prompt.**
Claude Code 2.1.274: "Fixed worktree-isolated sessions accepting Bash commands with certain
nested shell expansions; these are now refused". The changelog does not list which expansions
qualify, so do not assume the shapes in Rules 2 and 4 are the complete set. In this repo
`bash-ap1-inline-check.sh` already blocks Rule 4's shape (Case 26) wherever the hook runs, so a
main-checkout-versus-worktree difference can only show up for shapes that hook does not catch.
Two exceptions let Rule 4's shape through the hook: its `git commit -m "$(cat <<` exemption, and
its fail-open on internal errors (`trap 'exit 0' ERR`).
The fix is unchanged: split into separate bash calls.
(Source: Claude Code CHANGELOG 2.1.274, read 2026-09-21 for the W39 release-note review.)

## Quoting Rule 5: Variable Expansion False Positive (Case 24)

Claude Code's built-in parser broadly intercepts all `expansion`/`simple_expansion` AST nodes
**regardless of whether they are already quoted** — both forms trigger:

| Form | Hook message |
|------|-------------|
| `"${VAR}"` bracket form | `Contains expansion` |
| `"$VAR"` plain form | `Contains simple_expansion` |

Both are **false positives** — bash syntax is correct; interception is a parser design choice.

```bash
# Both forms trigger (syntax correct; parser intercepts)
test -n "${CODEX_API_KEY}" -o -n "${OPENAI_API_KEY}" && echo "AUTH: KEY_SET" || true
```

**Fix depends on context**:

**A. Single-line command (`cmd "$VAR"`) → add to allow list** (settings.json):

```json
"Bash(test -f *)",
"Bash(git -C /Users/<you>/<repo> status:*)",
"Bash(basename *)",
"Bash(dirname *)",
"Bash(test -n *)",
"Bash([ -n *)"
```

**B. Script with >=2 `"$VAR"` expansions → split bash calls or extract to script**:

Multi-line scripts cannot be covered by prefix wildcard allow-list patterns:

| Scenario | Fix |
|----------|-----|
| 2-4 lines with dependent variables | Split into separate bash calls, each covered by its own allow-list entry |
| 5+ lines or repeated use | Write `scripts/foo.sh`; bash call becomes just `bash scripts/foo.sh` |

**Threshold**: >=2 `"$VAR"` expansions in one bash call = AP1 sub-type; must split or extract.

**Never use `printenv` or `echo $VAR` to print key values** — this logs API keys in plain text to the session transcript. Always use `test -n` to check key existence.

Root cause: Claude Code's built-in parser layer (outside this repo's hook scope).
v3 backlog: hook should exempt `expansion`/`simple_expansion` nodes already wrapped in `"..."`.

## Decision Flow

**`$(...)` patterns** (Rules 1-2):

```text
Writing $(...)  →  Contains $VAR?
                     Yes → quote it: "$VAR" (Rule 1) → continue
                     No → continue
                   Wrapped in outer "..."?
                     No → pass
                     Yes → contains inner "..."?
                            No → pass
                            Yes → split into separate bash call (Rule 2)
```

Note: `"${VAR}"` and `"$VAR"` as standalone args (e.g., `test -n "$VAR"`) both trigger
false positives; see Rule 5.
If a variable has adjacent prefix/suffix (e.g., `"${prefix}_suffix"`), do not change to
`"$VAR"` (would read `$prefix_suffix`); write as `"${prefix}"_suffix` and add to allow list.

**Other patterns quick reference** (Rules 3-5; Rules 1-2: see flow above):

| Pattern | Hook message | Rule | Fix |
|---------|-------------|------|-----|
| `grep "...\|..."` double-quote BRE | `Unhandled node type: string` | Rule 3 | Single quote or `-E` flag |
| `$(outer "$(inner)")` reverse-nested | `Unhandled node type: string` | Rule 4 | Split two calls |
| `"${VAR}"` as test arg | `Contains expansion` (false positive) | Rule 5 | Add to allow list |
| `"$VAR"` as test arg | `Contains simple_expansion` (false positive) | Rule 5 | Add to allow list |

## Hook Category Reference

| Error type | Hook message | Root cause |
|-----------|-------------|-----------|
| `$VAR` inside `$()` unquoted | `simple_expansion` | Rule 1 |
| `"$(cmd "$VAR")"` double-quote conflict | `Unhandled node type: string` | Rule 2 |
| `$'...'` ANSI-C string | `ansi_c_string` | Avoid ANSI-C escape string syntax |
| `grep "...\|..."` double-quote BRE | `Unhandled node type: string` | Rule 3; auto-blocked |
| `$(outer "$(inner)")` reverse-nested | `Unhandled node type: string` | Rule 4; auto-blocked |
| `"${VAR}"` bracket form (already quoted) | `Contains expansion` | Rule 5; **false positive**; add to allow list |
| `"$VAR"` plain form (already quoted) | `Contains simple_expansion` | Rule 5; **false positive**; add to allow list |
| `echo "exit:$?"` / `[ $? -ne 0 ]` | `Contains simple_expansion` | Rule 5; `$?` intercepted regardless of quotes; use `if ! <cmd>; then` |

## $? Special Case (PR #24)

`$?` (exit status variable) is a `simple_expansion` AST node; Rule 5's "regardless of quotes" applies:

| Pattern | Triggers? | Correct alternative |
|---------|----------|-------------------|
| `echo "exit:$?"` | Yes | Remove the line; bash block already has `if ! cmd` |
| `echo exit:$?` | Yes | Same |
| `[ $? -ne 0 ]` | Yes | `if ! <command>; then` |
| `if ! gemini ...; then` | No | Recommended form |

Do not add any `$?`-related code after commands in SKILL.md bash blocks — use
`if ! <command>; then echo '[FAIL]...'; exit 1; fi` instead of all `if [ $? -ne 0 ]` forms.
