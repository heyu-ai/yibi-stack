# Allow-list Hygiene

When the Claude Code permission dialog shows "Yes, and don't ask again for: `<pattern>`",
the pattern is permanently added to `~/.claude/settings.local.json`.
This rule defines which patterns must **not** be permanently allowed and how to write safe ones.

**Source**: Claude Code official permissions docs (<https://code.claude.com/docs/en/permissions>).
All wildcard/pattern semantics are verified against the official docs, not inferred.

## Why It Matters

**`*` in a `Bash()` pattern spans multiple arguments** (official docs):

> "A single `*` matches any sequence of characters including spaces, so one wildcard
> can span multiple arguments. `Bash(git *)` matches `git log --oneline --all`, and
> `Bash(git * main)` matches `git push origin main` as well as `git merge main`."

`Bash(git -C * status)` looks like it locks the verb to `status` but actually allows
`git -C /any push --force origin status` — `*` consumes `<path> push --force origin`.

Official docs also warn that argument constraints are inherently fragile (see Red Flag 4).

**Conclusion: lock the verb at the pattern prefix; use only a trailing wildcard.**

## Pattern Semantics (official docs)

| Pattern | Semantics | Example |
|---------|-----------|---------|
| `Bash(verb)` | Exact match | `Bash(make ci)` matches only `make ci` |
| `Bash(verb *)` | Verb at prefix; trailing wildcard enforces word boundary | `Bash(npm run *)` matches `npm run build` but NOT `npm runtest` |
| `Bash(verb:*)` | Equivalent to `Bash(verb *)` | `Bash(git status:*)` === `Bash(git status *)` |
| `Bash(verb*)` | No word boundary | `Bash(ls*)` matches `ls -la` AND `lsof` |
| `Bash(* verb)` | Any prefix + verb at end | `Bash(* install)` matches `npm install` and `pip install` |
| `Bash(verb1 * verb2)` | `*` spans multiple args; middle is unconstrained | `Bash(git * main)` matches both `git merge main` and `git push origin main` |

`:*` is a trailing wildcard only at the end of the pattern; `:` elsewhere is literal.

## Red Flags — Choose One-Time Approval If Any Match

### Red Flag 1: Wildcard in the Middle (Most Dangerous)

```text
Bash(git -C * status)      Bash(verb1 * verb2)
Bash(curl https://host/*)  Bash(uv run --directory * pytest)
```

`*` spans any number of args and flags — `Bash(uv run --directory * pytest)` allows
`uv run --directory /tmp --with malicious-package pytest`.

**Fix**: `Bash(git status:*)`, `Bash(git status *)`. For `-C <path>` / `--directory <path>`,
write per-repo exact patterns or accept per-invocation confirmation.

### Red Flag 2: Verb-Level Wildcard

```text
Bash(git *)  Bash(npm *)  Bash(rm *)  Bash(curl *)
```

Covers all subcommands. `Bash(git *)` includes `commit`, `push`, `reset --hard`, `filter-branch`.

**Fix**: per-verb read-only patterns — `Bash(git status:*)`, `Bash(git log:*)`, etc.
`rm` and `curl` must never be allow-listed (see Red Flag 4).

### Red Flag 3: Variable Expansion or Variable Assignment Prefix

```text
Bash(* "$VAR" *)   Bash(PATH="..." git *)   Bash(* ${HOME}/*)
```

- `"$VAR"` patterns: match scope depends on runtime value; cannot be statically reviewed.
- `PATH="..." git ...`: first token is `PATH=...` not `git`, so `Bash(git *)` does not match.

Note: `PATH=...` is a shell assignment, not an exec wrapper. Stripped wrappers (`timeout`,
`time`, `nice`, `nohup`, `stdbuf`, bare `xargs`) and always-prompt wrappers (`watch`,
`setsid`, `ionice`, `flock`) are separate mechanisms in the official docs.

**Fix**: use absolute path, e.g., `Bash(/Users/<you>/.asdf/shims/git status:*)`.

### Red Flag 4: Network Tools and URL Constraints

Official docs explicit warning on `Bash(curl URL ...)`:

> "For more reliable URL filtering, consider:
> - **Restrict Bash network tools**: use deny rules to block `curl`, `wget`; use
>   `WebFetch(domain:github.com)` for allowed domains
> - **Use PreToolUse hooks**: validate URLs at runtime
> - **Add CLAUDE.md guidance**: describe allowed curl patterns"

**Fix**: `deny: Bash(curl *)`, `Bash(wget *)`, `Bash(* | sh)`, `Bash(* | bash)`;
`allow: WebFetch(domain:known.host)`.

### Red Flag 5: Redirection or Pipeline Wildcard

```text
Bash(* >> *)  Bash(* > *)  Bash(* | sh)  Bash(* | bash)
```

Equivalent to allowing arbitrary file writes or arbitrary command execution.

**Fix**: do not allow-list. Use Edit/Write tools for file writes; extract pipelines to a script.

## Safe Pattern Examples

General rule: **verb fixed at prefix, wildcard only at end, read-only or full absolute script path**.

| Pattern | Why safe |
|---------|----------|
| `Bash(make ci)` | Exact match |
| `Bash(git status:*)` | Verb locked at prefix; `:*` enforces word boundary |
| `Bash(git log:*)` | Read-only |
| `Bash(git diff:*)` | Read-only; does not modify filesystem |
| `Bash(git rev-parse:*)` | Read-only |
| `Bash(git fetch:*)` | Reads remote; does not touch working tree |
| `Bash(npm run *)` | Subcommand locked to `run` |
| `Bash(bash /Users/<you>/.agents/skills/foo/scripts/setup.sh)` | Absolute path exact match; reviewing once = permanent trust |

Key points:
1. `Bash(verb)` and `Bash(verb:*)` are the only reliable forms; never use a middle wildcard.
2. `~` does **not** expand in `Bash()` patterns (`~` expansion is only for Read/Edit rules).
   Use absolute path: `Bash(bash ~/foo.sh)` will not match `bash /Users/me/foo.sh`.
3. `Bash(rm *)`, `Bash(curl *)`, `Bash(wget *)` must never be allow-listed.

## Relationship to Fat Command Anti-pattern

Fat commands (`&&` chains) break allow-list matching:
agent writes fat command → verb not at prefix → `Bash(cmd *)` can't match → manual confirm
→ user nudged toward "don't ask again" → permanently allowed pattern has middle wildcard (Red Flags 1/3).

**Root fix**: extract fat command into `scripts/foo.sh`; allow-list only `Bash(bash /abs/path/scripts/foo.sh)`.

See rule 13 "AP1 auto-fix triggers" and the CLAUDE.md "Slash command bash block rewritten by agent" gotcha.

## Remediating Existing Unsafe Patterns

1. Open `~/.claude/settings.local.json`; find red-flag entries in `permissions.allow`.
2. For each, identify the single verb you want to permit.
3. Rewrite as "verb fixed at prefix + read-only" or "full absolute path + script".
4. Restart Claude Code to apply.

Example (`<abs-path-to-git>`: run `which git`; typical: `/opt/homebrew/bin/git`, `/usr/bin/git`):

```diff
 "permissions": {
   "allow": [
-    "Bash(PATH=\"/Users/me/.asdf/shims:$PATH\" git *)",
+    "Bash(<abs-path-to-git> status:*)",
+    "Bash(<abs-path-to-git> log:*)",
+    "Bash(<abs-path-to-git> diff:*)",
+    "Bash(<abs-path-to-git> rev-parse:*)",
+    "Bash(<abs-path-to-git> fetch:*)",
+    "Bash(bash /Users/<you>/.agents/skills/pr-review-cycle-mob/scripts/setup-review-dir.sh)"
   ]
 }
```

- Absolute path replaces `PATH=` so the first token is the binary itself.
- `git *` split into per-verb read-only subcommands with trailing `:*` word boundary.
- `git commit:*`, `git push:*`, `git reset:*` excluded intentionally (confirmation = safety net).

## Rule 13 / Rule 16 Relationship

- Rule 13: how the agent **writes** bash (no fat commands, no same-type quote conflicts).
- Rule 14: **shell quoting/variable expansion** hygiene (including `$?` — use `if ! cmd; then`).
- Rule 16: how **users/agents configure** allow-list patterns (no middle wildcards, no variable prefixes).

Rules 13+14 produce bash that allow-list patterns can precisely match.
Rule 16 ensures the allow-list is not broader than intended.
Without both sides, either unexpected commands slip through or users face endless confirmation fatigue.
