---
paths:
  - "**/*.sh"
  - "scripts/**"
  - ".claude/hooks/**"
  - "Makefile"
  - ".pre-commit-config.yaml"
  - ".github/workflows/**"
---

# Shell Script Authoring

Split out of [rule 13](13-bash-anti-patterns.md) to keep the always-loaded instruction set under
Claude Code's 150k-char limit. Rule 13 keeps what applies to **every Bash tool call** (AP1-AP3,
Quoting Rules 1-5, the self-check); this file holds what matters when **authoring or reviewing a
shell script, hook, or CI gate**, so it loads only when a matching path is touched. The sections
below were moved verbatim; section titles are unchanged, so older citations of the form
"rule 13, section X" resolve here.

## Gate Verdicts: Trust the Exit Code

### `|| exit 0` / `|| true` Turns a Real Result Into a Silent Skip

`|| true` masks the exit code and continues; `|| exit 0` masks it and exits immediately.
Either way the caller cannot distinguish "failed to run" from "ran and found something".

```bash
# Wrong: exit code masked
agy review ... || true

# Also wrong: output captured but exit code still masked — can't tell failure from findings
OUT=$(agy review ... || true); [ -n "$OUT" ] && handle_findings

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
**grep's** exit code, not flutter's (the pipe-masks-exit-code trap in [rule 13](13-bash-anti-patterns.md)), so it
can report success on a failing run whose output happened to contain the banner earlier. If you
genuinely must inspect the banner, do it without a pipe — run `flutter test`, keep its exit code,
then grep the saved output separately (and match `All (other )?tests passed` to survive the
skipped-test variant).

Success banners are **presentation**, not API — they change with tool versions and with run
conditions. Exit codes are the contract. Same family as the two sections above: the check ran and
reported confidently about the wrong thing.

## Self-Location and Portability

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

## Consuming Command Output

### Process substitution multi-line output consumption (2026-05)

`read -r A B < <(cmd)` reads one line then splits by IFS; if `cmd` outputs multiple lines via
multiple `print()` calls, subsequent variables are always empty — silently.

```bash
# Wrong: read consumes only the first line; DUR is always empty
read -r FILE DUR < <(python3 -c "print(fp); print(dur)")

# Fix: consecutive reads, one per line
{ read -r FILE; read -r DUR; } < <(python3 -c "print(fp); print(dur)")
```

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

# Fix: trap EXIT + set -e — restore runs on any normal exit, set -e propagates failure
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
**`;` is not the fix** — under `set -e` the restore never runs; without it the failure status is masked.
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

Using `in_double or in_single` incorrectly would let the Rule 2 (rule 13 Quoting Rule 2) match for
`printf '%s\' "$(id)"` be skipped, silently allowing it through.

## `\$` in Skill / Command Bodies Is Markdown-Layer Substitution, Not Bash Quoting

A `\$` in a skill or slash command **body** (the Markdown prose, outside bash code) is
consumed by Claude Code's string-substitution layer before any shell runs — it emits a
literal `$` in front of a digit, `ARGUMENTS`, or a declared argument name (e.g. `\$1.00`
in prose). It is unrelated to bash quoting, and none of the quoting rules in rule 13 or this file
apply to it. The full rules, official quote, and probed boundary table live in
[`11-skill-authoring.md`](11-skill-authoring.md) ("Skill Body — Literal `$` Escape") —
do not duplicate them here.

## Gemini / agy CLI Gotchas

**Gemini CLI**: `@<path>` restricted to worktree-internal paths — copy input into the worktree
first (`cp input.md "$WT_ROOT/gemini-input.md"`; `gemini -m model -p "@gemini-input.md"`).

**agy**: `@<path>` triggers agentic mode — never use `@file` with agy. Inline the prompt as `-p`
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
content*). Rule 13's AP2 section's "CJK text ... are all fine" is about AP2 detection, **not** about
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

## Global-State Install Guard

Skills locate this repo through the `~/.agents/bin/resolve-skill-repo` symlink that `make install`
creates (see rule 11, "Never locate this repo via `~/.agents/config.json`"). The sections below
cover the install targets that write that kind of machine-level state.

### `make install` must run from the main repo, never from a worktree

Self-locating is what makes a worktree install dangerous, and the danger is a direct
consequence of the property that makes the resolver correct: it faithfully resolves to
**the checkout that installed it**. Install from `.claude/worktrees/<name>/` and every
global symlink points into that worktree; once the branch merges and `/clean-wt --apply`
removes it, the symlinks dangle and every skill dies.

**Keep "the guard is the first recipe line" as a literal, testable invariant** — do not relax it
to "the guard precedes the first *mutation*". A reviewer proposed moving each target's
`[ -z "$(SKILL)" ]` usage check above the guard, so that forgetting `SKILL=` inside a worktree
reports the usage error rather than the (longer) worktree error. Declined, deliberately: the
usage check mutates nothing today, but "guard first" is checkable by a test that anyone can read,
while "guard before the first mutation" requires every future editor to correctly classify their
own line — and the cost of one wrong classification is the silent global-state corruption this
whole gate exists to prevent. The UX gain is also thin: a caller inside a worktree must fix that
first regardless of the missing argument.

**Guard every target that writes global state individually — a prerequisite chain is not a
gate.** `install-all` lists `install` before `install-scheduler`, but `make -j` runs
prerequisites **in parallel**, so the scheduler can finish writing a worktree path into its
LaunchAgent plist before `install`'s guard aborts the build. The same applies to
`install-handover-hooks`, which embeds the repo path into `~/.claude/settings.json` hook
commands. Neither goes through a symlink — both self-locate in Python from `__file__` — so the
symlink-shaped reasoning does not cover them; what they share is "writes the repo path into
machine-level state", and that is the property to guard on.

Nothing in the resolver can detect this — by construction:

- The identity gate passes: a worktree is a **complete checkout**, so `tasks/mycelium` is there.
- The Makefile's post-install gate (`resolved == $(CURDIR)`) passes: inside a worktree those
  two **are** equal. That gate catches "points at another checkout"; it cannot catch "points at
  a checkout that is about to be deleted".

This is also a **regression risk introduced by retiring config.json**, and it must not be
re-litigated as "the old way was safer": the old lookup was rewritten by `register_skill_repo.py`
on *every* `make install`, so a moved or deleted checkout self-corrected on the next run. A
symlink does not self-correct. The resolver traded a silent-wrong-answer failure mode for one
that needs an explicit up-front gate — which is `scripts/assert_not_worktree.sh`, wired as the
**first recipe line** of every target that writes machine-level state (first, because those
targets write global symlinks before they reach the resolver step — failing late leaves
`~/.claude/skills/` already polluted). The authoritative list is `GUARDED_TARGETS` in
`scripts/tests/test_assert_not_worktree.py`, which the tests enumerate — do not re-list the
targets here; an enumeration copied into prose is one more claim that decays silently (this
paragraph said "four targets" for three PRs after the count became seven).

Detection is `--git-dir != --git-common-dir` (in a worktree the former is
`<main>/.git/worktrees/<name>`, the latter `<main>/.git`; in the main repo they are equal).
Do **not** substring-match `.claude/worktrees` — a worktree may be created at any path.

**A fail-open must name the single condition it forgives, never "the call failed"** — and then
check that the condition it names is actually single. This one bit twice, one level apart:

1. The guard's non-git pass-through is deliberate (an unpacked zip cannot be a worktree), but the
   first implementation expressed it as "if `git rev-parse` fails, exit 0", silently forgiving a
   much larger set: git older than 2.31 (`--path-format` unknown), dubious ownership under
   `sudo make install`, permission errors, git missing from `PATH`, an unreadable directory. Each
   made the gate cease to exist with no warning. All three mob-review voices flagged it.
2. Narrowing it to "git's stderr says `not a git repository`" looked exact — but **git says the
   same sentence for two different conditions**. A linked worktree whose admin dir is gone
   (pruned, or the main repo moved/re-cloned) reports `fatal: not a git repository: (null)`, so
   the narrowed match still waved through a directory that is unmistakably a worktree *and*
   already doomed — precisely what the gate exists to catch. Measured, not theorised:
   `rm -rf <main>/.git/worktrees/<name>` and `mv <main> <elsewhere>` both reproduce it.

   The disambiguator is the filesystem, not the message: the legitimate case (unpacked zip) has
   **no `.git` at all**. A `.git` that exists while git denies the repo means broken, not absent.
3. `[ ! -e "$DIR/.git" ]` then looked exact, and was not either: **`-e` follows symlinks**, so a
   *dangling* `.git` symlink (link present, target gone) satisfies `! -e` and fail-opened again.
   Reproduced on a real worktree whose `.git` was replaced by a dangling link. The predicate has
   to be `[ ! -e "$DIR/.git" ] && [ ! -L "$DIR/.git" ]` — `-L` is what asks "does the entry
   itself exist".

4. `[ ! -e ] && [ ! -L ]` on `$DIR` was still not it: `$DIR` can be a **subdirectory** of the
   broken worktree, where no `.git` lives — it sits at the worktree root. Blocked at the root,
   fail-open one level down. The predicate has to walk ancestors.

Four rounds, one shape: **each time the fail-open was narrowed, the new condition still covered
more than its name suggested.** When you write a fail-open, do not stop at naming the condition —
enumerate the states that satisfy the predicate you actually typed, and probe each. Reading it as
prose is how all four survived review.

**Then the fix for the fail-open grew its own fail-opens — twice, in shapes already fixed
elsewhere in the same file.** Round 5 added a "is this path a registered worktree?" check on the
pass path; round 6 found it (a) skipped itself entirely when `git worktree list` failed, because
it was written as `if REGISTERED=$(...); then …; fi` with `exit 0` below, and (b) compared `$DIR`
by **equality** with each worktree root, so a **subdirectory** walked straight past it. Both are
verbatim repeats: (a) is the round-1 "command failed → pass" shape, (b) is the round-4 "the
marker is at the root, not at `$DIR`" shape that the ancestor walk twelve lines away exists to
solve. Two reviewers named the repeat explicitly.

The generalizable rule: **after fixing a class of bug, grep your own new code for that class
before shipping it.** Recency does not inoculate — the round-5 code was written *by the author
of the round-4 fix, hours later*. Fixing a bug creates new code, and new code is where the same
bug goes next. Concretely, for a gate: every new `if cmd; then check; fi` needs "what happens
when `cmd` fails?", and every new path comparison needs "what if the input is *under* this path?"

**A third occurrence, one level removed: two functions that share an invariant, fixed one at a
time.** The bug above is the *same* defect shape reappearing in new code. The variant is a
*different* defect shape appearing in a function you did not touch, because the fix broke an
invariant that function silently depended on. Three consecutive mob-review rounds (R1+R2,
re-review R1, re-review R2) each opened with "the most important finding is one the previous
round's own fix introduced" — every time in the same seam: `park_lesson()` and
`finalize_reassessed_lesson()` shared an implicit contract (the `confidence` watermark that marks
"still Tier 3", the meaning of a `recurrence-<n>` tag, `trusted` as a derived function of
`source`), and each round's fix satisfied its own function's half of the contract while silently
breaking the other function's assumption about it. Reading the diff of either function in
isolation looked correct every time. The mitigation is not "read more carefully" — it is
structural: **when editing one side of a two-function seam a second time, enumerate every
invariant the *other* function assumes about the data this function writes, and check each one
explicitly**, rather than re-verifying only the line you just changed. (Source: PR #347 —
`park_lesson()` / `finalize_reassessed_lesson()`, `tasks/mycelium/db.py`.)

**The documented residual is a claim too, and it decays with each fix.** State the limit
explicitly — but re-probe it every time the predicate changes, because a stale residual note is
worse than none: it tells the next reader (and reviewer) that a hole is known and accepted when
in fact it has moved. This rule was itself learned twice on the same PR, which is the point:

- Round 2's note said "only outright `.git` deletion is undetectable". By round 4 that was false
  twice over — the dangling-symlink and subdirectory cases both slipped past while the note
  claimed otherwise, and a reviewer caught the contradiction between code and note before
  catching the code.
- The note was then rewritten to say an in-tree worktree with a deleted `.git` "passes safely,
  and that is fine". Round 5 added a registration check that **blocks exactly that case** — and
  the note still claimed the old behavior until round 7, when a reviewer flagged the code/doc
  contradiction. The lesson had already been written into this very file by then. Writing the
  rule does not execute it.

The honest residual, re-probed: a worktree whose `.git` is deleted outright **and** which lives
outside the main repo's tree — there it is byte-identical to an unpacked zip. In-tree cases are
caught by the `git worktree list` registration check.

Operationally: treat a residual note like a test. When you change the predicate, the note is part
of the diff — if you did not re-run the scenario it describes, you do not know whether it is still
true.

**The subshell-`exit` trap is now enforced mechanically, not by memory.** After the fail-loud
principle recurred across three dated lessons (2026-07-07, 2026-07-14, and PR #234's four
in-PR repeats), continuing to write it down was an admission that writing it down does not work.
`scripts/lint_shell_subshell_exit.py` (pre-commit, `types: [shell]`) parses shell scripts and
warns on the one shape that actually fail-opens:

> `exit` inside a function **and** that function is called as the first token of a `$(…)` **and**
> the call site is somewhere `set -e` will not catch (an `if`/`elif`/`while`/`until` condition,
> `!` prefix, or `||`/`&&` where `$(…)` is not the final command), **or** a masking builtin
> (`local`/`declare`/`export`/`readonly`/`typeset`) swallows the exit status (SC2155), **or**
> the script has no `set -e` / `set -o errexit` at all.

Both extra conjuncts are load-bearing, and each was learned from a false positive the first draft
produced against real repo code: `bump.sh`'s `new_version=$(bump_semver …)` is a **bare
assignment under `set -e`**, so the subshell's `exit 1` does abort the script — no fail-open;
a call like `LOG=$(python3 logger.py block …)` only *mentions* a same-named token inside an
unrelated `$(…)` while `block()` itself is called **directly**, so requiring the name to be the
substitution's first token clears it (see test EG-004's synthetic fixture — do not cite a specific
tracked file's current contents, which drift). A lint that fires on correct code teaches people to
disable it, so the negative controls are the important tests, not the positive one.

**Ships advisory, not blocking (PR #241 mob review; correctness fixed in PR #407 / issue #282).**
A cross-family mob review (Claude / Codex / agy) on PR #241 empirically found this lint was
incomplete in both directions. The five correctness issues were fixed in PR #407:
false-positives on final-position `&&`/`||`, `set -o errexit`, and if-body calls;
false-negatives on quoted `X="$(fn)"` and `local`/`export X=$(fn)` (SC2155).
The lint defaults to warn-only (`--fail` opts into blocking for CI) until advisory-mode runtime
validates stability. The lesson for future mechanical guards: a lint that enforces an anti-pattern
must itself be held to the anti-pattern's full truth table before it is allowed to block.

**Do not run mutation tests on a shared worktree file while a review agent is reading it.**
Mutation testing edits the real file in place; a reviewer dispatched against that path will read
whatever state the file happens to be in. On this PR a reviewer read the script mid-mutation, got
one **false clean result**, and had to flag the race instead of reviewing. The global CLAUDE.md
already records this incident in the opposite direction (a verification subagent editing the file
the lead was reading) — it is symmetric, and the lead is not exempt. Sequence them: finish the
review round, collect every report, *then* mutate. If you must do both, mutate a copy outside the
worktree. Corollary for reviewers: pin any report on a mutable file to a SHA.

**An error message's hint must share the predicate of the branch it explains.** The guard's
"this repo is broken — pruned admin dir? main repo moved?" hint was gated only on "`.git`
exists", not on "git actually said *not a git repository*". So any other git failure inside a
directory that has a `.git` printed a confident, fabricated cause — reproduced against a
perfectly **healthy main repo** with a shimmed dubious-ownership error. Fail-closed was right;
naming a cause it had not established was not. This is the same rule as the `dirname` fallback
above, one level in: that fallback pointed at a possibly-wrong *directory*, this hint at a
possibly-wrong *reason*.

Because git localises its messages, any such match must pin `LC_ALL=C`, or it silently misses on
a non-English machine and starts blocking legitimate installs instead.

**Clear `CDPATH` before using `cd` to normalize a path.** POSIX has `cd` search `CDPATH` whenever
the target's first component is neither `.` nor `..` — which is exactly what git returns
(`.git`). On a hit, `cd` also **prints the destination to stdout**, so a `$(cd … && pwd -P)`
capture silently gains a second line. Measured on this repo's guard. It was not yet exploitable
there, but only because of which paths git happens to emit relative vs absolute — not a property
worth resting a safety gate on. `export CDPATH=` removes the dependency.

**Under `set -e` + `pipefail`, a bare `X=$(cmd | awk …)` kills the script and makes any fallback
below it dead code.** The guard resolved the main repo that way with a `dirname` fallback
underneath; when `git worktree list` failed, the script died at that line — exit 128, **no output
at all** — after it had already decided the directory was a worktree, so the `[FAIL]` never
printed and the fallback was unreachable. Wrap it in `if !`. Relatedly, do not let `awk` `exit`
early in such a pipeline: the producer gets SIGPIPE and `pipefail` turns a successful command
into a failure. Use a flag (`!seen`) and consume the whole stream.

**Normalizing git paths: use `cd`+`pwd -P`, not `--path-format=absolute`.** Two traps, both
measured on this repo during PR #234's review:

- `--path-format=absolute` needs git >= 2.31 (2021). Using it puts the gate's correctness on a
  version floor this repo does not otherwise require (rule 13 already documents caring about
  macOS < Ventura toolchains). `(cd "$dir" && cd "$raw" && pwd -P)` is portable and
  format-independent.
- Comparing the **raw** `rev-parse` outputs (the obvious way to avoid `--path-format`) is wrong:
  the two flags do not answer in the same spelling. From a main-repo **subdirectory**,
  `--git-dir` returns an absolute path while `--git-common-dir` returns `../.git`; from a
  **symlinked** path, `--git-dir` returns the *physical* path while a relative `--git-common-dir`
  resolves *logically*. Either asymmetry makes the two compare unequal and **falsely blocks a
  legitimate main-repo install**. `pwd -P` (physical, not logical) collapses both into one
  namespace. macOS's own `/var` → `/private/var` symlink is enough to trigger this.

**Report the main repo from `git worktree list --porcelain`, not `dirname` of the common dir.**
Its first `worktree` entry is authoritative. The common dir's parent is not necessarily the main
work tree (`git clone --separate-git-dir`, submodules), so `dirname` can print a `cd` target that
does not exist — an error message that misdirects is worse than a terse one.

**And when the authoritative lookup fails, print no recommendation at all** — do not fall back to
the guess you just rejected. The guard originally kept `dirname` as a fallback under exactly the
comment explaining why `dirname` is wrong; a reviewer caught it by holding the code to the
sentence above. A fallback that re-introduces the defect its own comment documents is worse than
having no fallback: say "could not determine the main repo" and let the operator look.

**Any new `git` call added to the resolver family must clear inherited git env vars.** This
is a shared trap, not a per-script detail: `GIT_DIR` / `GIT_WORK_TREE` / `GIT_COMMON_DIR`
outrank `git -C`, so git answers about *that* repo and ignores the `-C` directory entirely.
Both `resolve-skill-repo` (PR #233) and `assert_not_worktree.sh` therefore route every call
through `env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR -u GIT_INDEX_FILE git`. Measured
on the guard before it was hardened: with `GIT_DIR=<main>/.git` set, it flipped from `exit 1`
to `exit 0` inside a worktree — the gate silently ceased to exist. This path is routine, not
exotic: git sets `GIT_DIR` while running hooks, and this repo leans heavily on pre-commit.

The guard **fails loud rather than auto-deriving** the main repo via `--git-common-dir`, even
though that would "just work" for the user. Auto-deriving would install the *main repo's*
checkout while the user is looking at their worktree's code — possibly a different branch or
an older commit. That is a silent wrong answer, the exact failure class this whole resolver
design exists to eliminate. A non-git directory (an unpacked zip) is passed through, not
blocked: it cannot be a worktree, so blocking it would be a pure regression.

`scripts/resolve-skill-repo` is the single implementation — do not inline a copy of its
logic into a SKILL.md. If you need this in a script that already lives in the repo, that
script can self-locate directly instead of shelling out (see
`plugins/growth/skills/pr-control-log/scripts/bootstrap.sh` for the in-script form).

**Gotcha — `pwd -P` does not resolve a *file* symlink.** The in-script form
`SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)` only works when the symlink is
on a **directory** in the path (as with `~/.claude/skills/<name>` → `<repo>/skills/<name>`).
`resolve-skill-repo` is exposed as a **file** symlink under `~/.agents/bin/`, where that form
silently returns `~/.agents/bin` instead of the real directory — no error, just a wrong
answer. It therefore walks the symlink chain with `readlink` in a loop (macOS has no
`readlink -f`). Copy the right form for your symlink shape; verify by executing through the
symlink, not just directly.

**Note (error handling form)**: `cmd || { echo '[FAIL]' >&2; exit 1; }` contains a `'` quote
inside `{}`, triggering the "brace with quote character" confirmation dialog.
Always use `if ! cmd; then echo '[FAIL]' >&2; exit 1; fi` instead (the canonical form above
already uses this).

### A gate belongs at every entrance, and the tool that documents an entrance owns it

PR #234 wired the guard into 7 make targets and recorded the residual honestly: "the guard lives
in the Makefile, so calling the Python module directly bypasses it." Issue #237 closed it. Two
things are worth keeping from how that went:

**The "unrealistic" bypass was in our own help text.** The residual was defensible only if nobody
calls the module directly. But `tasks/scheduler/cli.py`'s `setup` command *prints*
`uv run python -m tasks.scheduler install` as the user's next step. The unguarded entrance was not
hypothetical — it was the documented one. Before accepting "nobody invokes it that way", grep for
the invocation in your own `--help`, `echo`s, SKILL.md, and README; a tool that teaches a path owns
that path.

**Guard the sink, and find all of them before choosing the altitude.** The issue named two
entry points; the repo had five. `insight install-hook` and `recap install-hook` build the same
`Path(__file__).resolve().parents[2]` command string into `~/.claude/settings.json` and have **no
make target at all** — the most exposed sinks were the ones nobody listed, precisely because the
Makefile inventory was the search index. The property to enumerate on is not "which CLI did the
issue mention" but **"what writes a repo path into state that outlives the checkout"**. Grep the
class (`parents[` / `PROJECT_ROOT` reaching a `~/…` write), not the ticket.

Three altitudes, and why the entry point wins here:

| Altitude | Verdict |
|----------|---------|
| Path source (`_paths.py`) | **No** — `PROJECT_ROOT` is imported by `status` / `tick` / tests; an import-time gate breaks read-only work inside a worktree, which is legitimate |
| Library install function | **No** — its destination is injectable (tests pass `settings_path=tmp`); gating it means either breaking every test or inventing a test-only bypass |
| Process entry point (CLI command / `main()`) | **Yes** — where install intent is expressed *and* where the real machine-level destination is chosen |

Residual, stated so it can be re-probed: importing an install function directly in Python still
bypasses this. That is an in-repo API consumer, not the documented surface — but if a future caller
appears, the guard moves down with it.

### A shared helper's message is part of its interface — a hardcoded caller idiom becomes a lie

`assert_not_worktree.sh` took `<make-target-name>` and printed `不可執行 make ${TARGET}` plus
`cd <main> && make ${TARGET}`. Correct while make was the only caller. The moment Python called it,
every message became a fabricated command: "不可執行 **make** uv run python -m tasks.scheduler
install", and a `cd … && make uv run python …` that fails on copy-paste. The detection was
caller-agnostic; the **message** silently was not.

The fix is the seam, not the string: the script now takes a `<recovery-command>` — the complete
command, program name included — and never prefixes anything. Callers own their idiom
(`"make install"`, `"uv run python -m tasks.mycelium insight install-hook"`). Its rationale line
was equally caller-specific ("symlink 會指向不存在的路徑，所有 skill 失效") and now names the
whole class it guards: symlinks, LaunchAgent plist, and settings.json hooks.

This is the same principle the script already enforced three times against *itself* — a misleading
message is worse than a terse one — applied one level out: **when a second caller arrives, re-read
every string the helper emits and ask which caller it was written for.** Reusing battle-tested
detection does not mean the prose around it transfers.

Pin it with a test, not a convention: `ANW-DT-016` asserts every Makefile call site passes a
command that **names its own target** (`"make <target>…"`), so dropping the prefix — or copying a
guard line to a new target and forgetting to change it — fails loudly instead of shipping a hint
that is uncopyable or points at the wrong target.
