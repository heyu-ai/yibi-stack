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

### AP3 Sub-class C: Path Resolution Hiding (class F1 hook attempts to catch)

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

### AP3 Summary

| Sub-class | Hook | Cases | Fix |
|-----------|------|-------|-----|
| A: CWD pollution | None (silent) | 4/17/18 | `--directory` flag or subshell |
| B: cd-before-git | Class C (partial) | 7/9/12 | `git -C <path>` |
| C: path resolution hiding | Class F1 (partial) | 10/11/15 | Absolute path / Read/Grep tool |

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

### `realpath` — Not Available on macOS < Ventura

`realpath` is absent on macOS Monterey and earlier. Scripts using it fail with `command not found`
(silently in some contexts), making the resolved path empty or causing exit 1.

```bash
# Wrong: realpath unavailable on macOS < Ventura
SCRIPT_DIR=$(realpath "$(dirname "$0")")

# Fix: portable form -- resolve symlinks via cd+pwd
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
```

Use `cd "$(dirname "$0")" && pwd` in all shell scripts that need the script's own directory.

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

External skill scripts (e.g., `bump-version/scripts/bump.sh`) have a **step execution contract**:
downstream scripts often read state written by upstream scripts; step ordering cannot be freely changed.
When "run tests before file mutation" conflicts with the contract, use `trap ERR` to auto-revert:

```bash
rollback() {
    echo "[WARN] Release failed -- reverting version files" >&2
    git checkout -- pyproject.toml CHANGELOG.md 2>/dev/null || true
    git checkout -- 'plugins/*/package.json' 2>/dev/null || true
}
trap rollback ERR

# ... file mutation steps (bump, sync, changelog) ...

# gates.sh depends on bump.sh's env file; must run after bump
"$GATES_SH"

trap - ERR   # clear trap before commit; failures after commit need different recovery
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): v${TAG_VERSION}"
```

Notes:

- `trap - ERR` must be cleared **before** the commit; post-commit failures need `git reset HEAD~1`.
- `git checkout -- 'plugins/*/package.json'` glob must use single quotes (shell glob expansion timing).
- If a step has its own `trap`, isolate with a subshell to avoid overwriting the outer `trap ERR`.

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

## Gemini CLI Workspace Sandbox (PR #24)

Gemini CLI `@<path>` references are restricted to paths inside the git worktree directory.

```bash
# Wrong: /tmp is outside Gemini workspace
gemini -m model -p "@/tmp/pr-review/wt-name/input.md"

# Fix: copy input into worktree; use relative path (auto-cleaned when worktree deleted)
cp /tmp/pr-review/wt-name/input.md "$WT_ROOT/gemini-input.md"
gemini -m model -p "@gemini-input.md"
rm -f "$WT_ROOT/gemini-input.md"
```

Do not use `~/.gemini/tmp/` — requires manual cleanup and may persist across sessions.

**Antigravity CLI (agy)** — `@<path>` triggers agentic mode (model outputs `call:read_file{...}`
/ brain-artifact narration / timeout instead of a review). In a **nested worktree** even a
worktree-relative `@.pr-review/...` fails the same way — agy cannot resolve the `@file` inside
the sandbox and silently goes agentic. Relative `@path` is **not** a reliable fix; **feed the
prompt via stdin — never `@file`**:

```bash
# Wrong: any @file (absolute OR worktree-relative) -> agentic mode in a nested worktree
agy -p "@$REVIEW_DIR/input.md" --add-dir . --sandbox
agy -p "@.pr-review/input.md" --add-dir . --sandbox

# Fix: pipe / redirect the prompt to stdin; agy reads no file, so there is no agentic trigger
cd "$WT_ROOT"
{ printf '%s\n' "$PROMPT_AND_DIFF"; } | agy --print --add-dir . --sandbox
agy --print --add-dir . --sandbox < "$WT_ROOT/.pr-review/input.md"   # equivalent
```

stdin also sidesteps two adjacent traps: ARG_MAX (a huge diff as a CLI arg) and a leading-`@` in
the content being re-parsed as a file path. `--print` is boolean (reads stdin when given no
positional prompt) — verified: `printf 'reply ALPHA' | agy --print --add-dir . --sandbox` returns
`ALPHA`, confirming `--add-dir` / `--sandbox` are still parsed as flags. (Source: PR #156
pr-cycle-deep inline migration, PR #157 standalone stdin migration.)

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
