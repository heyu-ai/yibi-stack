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

## Pathlib Semantics

`Path.with_suffix(ext)` **replaces** the last extension — it does not append:

```python
# Trap: with_suffix replaces .json; settings.json.tmp only works by coincidence
tmp = SETTINGS_PATH.with_suffix(".json.tmp")   # settings.json -> settings.json.tmp

# Correct: explicitly name the file
tmp = SETTINGS_PATH.with_name("settings.json.tmp")  # intent is clear
```

For `.tmp` scratch files, always use `with_name(stem + ".tmp")` or `with_name("filename.tmp")`.
