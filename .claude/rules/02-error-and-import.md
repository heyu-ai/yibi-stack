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

## Pathlib `rglob()` Does Not Follow Symlinks

`pathlib.Path.rglob()` does not traverse into symlink subdirectories by default.
If the target directory contains symlinks (e.g., plugin symlinks under `skills/`),
use `os.walk(followlinks=True)` or Python 3.13+ `glob(follow_symlinks=True)` instead.

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
