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
