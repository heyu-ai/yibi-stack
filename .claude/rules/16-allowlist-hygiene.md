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

## Advanced Rule Syntax: Tool-Parameter Matching and Tool-Name Globs (v2.1.172 / v2.1.178)

Newer Claude Code versions extend permission rules beyond `Bash(...)` command prefixes. These
apply to **any** tool, not just Bash, and are useful for `deny` rules in particular.

| Syntax | Meaning | Example |
|--------|---------|---------|
| `Tool(param:value)` | Match a tool by an input-parameter value; `*` wildcard allowed in the value (v2.1.178) | `Agent(model:opus)` matches an Agent/subagent call whose `model` is `opus` |
| Tool-name glob in the rule's tool position | `*` in the tool-name slot matches tool names; `"*"` matches every tool (Week 24) | `deny: "*"` denies all tools; `deny: "mcp__*"` denies all MCP tools |
| `WebFetch(domain:*.example.com)` | Subdomain wildcard for WebFetch domains (v2.1.172 fix made `*.` actually match subdomains) | matches `api.example.com`, `cdn.example.com` |

Practical uses:

- **Cap subagent model cost**: `deny: Agent(model:opus)` blocks spawning Opus subagents while
  still allowing cheaper tiers.
- **Subdomain allow-list**: `allow: WebFetch(domain:*.anthropic.com)` instead of enumerating
  each host — note this is the v2.1.172 fix; on older versions `*.` did not match subdomains.

These follow the same middle-wildcard caution as Bash patterns: a `value` wildcard that is too
broad (e.g. `Tool(arg:*)`) re-creates the over-broad-pattern problem from the Red Flags below.
Constrain the value as tightly as the use case allows.

> **Note**: an earlier internal cross-reference pointed this material at a `rule 14`
> (shell-quoting-hygiene). That file no longer exists — its content was merged into
> `13-bash-anti-patterns.md`. Permission-rule syntax lives here in rule 16.
>
> **This repo today**: `.claude/settings.local.json` lists `WebFetch(domain:...)` rules as fixed
> hosts (no `*.`). Consolidating them into `*.domain` form is optional, not required.

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
>
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
+    "Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh)"
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

## Built-in `/less-permission-prompts` — Usage Warning

Since Claude Code 2.1.111, the built-in `/less-permission-prompts` skill scans the current transcript for frequently used
read-only Bash/MCP calls and **automatically generates a sorted allowlist suggestion**. Understand the following limitations
before using it:

### Common Red-Flag Patterns in Automatic Suggestions

`/less-permission-prompts` sorts by execution frequency, so high-frequency commands (`git`, `npm`, `uv`) often produce:

```json
"Bash(git *)",
"Bash(npm *)",
"Bash(uv *)"
```

All of these are **Red Flag 2 (verb-level wildcard)** — covering all subcommands of that binary, including destructive operations.

### Correct Workflow

1. Run `/less-permission-prompts` to get the suggestion list
2. **Review each pattern against the Red Flag criteria (1–5) in this rule**
3. Approve only patterns that pass; **manually rewrite** those that fail before adding them

Rewrite examples:

| Auto-suggested (red flag) | Safe rewrite |
|--------------------------|-------------|
| `Bash(git *)` | `Bash(git status:*)` / `Bash(git log:*)` / `Bash(git diff:*)` |
| `Bash(npm *)` | `Bash(npm run:*)` / `Bash(npm ls:*)` |
| `Bash(uv *)` | `Bash(uv run pytest:*)` / `Bash(uv sync)` |

### Never Do This

**Never blindly accept all suggestions from `/less-permission-prompts` with "Yes, and don't ask again".**
The tool attempts to filter read-only calls but does so incompletely: commands with ambiguous semantics like `git reset *` or `curl *` may still appear.
More critically: even when only genuinely read-only calls are listed, the generated pattern may be `Bash(git *)` — a
verb-level wildcard covering all subcommands of the entire binary, including destructive operations.
**Frequency statistics cannot guarantee pattern safety.**

## Session-Dialog "Always Allow" Cannot Permanently Permit `$CLAUDE_JOB_DIR` — Use `settings.local.json` Instead

`$CLAUDE_JOB_DIR` expands to `~/.claude/jobs/<UUID>/` — a new UUID per background session.
The permission dialog's "Yes, and always allow access to `<UUID>/`" option locks that specific UUID;
the next session's UUID does not match and the prompt reappears.
**Permanently allowing job-dir access requires wildcard patterns in `~/.claude/settings.local.json`**
(see the two scenarios below) — not the session dialog.

**Two trigger scenarios require different fixes:**

**(1) Edit/Write tool writes to job dir** — add trailing-wildcard patterns to `~/.claude/settings.local.json`:

```json
"Edit(/Users/<you>/.claude/jobs/*)",
"Write(/Users/<you>/.claude/jobs/*)"
```

The path prefix is fixed; `*` covers all future UUIDs.

**(2) Bash redirect `>` writes to job dir** (e.g., `cmd > $CLAUDE_JOB_DIR/out.json`) —
permission type is `Bash()`, not `Edit()`. Add a verb-prefix pattern per command:

```json
"Bash(spectra analyze:*)",
"Bash(uv run python -m tasks.mycelium:*)"
```

Do **not** use `Bash(* > *)` — this is Red Flag 5 (redirection wildcard); it covers arbitrary
file writes and must never be allow-listed. Lock the verb at the prefix instead.
