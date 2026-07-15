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

## A Compatibility Test's Fixture Must Run in the Environment It Claims to Cover

A test that claims "this works on old tool version X" is worthless if its **setup** requires a
newer version than X: on the very environment it targets, the fixture dies first and the assertion
never runs. It passes on the developer's modern machine, so nothing looks wrong.

```python
# Wrong: the test exists to prove the script works on git < 2.31,
# but `git init -b` needs git 2.28 -- on a real old git the fixture fails, not the script
_run(["git", "init", "-q", "-b", "main", str(root)])

# Correct: build the fixture with primitives the target environment has
_run(["git", "init", "-q", str(root)])
_run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])
```

Rule: when a test's purpose is compatibility with an old//minimal environment, audit **every**
call in its fixture against that environment's floor — not just the code under test. Ask "if I ran
this whole test on the oldest supported toolchain, what is the first line that breaks?"

This is a distinct species from the fake test below: the assertions here are sound and the
production code is genuinely covered — on modern tooling. What is missing is coverage of the one
environment the test was written for. (Source: PR #234 — the guard's old-git regression test built
its repo with `git init -b main`.)

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

## Linter Suppression Tracking

When adding any linter suppression, **open a tracking issue in the same PR**. Without it,
suppressions accumulate and are never removed.

Applies to all suppression forms:

| Type | Example |
|------|---------|
| markdownlint inline | `<!-- markdownlint-disable MD013 -->` |
| markdownlint config | `.markdownlint.yaml` rule set to `false` |
| ruff | `# noqa: E501` |
| bandit | `# nosec B603` |
| mypy | `# type: ignore` |
| pre-commit | new `exclude:` pattern |

### Required fields in the tracking issue

- **Rule/warning name** being suppressed
- **Reason**: technical limitation / external dependency / temporary workaround
- **Removal condition**: "remove after X is fixed" — without this the suppression can never be tracked to closure

Incident (PR #5): 6 markdownlint rules suppressed at once with no tracking issue;
nearly became permanent until a follow-up commit re-enabled them all.

## Bug-Monitoring Tests Must Have Three Explicit Outcomes

When a test monitors for an upstream bug's continued existence, three outcomes are required:

1. **pass** — bug is still present (expected state; monitoring is working)
2. **fail** — bug is fixed, removal condition met (the desired detection signal)
3. **skip** — tool unavailable or exit was inconclusive (not a verdict)

Without the skip branch: if the monitored CLI exits non-zero due to auth failure or startup
crash (not the expected error), the test silently "passes" as "bug still present" — giving
false confidence that monitoring is working when it is not.

```python
def _assert_bug_still_present(self, command: str, pattern_id: str) -> None:
    result = _run_cli(command)
    combined = result.stdout + result.stderr
    error_present = "Expected error text" in combined

    # inconclusive: non-zero exit but target error not in output
    if result.returncode != 0 and not error_present:
        pytest.skip(f"CLI exited {result.returncode} without expected error for {pattern_id} "
                    f"— possible auth/startup failure; cannot verify bug status")

    bug_fixed = result.returncode == 0 and not error_present
    if bug_fixed:
        pytest.fail(f"REMOVAL CONDITION MET for {pattern_id}: bug appears fixed")
```

Source: PR #130 regression test for anthropics/claude-code#56018.

## Bug Repro Constants Must Trigger the Complete Pattern

A repro constant that does not actually trigger the target bug is worse than no repro:
it creates false confidence that the monitoring suite is working.

```python
# Wrong: missing outer $() — does NOT trigger reverse-nested subshell parser bug
D4_REPRO = 'dirname "$(git rev-parse --git-dir)"'

# Correct: outer $() is what makes the parser see a nested subshell
D4_REPRO = 'MAIN=$(dirname "$(git rev-parse --git-dir)")'
```

Rule: after writing a repro constant, verify it triggers the target bug in isolation
before adding it to a monitoring test suite.

This is distinct from "Test Fixture Schema Must Match Real Tool Schema" (fixture schema
ensures mock data structure accuracy; repro completeness ensures the repro actually exercises
the target code path).

Source: PR #130, D4_REPRO fix in commit `7326cf3`.
