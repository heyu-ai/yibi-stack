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

### `|| exit 0` / `|| true` Turns a Real Result Into a Silent Skip

`|| true` masks the exit code and continues; `|| exit 0` masks it and exits immediately.
Either way the caller cannot distinguish "failed to run" from "ran and found something".

```bash
# Wrong: exit code masked
agy review ... || true

# Fix: capture status and output separately
EXIT=0
OUT=$(agy review ...) || EXIT=$?
if [ -z "$OUT" ]; then
  echo "[FAIL] no output (exit $EXIT)" >&2; exit 1
fi
if [ "$EXIT" -ne 0 ]; then
  echo "[FAIL] execution failed (exit $EXIT)" >&2; exit 1
fi
```

Tool contract matters: `agy`/`codex review` use non-zero for execution failure; `mypy`/`pytest`
use non-zero for "found findings". Match the branch logic to the tool's contract. Silent-on-clean
tools (`ruff check`) need exit-code gating, not empty-output gating.

### A `file:line`-Only Diagnostic Filter Drops Invocation Errors

A filter written against the *diagnostic* format silently drops errors that do not have that
format — most importantly, the ones that mean the tool never ran.

mypy 2.x reports config and invocation failures as `mypy: error: <msg>` with **no file and no
line number**. A filter matching only `[0-9]+(:[0-9]+)?: (error|note):` matches zero lines, so
"no diagnostics" is reported as clean — even though mypy analyzed nothing at all.

```bash
# Wrong: counts parsed diagnostics; `mypy: error: Missing target module, package, files, or
# command.` yields a count of 0 == "clean"
COUNT=$(uv run mypy tasks/ | grep -cE '[0-9]+(:[0-9]+)?: (error|note):')

# Correct: the exit code already answers the question the filter was approximating
LOG=$(mktemp)   # unique per run; a fixed /tmp/mypy.log races under parallel runs and can truncate
                # a file the path already symlinks to
if ! uv run mypy tasks/ > "$LOG" 2>&1; then
  echo "[FAIL] mypy failed -- see ${LOG} (may be diagnostics OR an invocation error)" >&2
  exit 1
fi
```

Generalization: whenever you parse a tool's output to decide pass/fail, you have replaced the
tool's own verdict with a regex, and the regex does not know about the failure modes it was not
written for. Prefer the exit code; if you must parse, add an explicit arm for
"tool-level error" (`^mypy: error:`) alongside the per-file diagnostics.

### Grepping a Success Banner Breaks When the Banner Changes

`flutter test` prints `All tests passed!` — except when any test was **skipped**, where it prints
`All other tests passed!` instead. A gate written as `grep "All tests passed"` therefore reports
failure for a perfectly green run that happened to skip a test.

```bash
# Wrong: false FAILURE whenever any test is skipped
flutter test | grep -q "All tests passed"

# Correct: use the exit code, which already encodes the verdict
flutter test
```

Do not reach for a banner grep even as a "double-check": `flutter test | grep ...` returns
**grep's** exit code, not flutter's (the pipe-masks-exit-code trap at the top of this file), so it
can report success on a failing run whose output happened to contain the banner earlier. If you
genuinely must inspect the banner, do it without a pipe — run `flutter test`, keep its exit code,
then grep the saved output separately (and match `All (other )?tests passed` to survive the
skipped-test variant).

Success banners are **presentation**, not API — they change with tool versions and with run
conditions. Exit codes are the contract. Same family as the two sections above: the check ran and
reported confidently about the wrong thing.

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

### `realpath` — Not Available on macOS < Ventura

`realpath` is absent on macOS Monterey and earlier. Scripts using it fail with `command not found`
(silently in some contexts), making the resolved path empty or causing exit 1.

```bash
# Wrong: realpath unavailable on macOS < Ventura
SCRIPT_DIR=$(realpath "$(dirname "$0")")

# Fix: portable form -- resolve symlinks via cd+pwd
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
```

Use `cd "$(dirname "$0")" && pwd` in shell scripts that need the script's own directory —
but only when the script is **not reached through a file-level symlink**; see the next section
for that case.

### `pwd -P` Does Not Resolve a *File* Symlink (silent wrong directory)

The portable form above resolves symlinks on **directories in the path**, never the symlink on
the **script file itself**. `dirname` strips the filename first, so a file symlink is gone before
`pwd -P` ever runs — it then resolves the *link's own* directory and returns it with no error.

This bites when the same self-locate block is copied to a new install location:

| Where the symlink sits | Example | `cd "$(dirname "$0")" && pwd -P` |
|------------------------|---------|----------------------------------|
| On a **directory** | `~/.claude/skills/<name>` → `<repo>/skills/<name>` | correct — resolves into the repo |
| On the **file** | `~/.agents/bin/<tool>` → `<repo>/scripts/<tool>` | **wrong** — returns `~/.agents/bin` |

```bash
# Wrong through a file symlink: silently yields the symlink's own directory
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

# Fix: walk the symlink chain first (macOS has no readlink -f), then resolve the directory.
# The depth cap matters: a circular link (a -> b -> a) otherwise hangs forever with no output.
SOURCE="${BASH_SOURCE[0]}"
_depth=0
while [ -L "$SOURCE" ]; do
  _depth=$((_depth + 1))
  if [ "$_depth" -gt 40 ]; then echo "[FAIL] symlink loop: $SOURCE" >&2; exit 1; fi
  _link_dir=$(cd -P "$(dirname "$SOURCE")" && pwd)
  SOURCE=$(readlink "$SOURCE")
  case "$SOURCE" in
    /*) ;;
    *) SOURCE="$_link_dir/$SOURCE" ;;
  esac
done
SCRIPT_DIR=$(cd -P "$(dirname "$SOURCE")" && pwd)
```

Rule: before copying a self-locate block to a new location, check the **shape** of the symlink
that will reach it, and verify by **executing through the symlink** — not just directly. Running
the script in place passes in both designs, which is exactly why this ships unnoticed.

Reference implementation: `scripts/resolve-skill-repo`. (Source: PR #224 — the naive form was
correct for `~/.claude/skills/` and silently wrong the moment the same logic moved to
`~/.agents/bin/`.)

### `GIT_DIR` / `GIT_WORK_TREE` Override `git -C` (defeats self-location)

`git -C <dir>` does **not** win over an inherited `GIT_DIR` / `GIT_WORK_TREE`. When those are
set, git reports **that** repository and ignores `-C` entirely. Any "find my own checkout" logic
built on `git -C "$SCRIPT_DIR" rev-parse --show-toplevel` is therefore defeatable by an
environment variable, and returns a **different, valid** repo — so an identity gate that checks
for a marker file cannot catch it either (the other checkout has the marker too).

This is not an exotic scenario: **git sets `GIT_DIR` while running hooks**, so any script invoked
from a hook context inherits it. A repo that leans on pre-commit hooks is exposed by default.

```bash
# Wrong: an inherited GIT_DIR silently redirects this to another checkout
SKILL_REPO=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)

# Fix: clear git's repo-selection vars for the resolution call only
_GIT="env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE git"
SKILL_REPO=$($_GIT -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)
```

**Scope the clearing deliberately.** Clear it only on calls that ask "where does *this script*
live". A call that asks "which repo is the *caller* working in" (project-name detection, branch
reporting) must keep honouring the caller's git environment — clearing it there breaks the very
answer it wants. Both kinds often sit in the same script.

Verify with a probe, not by reading: point `GIT_DIR`/`GIT_WORK_TREE` at a second checkout that
is **also valid** (has the marker), and assert the resolver still returns its own. A test whose
decoy checkout is invalid proves nothing — the identity gate would reject it anyway.
(Source: PR #224 round-5 review / PR #233.)

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

### Process substitution multi-line output consumption (2026-05)

`read -r A B < <(cmd)` reads one line then splits by IFS; if `cmd` outputs multiple lines via
multiple `print()` calls, subsequent variables are always empty — silently.

```bash
# Wrong: read consumes only the first line; DUR is always empty
read -r FILE DUR < <(python3 -c "print(fp); print(dur)")

# Fix: consecutive reads, one per line
{ read -r FILE; read -r DUR; } < <(python3 -c "print(fp); print(dur)")
```

## exec wrapper Penetrates deny rule (2026-05)

Claude Code deny rules now see through `env`/`sudo`/`watch`/`ionice`/`setsid`:

```bash
# These are also blocked by deny rules
sudo rm -rf /dangerous/path
env DANGEROUS_VAR=1 bash script.sh
```

Do not assume a wrapper bypasses a deny rule. When blocked, follow rule 15 standard behavior:
describe the operation and ask the user to run manually.

## trap ERR Rollback (External Skill Contract Constraint)

When step ordering can't be changed (downstream reads upstream's state), use `trap ERR` to
auto-revert on failure. `set -e` and `trap ERR` are both **load-bearing** — without `set -e`,
the script rolls back then continues into the commit.

```bash
set -euo pipefail

rollback() {
    echo "[FAIL] Release failed -- reverting version files" >&2
    git checkout HEAD -- pyproject.toml CHANGELOG.md \
        || echo "[FAIL] rollback failed -- revert by hand" >&2
    git checkout HEAD -- ':(glob)plugins/*/package.json' \
        || echo "[FAIL] rollback failed -- revert by hand" >&2
}
trap rollback ERR

# ... file mutation steps ...
"$GATES_SH"

trap - ERR   # clear before commit; post-commit failures need git reset HEAD~1
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): v${TAG_VERSION}"
```

Key points:

- Use `checkout HEAD --`, not bare `checkout --` — bare form reads the index, fails silently
  when a concurrent session staged the same files.
- `trap - ERR` before the commit — post-commit failures need `git reset HEAD~1`.
- Git pathspec `*` crosses `/` — use `:(glob)` for single-level matching.
- Isolate nested `trap` in a subshell to avoid overwriting the outer `trap ERR`.

## Never `&&`-Gate a Restore Behind the Step That Might Fail

`&&` means the restore runs only if the risky step **succeeds** — exactly when it's not needed.

```bash
# Wrong: some-tool fails → restore skipped → deletion permanent
rm -rf "$OTHER/dir" && some-tool --do-thing && git -C "$OTHER" checkout HEAD -- dir

# Fix: trap EXIT + set -e — restore runs on any exit, set -e propagates failure
set -e
restore() { git -C "$OTHER" checkout HEAD -- dir; }
trap restore EXIT
rm -rf "$OTHER/dir"
some-tool --do-thing
```

| Signal | Use when |
|--------|----------|
| `trap … ERR` | Mutation should survive success (e.g. version bump stays after gates pass) |
| `trap … EXIT` | Mutation is temporary scaffolding — undo on every path |

`trap EXIT` alone does NOT propagate the failure status — `set -e` does. Use both.
Add catchable signals: `trap restore EXIT INT TERM HUP`. Make the restore idempotent
(`SIGTERM` runs it twice if trapped on both `EXIT` and `TERM`). Do not `exec` after a
mutation — `exec` replaces the shell and skips the `EXIT` trap.

## Exemption Regex Must Enumerate Precisely, Not Use Open Glob (PR #23)

A hook exemption using `[^;|\n&]*` (open glob) instead of precise flag enumeration appears to
only widen "flag between git and commit", but actually allows the word `commit` to appear in
the *argument* of another git subcommand, causing AP2 detection to be silently exempted.

```python
# Wrong: open glob lets "git notes add -m 'fix about commit'" trigger exemption
if re.search(r"git\b[^;|\n&]*\bcommit\b", cmd):
    strip_payload()

# Fix: enumerate git global flags precisely (source: man git OPTIONS)
_GIT_GLOBAL_FLAG = r"(?:\s+(?:-C\s+\S+|-c\s+\S+|--git-dir=\S+|...))"
if re.search(r"git\b" + _GIT_GLOBAL_FLAG + r"*\s+commit\b", cmd):
    strip_payload()   # only real "git commit" is exempted
```

Rule: **exemption regex must precisely describe the exempted command type**; open `[^chars]*`
globs must become enumerations or subcommand-position constraints when the target word can
appear in another command's arguments.

## AP2 Exemption Requires Verb Prefix Lock (PR #92)

When exempting a command's argument values from AP2 scanning (e.g., user data in
`--topic`/`--summary` flags), the exemption regex must require the **verb prefix** before the
module name — not just the module name alone.

```python
# Wrong: no verb prefix; "echo tasks.session_memory" or grep output also triggers exemption
_SM_RE = re.compile(r"-m\s+tasks\.session_memory\b")

# Correct: require python verb before -m tasks.session_memory
_SM_RE = re.compile(r"\bpython[\w.]*\b[^;|\n&]*-m\s+tasks\.session_memory\b")
```

Without the `python` prefix, any bash command whose output or arguments happen to contain
`-m tasks.session_memory` (e.g., `grep -r tasks.session_memory .`) would also be exempted
from AP2 scanning — an actual AP2 evasion hole.

Design principle: **exemption always requires a verb + separator** to anchor the command type.
This is symmetric with `_GIT_COMMIT_RE` requiring `git` before `commit` (PR #23).

## Shell Script Diagnostics Must Go to stderr (PR #31)

`[WARN]`, `[FAIL]`, `[SKIP]` diagnostic `echo` calls must always use `>&2` — stdout may be
parsed, redirected, or captured in CI pipelines; mixing in diagnostics causes silent downstream failures.

```bash
# Wrong: diagnostic goes to stdout
echo "  [WARN] gitCommitSha missing, using version as tracking ID"

# Fix: always >&2
echo "  [WARN] gitCommitSha missing, using version as tracking ID" >&2
echo "  [FAIL] jq not installed; run: brew install jq" >&2
```

Rule: any `echo` with `[WARN]`/`[FAIL]`/`[SKIP]` prefix must use `>&2`.
`[OK]` goes to stdout if it is a user-visible completion summary; stderr if it is debug info.

### `[SKIP]` vs `[WARN]` Semantics for Missing Resources

When a bootstrap or install script silently skips a step because a required resource (file,
config, binary) does not exist, use `[WARN]` — not `[SKIP]` — and include a repair command.
Silent `[SKIP] + exit 0` hides the problem; the user does not know the step was incomplete.

```bash
# Wrong: silent skip — user gets no feedback; resource stays unconfigured
if [ ! -f ~/.claude/settings.json ]; then
  echo "  [SKIP] settings.json not found" >&2
  exit 0
fi

# Correct: warn with repair instruction — user knows what to do next
if [ ! -f ~/.claude/settings.json ]; then
  echo "  [WARN] ~/.claude/settings.json not found." >&2
  echo "         Start Claude Code once to generate it, then re-run: make patch-agy-allow-list" >&2
  exit 0
fi
```

Scope: `make install-all` chains and any bootstrap script whose steps have prerequisites.

## Tracking ID System Must Not Use Hardcoded Sentinels as Fallback (PR #31)

Idempotency tracking (STATE_FILE, cache key) must not fall back to a hardcoded sentinel
string (`"unknown"`, `"none"`) — if two runs both produce the same sentinel, ID comparison
always matches and upgrade detection is silently bypassed.

```bash
# Wrong: fallback to hardcoded sentinel
TRACKING_ID=$(jq -r '.version // "unknown"' "$JSON")
# Next run: TRACKING_ID="unknown" == STATE_FILE "unknown" -> always-match

# Fix: return empty string on null; do not write to STATE_FILE
TRACKING_ID=$(jq -r '.version // ""' "$JSON")
if [ -n "$TRACKING_ID" ]; then
  echo "$TRACKING_ID" > "$STATE_FILE"
fi
```

Scope: any idempotency protection logic that compares previous ID vs current ID.

## jq `--arg` with Empty String: Avoid `if $x=="" then null` (PR #48)

`jq --arg rid "$RULE_ID"` passes an empty string; if the jq expression writes
`if $rid=="" then null else $rid end`, the resulting `rule_id: null` causes a Pydantic `str`
field ValidationError that **silently drops the entire record** — no error, no count, it just
disappears.

```bash
# Wrong: null causes Pydantic str field to silently drop record
--arg rid "$RULE_ID"
# jq: rule_id: (if $rid=="" then null else $rid end)

# Fix: pass $rid directly; empty string is valid for Pydantic str, null is not
--arg rid "$RULE_ID"
# jq: rule_id: $rid
```

Difference from "tracking ID sentinel": sentinel trap is a shell-layer hardcoded fallback;
this is jq converting empty string to null. Both cause silent failure but at different layers.

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
"Bash(rg *)",
"Bash(git -C *)",
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

## Single-Quote Semantics (hook implementation note)

Backslash inside bash single quotes is **literal**, not an escape character.
Only inside double quotes does backslash escape the next character.

```bash
printf '%s\' "$(id)"   # single quotes do not process \; closing ' is after \
                        # correct parse: '%s\' is the full token; "$(id)" is Rule 2 violation
```

This is the key behavior of the hook's `_quote_state_at()` state machine:

```python
if c == "\\" and in_double:   # only skip next char inside double quotes
    i += 2
    continue
# inside single quotes: backslash is a normal character; do not skip
```

Using `in_double or in_single` incorrectly would let the Rule 2 match for
`printf '%s\' "$(id)"` be skipped, silently allowing it through.

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

## `\$` in Skill / Command Bodies Is Markdown-Layer Substitution, Not Bash Quoting

A `\$` in a skill or slash command **body** (the Markdown prose, outside bash code) is
consumed by Claude Code's string-substitution layer before any shell runs — it emits a
literal `$` in front of a digit, `ARGUMENTS`, or a declared argument name (e.g. `\$1.00`
in prose). It is unrelated to bash quoting, and none of the quoting rules in this file
apply to it. The full rules, official quote, and probed boundary table live in
[`11-skill-authoring.md`](11-skill-authoring.md) ("Skill Body — Literal `$` Escape") —
do not duplicate them here.

## Gemini / agy CLI Gotchas

**`@<path>` triggers agentic mode** — never use `@file` with agy. Inline the prompt as `-p`
value instead.

**`--add-dir` must be an absolute path** — relative `.` silently yields zero file context
(agy exits 0 with a fabricated answer, no error).

**`-p`/`--print` takes the prompt as its value, not boolean** — `agy --print --add-dir .`
swallows `--add-dir` as the prompt text. No stdin channel exists.

```bash
# Wrong: @file triggers agentic mode; --add-dir . yields zero context
agy -p "@$REVIEW_DIR/input.md" --add-dir . --sandbox

# Fix: inline prompt + absolute --add-dir. Both halves required.
agy -p "$PROMPT_AND_DIFF" --add-dir "$WT_ROOT" --sandbox
```

Size guard: assert content < 256000 bytes before the call. Prepend guard text so content
never starts with `@`. Version-stamped probes expire — re-test after `agy` upgrades.
`trustedWorkspaces` is NOT the cause of workspace errors — the path form is.
`scripts/lint_skill_bash.py` flags `--add-dir` with relative paths in SKILL.md fences.

## Quoting Rule 6: Python Comment with `"` Truncates Outer Shell Double-Quote (PR #23)

The shell string for `python3 -c "..."` is wrapped in outer double quotes. **Even a Python
comment (`#`) containing `"` is seen by the bash parser as closing the outer double-quote**,
truncating the Python code; regex and other logic fail silently (no error message).

```bash
# Wrong: comment contains " which truncates outer shell string
python3 -c "
import re, sys
# Known Limitation: user.name="foo | bar" -- quoted pipe breaks match
ptn = r'\bcommit\b'
re.search(ptn, sys.stdin.read())
"
# bash truncates at the " in "foo | bar"; python3 receives broken code

# Fix A: replace " in comments with full-width quotes or remove them
# Known Limitation: user.name=foo|bar -- quoted pipe breaks match

# Fix B: move inline python to a standalone .py file (root fix)
python3 scripts/check_pattern.py
```

Rule: **inside a bash `"..."` string, avoid `"` in comments in any language**; if quotes are
needed, use single quotes `'` (literal inside bash double-quote strings, does not close outer string).

## Quoting Rule 7: Bare `$VAR` Immediately Followed by a Non-ASCII Char Can Fold Into the Name (PR #198)

A bare `$VAR` (no braces) directly followed by a non-ASCII character — a full-width paren `（`,
CJK ideograph, full-width colon `：`, Cyrillic, Greek, accented Latin, etc. — can be folded into
the variable name by bash. bash classifies name characters via the current locale's `isalnum()`,
and **in a UTF-8 / multibyte locale** most high bytes count as "alphanumeric" and are read as part
of the name. The result is a **different, unset** variable, so under `set -u` the line aborts with
`<VAR><bytes>: unbound variable` **even though `$VAR` itself is set**.

Three scope caveats (the "any non-ASCII" phrasing above is the practical guidance, not a literal
universal). All folding behavior below was **verified on macOS system bash 3.2**; the exact set of
folding bytes is locale-, libc-, and bash-version-dependent, so treat other UTF-8 environments
(e.g. Linux/glibc, other bash versions) as "likely affected, exact boundary unverified" rather than
assuming identical behavior:

- **Locale-dependent**: the fold only fires in a UTF-8 / multibyte locale. Under `LC_ALL=C` the
  high byte is not alnum, the name terminates, and the same line prints fine — so a reader
  reproducing under `LC_ALL=C` will not see the crash and may wrongly mistrust the rule.
- **Not literally every non-ASCII char**: the fold follows `isalnum()`, which is script- and
  libc-dependent. On macOS, CJK, full-width punctuation, Cyrillic, Greek, and accented Latin all
  fold; **Hebrew (e.g. `א`) does not**. The boundary is not easily predictable, so the practical
  rule below (always brace) is the safe superset — do not rely on a particular script being "safe".
- **Environment-dependent**: because it hinges on the runtime locale + libc, the same script can
  fold on one machine and not another. Bracing removes the dependency entirely.

This bites hardest in `[FAIL]` / `[INFO]` diagnostic `echo`s whose Chinese message text opens
with a full-width paren right after the variable — the failure branch crashes with a confusing
`unbound variable` instead of printing its intended message, defeating the fail-loud contract.

```bash
set -u
REVIEW_DIR=/tmp/x
# Wrong: 全形括號（ folds into the name -> bash looks up $REVIEW_DIR（... = unset
echo "[FAIL] 無法建立目錄：$REVIEW_DIR（請確認權限）" >&2
#   -> line N: REVIEW_DIR<0xef...>: unbound variable   (REVIEW_DIR is set, but this name isn't)

# Fix: brace the variable so its name terminates explicitly before the CJK char
echo "[FAIL] 無法建立目錄：${REVIEW_DIR}（請確認權限）" >&2
```

Rule: **whenever a `$VAR` is immediately followed by a CJK / full-width / any non-ASCII character
(no intervening space or ASCII punctuation), brace it `${VAR}`.** A space or ASCII char after the
name (`$VAR 失敗`, `$VAR/info`, `$VAR...HEAD`) is safe — the name terminates on its own.

Detection (scan a committed `.sh` before trusting its error paths). This catches the **non-ASCII
adjacency** class only — a bare `$VAR` abutting an *ASCII* identifier char (`$VARfoo`) is a
different "wrong variable" bug, not covered here. **Use `rg`, not `grep -P`**: BSD `grep` on macOS
(the default) rejects `-P` with `invalid option -- P` and exits non-zero with no output — itself a
silent-failure trap (see the `realpath` macOS-portability note above). `rg`'s Rust regex needs no
`-P` flag. The pattern is purely lexical, so it also matches `$VAR` in **non-expanding literal
contexts** (comments, single-quoted strings, escaped `\$`, here-doc bodies) — those are false
positives; inspect each match rather than trusting the count:

```bash
rg -n '\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]' script.sh   # bare $VAR + non-ASCII; verify each hit is an expanding context
```

Note: this is orthogonal to AP2 (which only bans emoji / em-dash / zero-width in the *string
content*). The AP2 section's "CJK text ... are all fine" is about AP2 detection, **not** about
variable-adjacency — CJK text is fine as literal content but not immediately abutting a bare `$VAR`.
Empirically confirmed on PR #198 (`BASE_REMOTE\xef: unbound variable`), and an independent mob
reviewer (agy) found a second latent instance in the same file's mkdir-failure branch.

**Family — `set -u` "unbound variable" traps.** This is one of a recurring cluster where a
line dies with `unbound variable` even though the author believed the variable was set. The
same symptom shows up from:

- **non-ASCII adjacency** (this rule): `$VAR（` resolves to a *different*, unset name.
- **empty-array expansion**: under `set -u`, `"${ARR[@]}"` on an empty array crashes on macOS
  system bash 3.2 (homebrew bash 5.x is fine); write `${ARR[@]+"${ARR[@]}"}` or split into
  explicit non-array branches.
- **unchecked positional before `shift`**: the `--flag) VAL="$2"; shift` idiom dereferences `$2`
  *before* shifting, so it crashes on `$2` when the caller omits the value; guard
  `[ "$#" -lt 2 ] && { echo '[FAIL] ...' >&2; exit 2; }` before dereferencing.

Common cure: never expand a name/positional/array under `set -u` without first making it
boundary-explicit (`${VAR}`), bounded (`$#` check), or defaulted (`${x:-}` / `${ARR[@]+...}`).
When a `set -u` script aborts with `<name>: unbound variable` and the name *looks* assigned,
suspect one of these three before assuming a real logic bug.
