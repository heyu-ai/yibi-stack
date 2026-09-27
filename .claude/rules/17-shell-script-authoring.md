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
