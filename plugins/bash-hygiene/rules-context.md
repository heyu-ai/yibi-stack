# Bash Anti-Pattern Rules (injected by ainization-bash-hygiene plugin)

## Anti-Pattern 1: Overly Complex Single Commands

Complexity score (5 criteria, >= 2 means too complex, must split):

1. Multi-line (heredoc or backslash continuation)
2. Nested quotes (double inside single inside double, or `$(cmd "$VAR")` same-type conflict)
3. Inline other languages (`python -c`, `node -e`, complex jq expressions)
4. Multi-level if/elif/case branches
5. Complex parameter expansion (`${var//pattern/replace}`, indirect `${!var}`)

NOT overly complex: pure git workflow chains, linear tool chains (`make lint && make test`).

Fix priority: 1) Split into multiple bash calls 2) Write standalone script 3) Use proper tools (jq, realpath, basename)

Golden rule: never squeeze multi-step logic into one line to save a bash call.

## Anti-Pattern 2: Unicode in Bash Command Strings

Scope: only bash command string content (echo strings, variable literals, heredoc content).
NOT restricted: file content read by bash, markdown docs, code comments, commit messages.

Prohibited: em dash, en dash, emoji, zero-width whitespace.
Replacements: [SKIP] / [OK] / [WARN] / [FAIL] / -- / -

## Anti-Pattern 3: Stateful cd

`cd <path> && cmd` has three harm mechanisms:
- `cd ... && git <cmd>` -> use `git -C <path> <cmd>`
- `cd ... && uv run` -> use `uv run --directory <path>`
- `cd ... && cmd 2>/dev/null` -> use absolute paths, remove cd

## Shell Quoting Hygiene

Rule 1: `$(cmd $VAR)` — always quote: `"$VAR"` (prevents simple_expansion)
Rule 2: `"$(cmd "$VAR")"` same-type quote conflict — split into separate bash calls
Rule 3: `grep "pat\|pat2"` double-quoted BRE — use single quotes: `grep 'pat\|pat2'`
Rule 4: `$(outer "$(inner)")` reverse nesting — split into two bash calls
Rule 5: `"${VAR}"` brace form triggers expansion false positive — use `"$VAR"` plain form

## Irreversible Operations

The following must NOT be executed autonomously by the agent. Explain impact and get user confirmation first:

- DB: alembic upgrade/downgrade, prisma migrate deploy, DROP/TRUNCATE/DELETE without WHERE
- Deploy: kubectl apply (prod), terraform apply, gh release create, npm/uv publish
- Git: git push --force/-f, git reset --hard, shared branch rebase
- File: rm -rf, find ... -delete, overwrite existing files with >
- Cloud: aws s3 rm --recursive, gcloud instances delete

## Prefer Built-in Tools Over Bash for Code Search

Use Grep/Glob tools instead of `cd $(...) && rg ... 2>/dev/null | head -10`.
Benefits: zero CWD dependency, no hook triggers, no manual truncation.

Use bash `rg`/`find` only when you need features like `--json`, `-exec`, `wc -l`, or searching gitignored files.
