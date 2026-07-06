# Error Handling & Imports

## Exception Type Selection

| Situation | Exception type |
|-----------|---------------|
| Environment not set up, external tool unavailable, decryption failure, missing file | `RuntimeError` |
| Malformed input, invalid config value | `ValueError` |
| Inside a Pydantic validator | `ValueError` (Pydantic wraps it into `ValidationError`) |

## Exception Chaining

Always use `raise ... from e` to preserve the full traceback:

```python
try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    raise RuntimeError(f"設定檔格式錯誤：{config_path}") from e
```

## Deferred Heavy Imports

The following third-party libraries must be imported inside function bodies,
never at module top-level:

- `pikepdf`, `pdfplumber`, `tabula`
- `cryptography.fernet`
- `playwright`
- `pytesseract`, `PIL`

```python
# Correct
def decrypt_pdf(path: Path, password: str) -> Path:
    from cryptography.fernet import Fernet
    ...

# Wrong
from cryptography.fernet import Fernet  # module top-level
```

Standard library (`pathlib`, `json`, `sqlite3`) and lightweight packages
(`click`, `pydantic`, `requests`) may be imported at top-level.

## Subprocess

```python
import subprocess  # nosec B404

result = subprocess.run(  # nosec B603
    ["uv", "run", "python", "-m", "tasks.gmail_scan", "status"],
    capture_output=True,
    text=True,
    timeout=60,
)
```

- Always use list args (never `shell=True`)
- Always set `timeout`
- Add bandit nosec comments: `# nosec B404` (import), `# nosec B603` (call)

## Filesystem Path Existence Checks

Prefer `is_dir()` / `is_file()` over `exists()`:

```python
# Wrong: returns True for a same-named non-directory file; rglob() raises NotADirectoryError
if path.exists():
    for f in path.rglob("*.md"): ...

# Correct: directly excludes non-directories
if path.is_dir():
    for f in path.rglob("*.md"): ...
```

Use `exists()` only when type doesn't matter (e.g., config files, log files).

## File Read TOCTOU

`path.exists()` followed by `path.read_text()` is a TOCTOU race — the file can disappear
between the two calls. Always wrap `read_text()` in `try/except OSError`, independent of
any prior existence check:

```python
# Wrong: exists() does not guarantee read_text() succeeds
if settings_path.exists():
    data = json.loads(settings_path.read_text(encoding="utf-8"))  # can still raise OSError

# Correct: catch OSError at the read call
if settings_path.exists():
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except OSError as e:
        findings.append(f"WARN: 無法讀取：{e}")
    except json.JSONDecodeError as e:
        findings.append(f"WARN: 格式錯誤：{e}")
```

This applies to any file read inside a scanner or service — another process may delete
or replace the file between the `exists()` check and the `read_text()` call.

## Pathlib Semantics

`Path.with_suffix(ext)` **replaces** the last extension — it does not append:

```python
# Trap: with_suffix replaces .json; settings.json.tmp only works by coincidence
tmp = SETTINGS_PATH.with_suffix(".json.tmp")   # settings.json -> settings.json.tmp

# Correct: explicitly name the file
tmp = SETTINGS_PATH.with_name("settings.json.tmp")  # intent is clear
```

For `.tmp` scratch files, always use `with_name(stem + ".tmp")` or `with_name("filename.tmp")`.

## Type Guard at External Data Boundaries (PR #92)

Validate the type of external data **before** entering business logic — especially in hooks
and scripts that read from `json.load(sys.stdin)` or similar sources.

```python
# Wrong: command=None (JSON null) reaches _scannable() -> TypeError crash
data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")
m = _AP2.search(_scannable(command))  # TypeError if command is None

# Correct: isinstance guard before entering business logic
command = data.get("tool_input", {}).get("command", "")
if not isinstance(command, str):
    sys.exit(0)
m = _AP2.search(_scannable(command))
```

Scope: any function that receives data from external sources (stdin JSON, API response,
config file) where the type cannot be statically guaranteed. Even when `dict.get()` has a
default, callers may pass explicit `None` values that override the default.

## `Path.rglob()` Does Not Follow Symlinks

`pathlib.rglob()` does not descend into symlinked subdirectories by default.
If the target directory contains symlinks (e.g., `skills/` with plugin symlinks in this repo),
use `os.walk(followlinks=True)` or Python 3.13+ `glob(follow_symlinks=True)`:

```python
# Wrong: rglob() silently skips symlinked subdirectories
for f in skills_dir.rglob("SKILL.md"):
    ...

# Correct: os.walk with followlinks=True
import os
for root, dirs, files in os.walk(skills_dir, followlinks=True):
    for name in files:
        if name == "SKILL.md":
            process(Path(root) / name)
```

## `Path.glob()`'s `*` Does Not Cross `/` (Unlike Regex `.*`)

`pathlib.Path.glob("*/skills/*/SKILL.md")`'s `*` only matches **one** path segment,
unlike regex `.*` which crosses `/` freely. Nested structures (e.g.,
`plugins/growth/skills/mycelium/recap/SKILL.md`) need `**`
(`plugins_dir.glob("*/skills/**/SKILL.md")`), or nested items are silently excluded
with no error:

```python
# Wrong: only matches one level, misses mycelium/recap and similar nested sub-skills
plugins_dir.glob("*/skills/*/SKILL.md")

# Correct: ** recursively matches any depth
plugins_dir.glob("*/skills/**/SKILL.md")
```

This is the mirror-image gotcha of the `Path.rglob()` symlink issue above: both are cases
where pathlib's traversal semantics differ from what a regex-trained intuition would expect.
(Incident: PR #190 — Codex mob review found 4 `plugins/growth/skills/mycelium/*` nested
sub-skills excluded from a lint tool's scan with zero diagnostic.)

## Fixer Loop Exhaustion Must Transition to BLOCKED, Not a Waiting State

When a fixer loop exhausts all available fixers (every fixer raises an exception),
transitioning back to a waiting/retry state (e.g., `CI_WAIT`) creates a silent dead loop:
the state machine re-enters the fixer loop with the same failing fixers, cycles forever,
and surfaces no user-visible error.

The correct transition on all-fixers-failed is an explicit blocked/error state:

```python
# Wrong: re-enters the loop; silent dead cycle
if all_fixers_failed:
    transition(State.CI_WAIT)

# Correct: stop and surface the failure
if all_fixers_failed:
    transition(State.BLOCKED, reason="all fixers raised exceptions")
```

Applies to any state machine with an auto-retry fixer pattern.

## `.gitignore` Does Not Mean Absent From Disk

A `.gitignore`-listed directory still exists on disk. Shell globs, Python `rglob()`,
`make install`, and similar tools do not know about `.gitignore` — they see everything.

Defense must be built into scripts themselves (skip lists, `SKILL.md` existence checks),
not delegated to `.gitignore` as the sole barrier.

```python
# Wrong: assumes gitignored dirs are invisible
for skill_dir in skills_root.iterdir():
    process(skill_dir / "SKILL.md")  # crashes on gitignored non-skill dirs

# Correct: check for SKILL.md existence; skip dirs without it
for skill_dir in skills_root.iterdir():
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        continue
    process(skill_md)
```

## Catching and Logging Exceptions in CI/Network Helpers

Network and subprocess helpers used in CI must catch specific exception types and log
each failure mode to `stderr`. Bare `except Exception` swallows distinct failure modes
(auth error, rate limit, network unreachable, JSON decode error) into a single silent
`None` return, making CI failures undiagnosable.

```python
# Wrong: all failure modes become silent None returns
def _fetch_state() -> str | None:
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("state")
    except Exception:
        return None  # auth error? rate limit? network down? impossible to tell

# Correct: each failure mode logged to stderr with its code/message
def _fetch_state() -> str | None:
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            print(f"[warn] rate-limited ({e.code}): {e}", file=sys.stderr)
        else:
            print(f"[warn] HTTP {e.code}: {e}", file=sys.stderr)
        return None
    except (urllib.error.URLError, OSError) as e:
        print(f"[warn] network error: {e}", file=sys.stderr)
        return None
    try:
        return json.loads(body).get("state")
    except json.JSONDecodeError:
        print(f"[warn] non-JSON response: {body[:200]!r}", file=sys.stderr)
        return None
```

Scope: any helper that calls external services (REST API, subprocess, file system) and
returns `None` on failure, especially in CI contexts where failures must be diagnosable.

This is distinct from "Exception Type Selection" (which describes what to *raise*); this
section covers what to *catch and log* in infrastructure helpers.

Source: PR #130, `_github_issue_state()` fix in commit `7326cf3`.

## Pylint Detects Cyclic Imports Through Deferred (Method-Body) Imports

Python runtime can avoid circular import errors by deferring `from .foo import Bar`
inside a method body — the import only executes at call time, not at module load time.
However, **pylint's static analysis builds a full import graph and detects the cycle
regardless** of whether the import is at the module level or inside a function.

```python
# models.py — deferred import inside a validator
class LessonRecord(BaseModel):
    @field_validator("insight")
    @classmethod
    def check_no_injection(cls, v: str) -> str:
        from .lessons_service import INJECTION_PATTERNS  # deferred — runtime OK
        ...

# lessons_service.py — imports from models at top level
from .models import LessonRecord  # top-level

# Result: pylint reports R0401 Cyclic import (lessons_service -> models)
# even though Python itself never raises ImportError at runtime.
```

**Fix:** move the shared constant to the module that actually uses it (the import
direction becomes one-way). In the example above, `INJECTION_PATTERNS` only needed
by `models.py` — move it there and remove the deferred import entirely.

```python
# models.py — no longer imports from lessons_service
_INJECTION_PATTERNS: list[re.Pattern[str]] = [...]  # defined here, used here

# lessons_service.py — one-way dependency, no cycle
from .models import LessonRecord  # still fine; models doesn't import back
```

The rule: **if a constant or helper is only used in module A, define it in module A**,
even if it was originally written alongside related logic in module B.
