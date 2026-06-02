---
name: bash-anti-patterns
type: know
scope: global
description: >-
  識別與避免 Claude Code agent 下 bash 指令的三層防線：(1) Anti-Pattern 1
  過度複雜單行（多行 heredoc、巢狀引號、內嵌 Python -c / Node -e、複雜 if/elif、
  for-loop-file-list），(2) Anti-Pattern 2 bash 字串內特殊 Unicode（em dash、
  en dash、emoji），(3) Anti-Pattern 3 stateful cd（CWD 污染 / cd-before-git /
  cd + 2>/dev/null 路徑隱藏）。另含 Rule 14 shell 引號衛生（simple_expansion /
  同型引號衝突 / grep BRE alternation / 反向巢狀 subshell / expansion false
  positive）與 Rule 15 不可逆操作邊界（alembic migrate / terraform apply /
  git push --force / rm -rf / kubectl apply）。觸發情境：parser 錯誤「Unhandled
  node type: string」「Contains simple_expansion」「Contains expansion」「Newline
  followed by # inside quoted argument」、「bash heredoc 失敗」、「cd 會污染 CWD」、
  「stateful cd」、「不可逆操作要不要執行」、「terraform apply 確認」、「git push
  --force 安全嗎」、agent 自我反省「這段 bash 太複雜」「要不要寫成 script」
  「cd 指令要不要改成 --directory」時。
---

# Bash Anti-Patterns — Three Defensive Layers for Claude Code Bash Commands

This skill provides a systematic set of bash command conventions to prevent parser
failures from disrupting your workflow, and to set autonomy boundaries for irreversible
operations. The three rule files can be enabled independently.

## Core Philosophy

- **Bash calls are cheap; parser retries are expensive**
- The cost of complexity is ultimately paid by the user on every Cmd+Enter
- Golden rule: never cram multi-step logic into one line to save a bash call

## Anti-Pattern 1: Overly Complex Single Command

### Symptoms

When you hit this, you'll see parser errors that escaping cannot fix:

- `Newline followed by # inside a quoted argument` (class B)
- `Unhandled node type: string` (class D)

### Threshold (>=2 of 5 = excessive; must decompose)

Any two or more of the following make a command too complex:

1. **Multi-line** (heredoc or `\` continuation)
2. **Nested same-type quotes** (`"''"` or `$(cmd "$VAR")` same-quote conflict)
3. **Embedded other language** (`python -c`, `node -e`, `perl -e`, complex multi-line jq)
4. **Multiple `if`/`elif`/`case` branches**
5. **Complex parameter expansion** (`${var//pattern/replace}`, `${!indirect}`, chained `${var%suffix}`)

### What is NOT excessive (avoid false positives)

These are all valid patterns — do not flag them:

```bash
# Valid git workflow chain -- && count alone is not a criterion
git add . && git commit -m "feat: add feature" && git push origin feature

# Valid tool chain
make lint && make test

# Valid simple condition (keep separate; do not merge into && ... || ...)
[ -f ".env" ] || echo "[WARN] .env not found"
[ -f ".env" ] && source .env
# Avoid: [ -f ".env" ] && source .env || echo "..."
# Reason: if source fails, || also triggers echo -- wrong semantics
```

**`&&` count alone is not the criterion** — the issue is complexity inside each segment, not the number of chained segments.

### Fixes (in priority order)

### 1. Split into multiple bash calls (most common and simplest)

Each call solves one problem; the agent reads the result before deciding the next step:

```text
# Wrong: too much in one line
RESULT=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('key', {}).get('nested', ''))
" <<< "$INPUT")
```

```bash
# Fix: two steps (jq with double-quote filter to avoid AP1 class D)
echo "$INPUT" > /tmp/input.json
RESULT=$(jq -r ".key.nested" /tmp/input.json)
```

### 2. Extract to a standalone script

Place it in `~/.claude/scripts/` or the project's `scripts/`, then call via `bash <path>`:

```bash
# Wrong: heredoc with embedded Python
bash -c "$(cat <<'PYEOF'
import re, sys
for line in sys.stdin:
    if re.match(r'pattern', line):
        ...
PYEOF
)"

# Fix: write standalone script, call from bash
cat > /tmp/process.py << 'EOF'
import re, sys
for line in sys.stdin:
    if re.match(r'pattern', line):
        print(line.rstrip())
EOF
python3 /tmp/process.py < input.txt
```

### 3. Use the right tool instead of inline logic

| Need | Avoid | Use instead |
|------|-------|-------------|
| JSON processing | `python3 -c "import json..."` | `jq` |
| Path manipulation | `${VAR%/*}` string expansion | `dirname` / `basename` / `realpath` |
| Simple condition | three-level `if/elif/else` | `[ ]` + `&&`/`\|\|` or `case` |
| Text filtering | inline `awk '{if...}'` | `grep -E` or multiple `grep` + `cut` pipes |

### Before / After Examples

### Example A: complex jq condition → two-step pipe

```text
# Wrong: multi-line jq expression (embedded language + multi-branch = score 2)
RESULT=$(jq -r '
  if .status == "active" then
    .users[] | select(.role == "admin") | .name
  else
    "inactive"
  end
' config.json)
```

```bash
# Fix: split into two steps (jq with double-quote filter; escape inner quotes with \")
STATUS=$(jq -r ".status" config.json)
if [ "$STATUS" = "active" ]; then
  RESULT=$(jq -r ".users[] | select(.role==\"admin\") | .name" config.json)
fi
```

### Example B: nested if/elif → case statement

```text
# Wrong: multi-level if/elif (multi-branch = score 1, plus complex expansion ${EXT##*.} = score 2)
EXT="${FILENAME##*.}"
if [ "$EXT" = "py" ]; then
  RUNNER="python3"
elif [ "$EXT" = "js" ]; then
  RUNNER="node"
elif [ "$EXT" = "rb" ]; then
  RUNNER="ruby"
elif [ "$EXT" = "sh" ]; then
  RUNNER="bash"
else
  RUNNER="unknown"
fi

# Fix: use basename to get extension, then case
EXT=$(basename "$FILENAME" | cut -d. -f2)
case "$EXT" in
  py) RUNNER="python3" ;;
  js) RUNNER="node" ;;
  rb) RUNNER="ruby" ;;
  sh) RUNNER="bash" ;;
  *)  RUNNER="unknown" ;;
esac
```

### Example C: inline Python heredoc → standalone script

```bash
# Wrong: heredoc + embedded Python (score 1 + score 3 = 2, excessive)
python3 - <<'EOF'
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    if item.get('active'):
        print(item['name'])
EOF

# Fix: write Python to a standalone file; cat heredoc only writes the file (score 1 = acceptable)
# Note: cat > file heredoc just writes the file, does not execute Python -- score drops from 2 to 1
cat > /tmp/filter_active.py << 'EOF'
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    if item.get('active'):
        print(item['name'])
EOF
python3 /tmp/filter_active.py < data.json
```

## Anti-Pattern 2: Special Unicode in Bash Command Strings

### Scope (read carefully to avoid over-restriction)

This rule applies only to: **the character content of the bash command string itself**

- `echo` string arguments
- Variable value literals
- Filename literals
- Heredoc content inside bash

**Not restricted:**

- File content read by bash (`cat README.md` containing emoji is fine)
- File content written by bash (text going into `.md` files is at the file level)
- Markdown document prose
- Code comments
- Commit message text (git accepts UTF-8)

### Characters that block the parser

The following characters in **bash command strings** will jam the Claude Code bash tool parser:

| Type | Example chars | Unicode range |
|------|--------------|---------------|
| Em dash | — | U+2014 |
| En dash | – | U+2013 |
| Emoji (icon types) | most Unicode emoticons | U+1F300–U+1FAFF, U+2600–U+27BF |
| Zero-width space | (invisible) | U+200B etc. |

**CJK characters, full-width punctuation, and ASCII punctuation are all fine.**

### Replacement table (for bash command strings)

| Original | Replace with |
|----------|-------------|
| Skip icon | `[SKIP]` or `(skipped)` |
| OK/check icon | `[OK]` or `(ok)` |
| Warning icon | `[WARN]` or `(warn)` |
| Fail icon | `[FAIL]` or `(fail)` |
| Rocket/go icon | `[GO]` |
| Em dash — | `--` (ASCII double hyphen) |
| En dash – | `-` (ASCII hyphen) |

### Examples

```text
# Wrong: emoji inside bash echo string (this line jams the parser)
echo "  ⏭ no docker-compose, skipping"

# Fix: use ASCII alternative
echo "  [SKIP] no docker-compose, skipping"

# Wrong: em dash inside bash echo string ([EM_DASH] represents U+2014 to avoid triggering linter)
echo "PREREQ: NOT_FOUND [EM_DASH] stop here"

# Fix: use ASCII double hyphen
echo "PREREQ: NOT_FOUND -- stop here"

# OK: emoji in a markdown document paragraph (this is not a bash command)
# README.md: > [OK] installation complete

# OK: bash cat reading a file that contains emoji (emoji is in the file, not in the bash string)
cat README.md
```

## Agent Self-Check Checklist

Before writing a bash command, quickly ask:

- [ ] Does this bash call have newlines? (heredoc, backslash continuation)
- [ ] More than two levels of nested quotes? (`"''"` form, or `$(cmd "$VAR")` same-type conflict)
- [ ] Embedded another language? (`python -c`, `node -e`, multi-line jq)
- [ ] Emoji or em dash in the bash string?
- [ ] Contains `cd <path> &&`? → classify sub-type: use `--directory` / `git -C` / absolute path
- [ ] Using `grep "...\|..."` double-quote BRE? → switch to single quotes
- [ ] Using `$(outer "$(inner)")` reverse-nested subshell? → split into two calls
- [ ] Is this an irreversible operation? (`rm -rf` / force push / migrate / publish) → explain first, wait for confirmation
- [ ] Using `sudo` / `env` / `watch` or similar wrappers around an irreversible operation? → deny rules still intercept; wrappers do not bypass them

### AP1 threshold: if any 2 of newline / nested quotes / embedded language answer yes → split bash call / write script / use right tool

## Enabling in Your Project

The three rules can be enabled independently. Store each `.md` in your project's
`.claude/rules/` directory — Claude Code will load them unconditionally at session start
(no keyword trigger required).

### Rule 13: bash command anti-patterns (AP1 + AP2 + AP3)

Store as `.claude/rules/13-bash-anti-patterns.md`:

```markdown
# Bash Anti-Patterns

## Anti-Pattern 1: Overly Complex Single Command

Threshold (complexity score: >=2 of 5 = excessive, must decompose):
1. Multi-line (heredoc / backslash continuation)
2. Nested same-type quotes (double inside double, or $(cmd "$VAR") same-type conflict)
3. Embedded other language (python -c / node -e / multi-line jq expression)
4. Multiple if / elif / case branches
5. Complex parameter expansion (${var//pattern/replace}, indirect refs)

Not excessive: pure git workflow chains, linear tool chains (make lint && make test).
"&& count alone is not the criterion." Fix: split bash call / write script / use jq|realpath.
Golden rule: never cram multi-step logic into one line to save a bash call.

## Anti-Pattern 2: Special Unicode in Bash Command Strings

Scope: the character content of bash commands themselves (echo strings, variable literals, heredoc content).
Not restricted: file content read/written by bash, markdown docs, code comments, commit messages.
Banned: em dash (—) / en dash (–) / emoji / zero-width space.
Replacements: [SKIP] / [OK] / [WARN] / [FAIL] / -- / -

## Anti-Pattern 3: Stateful cd

Three failure modes of cd <path> && cmd, each with a different fix:
- cd ... && git <cmd>         -> git -C <path> <cmd>  (class C hook intercepts)
- cd ... && uv run            -> uv run --directory <path>  (no hook; silent blind spot)
- cd ... && cmd 2>/dev/null   -> use absolute path, remove cd  (class F1 hook intercepts)

Full methodology: skill bash-anti-patterns.
```

### Rule 14: shell quoting hygiene

Store as `.claude/rules/14-shell-quoting-hygiene.md`:

```markdown
# Shell Quoting Hygiene

Rule 1: $VAR inside $(cmd $VAR) must always be quoted -> "$VAR" (prevents simple_expansion; avoid bracket form "${VAR}", see Rule 5)
Rule 2: "$(cmd "$VAR")" same-type quote conflict -> split into separate bash call (prevents class D)
Rule 3: grep "pat\|pat2" double-quote BRE -> fix in priority order: A) Claude Code Grep tool (recommended); B) grep -Ei 'pat1|pat2' (ERE, GNU-recommended); C) grep -i 'pat1\|pat2' (BRE single-quote, valid but backslash-prone) — prevents class D
Rule 4: $(outer "$(inner)") reverse-nested subshell -> split into two separate bash calls (prevents class D)
Rule 5: "${VAR}" bracket form triggers expansion false positive -> use "$VAR" plain form instead

Full methodology and decision flow: skill bash-anti-patterns.
```

### Rule 15: irreversible operation boundaries

Store as `.claude/rules/15-irreversible-operations.md`:

```markdown
# Irreversible Operation Boundaries

The following operations must not be executed autonomously by the agent.
Explain the impact and wait for user confirmation first:

DB / Storage: alembic upgrade/downgrade, prisma migrate deploy, DROP/TRUNCATE/DELETE without WHERE
Deployment: kubectl apply (prod), terraform apply, gh release create, npm/uv publish
Git: git push --force/-f, git reset --hard, shared branch rebase, git filter-branch
File: rm -rf, find ... -delete, > overwriting an existing file
Cloud: aws s3 rm --recursive, gcloud compute instances delete

Standard response format:
STOP: <operation description>
Impact: <resources affected and scope>
Rollback difficulty: High / Medium / Low
Recommendation: <dry-run command> or <ask user to run manually>

Full list and v3 deny list backlog: skill bash-anti-patterns.
```

### Path 2: Install PreToolUse hooks (advanced — mechanical interception)

Adding two hooks provides mechanical blocking of the highest-frequency AP1 / AP2 violations:

1. Copy hooks from this repo:
   - AP1 hook: `.claude/hooks/bash-ap1-inline-check.sh` (intercepts python -c multiline / osascript heredoc / grep BRE alternation / reverse-nested subshell)
   - AP2 hook: `.claude/hooks/bash-ap2-check.py` or `hooks/pre-tool-use-bash-unicode.sh` (intercepts Unicode)

2. Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/bash-ap1-inline-check.sh" },
          { "type": "command", "command": "python3 $CLAUDE_PROJECT_DIR/.claude/hooks/bash-ap2-check.py" }
        ]
      }
    ]
  }
}
```

AP3 / Rule 14 Rule 5 / Rule 15 complexity judgments are handled by prompt rules, not hooks.

## exec wrapper Penetrates deny rule (2026-05)

Claude Code `settings.json` `permissions.deny` rules now see through the following wrappers:

| Wrapper | Description |
|---------|-------------|
| `sudo` | privilege escalation |
| `env` | environment variable injection |
| `watch` | periodic execution |
| `ionice` | I/O priority setting |
| `setsid` | new session execution |

**Important**: all of the following are still intercepted by deny rules — do not assume wrappers bypass them:

```bash
# All of these are still blocked by deny rules
sudo rm -rf /dangerous/path
env DANGEROUS_VAR=1 bash script.sh
watch -n1 bash -c "rm /tmp/files"
ionice -c 3 rm -rf /path
```

**For users**: once deny rules are configured in `settings.json`, even agent-generated commands
with wrappers are intercepted. This is a reliable way to strengthen Rule 15 irreversible
operation protection:

```json
{
  "permissions": {
    "deny": [
      "Bash(rm -rf*)",
      "Bash(sudo rm*)",
      "Bash(env * rm*)"
    ]
  }
}
```

**For the agent**: when blocked by a deny rule, stop and explain the operation;
ask the user to run it manually (Rule 15 standard behavior). Do not try to use wrappers
to bypass the rule.

## Why This Happens (Technical Background)

Claude Code's bash tool uses a simplified shell parser rather than a full bash AST parser:

- `#` characters inside heredocs, and quote nesting beyond a certain depth, trigger parser edge cases
- Unicode codepoints at certain byte boundaries have off-by-one bugs on some platforms
- These issues are unrelated to specific bash versions or OS — they are tool-layer limitations

No need to understand the implementation details — knowing the threshold and fix is enough.

## Relationship to This Repo

This skill is the complete cross-project version. The three rule files in yibi-stack are
a condensed subset:

- `.claude/rules/13-bash-anti-patterns.md`: AP1/AP2/AP3 thresholds and quick reference
- `.claude/rules/14-shell-quoting-hygiene.md`: five quoting error types, Rules 1-5
- `.claude/rules/15-irreversible-operations.md`: five categories of irreversible operation boundaries

Maintenance discipline: when changing core threshold criteria in a rule, sync the skill;
when adding examples or technical background to the skill, the rule does not need to change.
The three rules can each be maintained independently.
