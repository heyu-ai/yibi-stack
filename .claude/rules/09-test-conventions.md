---
globs: tasks/**/tests/**
---
# Test Conventions

## Naming Conventions

```text
tasks/<module>/tests/
├── __init__.py
├── test_models.py
├── test_service.py
├── test_cli.py
└── test_parsers.py    # if parsers/ exists
```

Class naming: `class TestXxx:` (no inheritance)
Method naming: `test_<scenario>` or with structured ID: `test_gbill_dt_001_cathay_cc_parser`

## Structured Test IDs

Mark the ID in the docstring, format: `<MODULE>-<CATEGORY>-<NUMBER>`

| Abbrev | Purpose |
|--------|---------|
| DT | Decision Table (branch coverage) |
| ST | Service Test (integration flow) |
| EG | Edge Case |
| CV | Conversion (format conversion) |
| VL | Validation |

```python
def test_gscan_dt_001_scan_days_controls_after_date(self) -> None:
    """GSCAN-DT-001: scan_days 控制 after_date 計算"""
    ...
```

## Helper Factory Functions

Use module-level helper functions to build test data; do not use conftest.py:

```python
def make_scan_profile(**kwargs: object) -> ScanProfile:
    defaults = {"name": "test", "labels": ["INBOX"], "scan_days": 7}
    return ScanProfile(**{**defaults, **kwargs})

class TestScanProfile:
    def test_default_values(self) -> None:
        profile = make_scan_profile()
        assert profile.scan_days == 7
```

## Mocking

```python
SCAN_SVC = "tasks.gmail_scan.service"

class TestRunScan:
    @patch(f"{SCAN_SVC}.build_gmail_service")
    def test_builds_service(self, mock_build: MagicMock) -> None:
        ...
```

## Resource Handling

- SQLite: pass `":memory:"`
- Filesystem: use the pytest built-in `tmp_path` fixture
- Do not create conftest.py or custom pytest fixtures

## Import Syntax

Always use absolute-path imports in tests:

```python
from tasks.gmail_scan.models import ScanProfile
from tasks.gmail_scan.service import run_scan
```

## Test Fixture Schema Must Match the Real Tool Schema

The fixture's data structure must match the **real** schema of the tool under test; do not invent fields.
Passing tests only verify "logic runs on test data", not "logic works in production."

Counter-example (PR #20 hooks.py): fixture used `{"run": ".sh"}` but the real Claude Code schema is
`{"hooks": [{"type": "command", "command": ".sh"}]}` — 59 tests passed, but ghost hook detection was
permanently broken in production, only discovered when mob review compared against the real
`.claude/settings.json`.

Fix: read the tool's real schema documentation before writing fixtures, or compare against a real
config file (e.g. `.claude/settings.json`).

## Assertion Semantic Precision

Avoid overly broad substring matches when verifying findings/output — if the target string appears
in multiple valid paths, the assertion loses its protection and a broken fallback silently passes.

```python
# Wrong: ".claude/skills/" also contains "skills/", so fallback failure still passes
assert any("skills/" in f for f in result.findings)

# Correct: use a semantically unique string to lock in the expected branch
assert any("源碼 repo 模式" in f for f in result.findings)
```

Applies to: any assertion that verifies which logical branch was taken.

## Bandit `# nosec` Usage Conventions

Do not blindly add `# nosec` in tests; the following two scenarios are legitimate exceptions:

### B112 (try_except_continue) — skip malformed lines in stream parsing

```python
try:
    obj = json.loads(raw)
except Exception:  # nosec B112
    continue
```

Applies when: parsing JSONL / log files line by line; malformed lines should be skipped rather than
aborting the whole parse. The `continue` is intentional, not an oversight.

### F841 (unused variable) — delete both lines; do not use `# noqa`

ruff F841 "local variable assigned but never used" requires **deleting both the assignment line and
the initialization line**; deleting only one leaves the other still triggering.

```python
# Wrong: deleted the loop assignment but kept the function-level initialization
prev_output_tokens = 0      # <-- delete this line too
...
# prev_output_tokens = last_output_tokens  # deleted, but the line above is still F841

# Correct: delete both lines
```
