# Security

## Never Commit Sensitive Files

The following are in `.gitignore` — never attempt to commit them:

- `.env` — API keys, passwords, encryption keys
- `.runtime/` — JSON configs (may contain encrypted passwords), SQLite DB
- `output/` — all skill output files

## Password Encryption

Passwords stored in `.runtime/` JSON must be Fernet-encrypted first:

```python
# Correct: store the encrypted value
config.pdf_secret_fernet = encrypt(secret, key)

# Wrong: store plaintext in JSON
config.pdf_secret = "<plaintext>"
```

Encryption key from environment variable, never hardcoded:

```python
key = os.environ["ENCRYPT_KEY"].encode()  # loaded from .env
```

## Parameterized SQL

Always use `?` placeholders — never f-string concatenation:

```python
# Correct
cursor.execute("SELECT * FROM runs WHERE job_id = ?", (job_id,))

# Wrong
cursor.execute(f"SELECT * FROM runs WHERE job_id = '{job_id}'")
```

Dynamic WHERE clauses (variable number of conditions):

```python
conditions = []
params: list[object] = []
if status:
    conditions.append("status = ?")
    params.append(status)
where = f"WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
cursor.execute(f"SELECT * FROM runs {where}", params)  # nosec B608
```

## Protect-Push Hook

`.claude/hooks/protect-push.sh` prevents direct pushes from a worktree branch to `origin/main`.
Do not bypass this hook or use any flags that disable git hook validation.

## Scanner Gate Design

A security scanner's precondition gate (e.g., `gitignore_ok`) must only control score
accumulation — never use early return to suppress findings output. Users need to see
all detection results even when a gate fails.

```python
# Correct: gate only affects score; findings always run
if not gitignore_ok:
    pass  # score not accumulated, but scanning continues
findings.append(check_dangerous_commands())

# Wrong: early return hides all downstream findings
if not gitignore_ok:
    return MechanicalFinding(score=0, findings=["WARN: no .gitignore"])
```

## Injection Pattern Regex: Use `\s+` Not Literal Space

When writing regex patterns to detect injection payloads, use `\s+` instead of
literal space between words. A literal space only matches a single space (U+0020); `\s+`
matches any whitespace including `\n`, `\t`, and multiple spaces — necessary to
block multi-line payloads where words are newline-separated.

```python
# Wrong: "do not\nreport findings" bypasses this pattern
re.compile(r"do not (report|flag|mention)", re.IGNORECASE)

# Correct: \s+ matches space, tab, newline — blocks multi-line payloads
re.compile(r"do\s+not\s+(report|flag|mention)", re.IGNORECASE)
```

Note: `re.DOTALL` only changes `.` (dot) behavior — it does **not** make literal
spaces match newlines. Both `re.DOTALL` (for `.*`-based patterns) AND `\s+` (for
space-separated multi-word patterns) are needed for comprehensive coverage.

## bandit `# nosec` Must Be on the Flagged Line

`# nosec B608` (or any bandit B-code) must appear on the **same line** that bandit
actually scans — not on a wrapping parenthesis or assignment line.

```python
# Wrong: nosec on the paren line; bandit flags the f-string line (line below)
sql = (  # nosec B608
    f"SELECT * FROM foo WHERE {where} ORDER BY created_at ASC LIMIT ?"
)

# Correct: nosec on the f-string line itself
sql = (
    f"SELECT * FROM foo WHERE {where} ORDER BY created_at ASC LIMIT ?"  # nosec B608
)
```

**ruff format interaction:** ruff may want to inline a parenthesized expression.
Before fighting ruff with parens, first measure the inline form:
if `len(indent) + len(expression) + len("  # nosec B608")` ≤ `max-line-length`,
accept ruff's inline format — it is both shorter and correctly suppresses bandit:

```python
# ruff inline form (97 chars, within 100 limit) — correct and bandit-clean
sql = f"SELECT * FROM foo WHERE {where} ORDER BY created_at ASC"  # nosec B608
if limit is not None:
    sql += " LIMIT ?"
```

## OTEL Logs the Full Assistant Response — Disable It for Sensitive-Output Environments

Claude Code (v2.1.193) added a `claude_code.assistant_response` OpenTelemetry log event
containing the model's reply text. It is gated by `OTEL_LOG_ASSISTANT_RESPONSES`, but **when
that variable is unset it falls back to `OTEL_LOG_USER_PROMPTS`** — meaning a deployment that
already logs prompt content will automatically start logging reply content after upgrading.
This is on the same axis as the existing "never `echo $VAR` a key into the transcript" rule,
but stealthier: no command is needed; a plain version upgrade activates it.

Any skill environment that handles decrypted billing data, account numbers, or keys
(`gmail-billing`, `ledger-import`, `saas-*`) must explicitly set
`OTEL_LOG_ASSISTANT_RESPONSES=0` when OTEL is enabled, so sensitive content in the reply is
not recorded:

```bash
# On a prompt-logging environment, keep logging prompts but never replies
export OTEL_LOG_ASSISTANT_RESPONSES=0
```

**This repo does not currently enable OTEL** — this is a preventive guard: the moment anyone
turns on OTEL telemetry in CI or locally, the rule applies.

## `sandbox.credentials`: Do Not Enable Globally (Financial Skills Need Their Keys)

The `sandbox.credentials` setting (v2.1.187) blocks sandboxed commands from reading credential
files and secret environment variables. It is double-edged: it prevents a sandboxed bash
command from leaking secrets, but it also blocks flows that **legitimately need keys** — this
repo's `gmail-*` / `ledger-import` / `saas-*` skills require secret env vars such as
`GMAIL_TOKEN` and `ENCRYPT_KEY` to function.

**Decision: do not enable `sandbox.credentials` globally.** This trade-off is recorded
explicitly so nobody enables it in the name of "hardening" and silently breaks every financial
skill's key access. If a real need arises, evaluate it per-flow for sandboxed flows that never
touch secrets, rather than applying it globally.
