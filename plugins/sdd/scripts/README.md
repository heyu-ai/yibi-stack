# plugins/sdd/scripts/

CLI tools shipped with the `sdd` plugin.

## check_spec_coverage.py

BDD Spec-Test Traceability Scanner (ADR-0008).

Scans `spec.md` files for `#### Scenario: <slug>` headings and
test files for `spec: <cap>#<slug>` docstring traces,
then reports coverage status.

### Quick start

```bash
# Scan a specific change (recommended during development)
uv run python plugins/sdd/scripts/check_spec_coverage.py \
    --specs-dir openspec/changes/<name>/specs \
    --tests-dir tests/ \
    --cap <feature-name>

# Full scan with CI gate (exit 1 on missing or orphan)
uv run python plugins/sdd/scripts/check_spec_coverage.py \
    --specs-dir openspec/changes/<name>/specs \
    --tests-dir tests/ \
    --exit-on-missing
```

### All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--specs-dir` | auto-detect | Directory containing `spec.md` files |
| `--tests-dir` | auto-detect | Directory containing `test_*.py` files |
| `--cap` | all | Limit scan to one capability (direct parent dir of `spec.md`) |
| `--exit-on-missing` | false | Exit 1 if any Scenarios are missing or orphaned |
| `--spec-root` | — | Legacy alias for `--specs-dir` (yibi-mvp compat) |
| `--test-root` | — | Legacy alias for `--tests-dir` (yibi-mvp compat) |

### Output

```text
Spec-Test Coverage Report (cap=login)
==================================================
  [OK]   login#require-current-password
  [WARN] missing: login#require-new-password-confirmation
  [WARN] orphan:  login#old-slug-that-no-longer-exists

Summary: 1/2 covered, 1 missing, 1 orphan
```

| Prefix | Meaning |
|--------|---------|
| `[OK]` | Scenario has a matching `spec: <cap>#<slug>` docstring |
| `[WARN] missing:` | Scenario exists in spec but no test trace found |
| `[WARN] orphan:` | Test docstring references a non-existent Scenario slug |
| `[ERROR]` | Duplicate slug in spec (fatal, exit 1) |
| `[FAIL]` | Configuration error (bad paths, etc.) |

### Scenario slug format (in spec files)

```markdown
#### Scenario: require-current-password -- 必須提供當前密碼
```

See `plugins/sdd/skills/spectra-amplifier/bdd-trace-convention.md` for full spec.

### Test docstring format (in pytest files)

```python
def test_password_change_requires_current_password() -> None:
    """
    spec: account-settings-page#require-current-password
    """
```

## check_testplan_trace.py

Bidirectional trace check between a change's `testplan.md` and the tests
(openspec change `enforce-testplan-trace`). `check_spec_coverage.py` verifies
"Gherkin scenario ↔ test"; this script verifies "testplan TC ↔ test". They
complement each other; neither replaces the other.

A test declares the TCs it implements on a `tc:` docstring line, next to `spec:`:

```python
def test_empty_password_rejected() -> None:
    """
    spec: login#require-password
    tc: LOGIN-VL-001
    """
```

For Python, only a docstring line that **starts with** `tc:` binds. TC-IDs in test
data, ordinary comments, or docstring prose never count.

Vitest uses direct callback comments, parsed with the TypeScript compiler AST:

```tsx
import { it } from "vitest";

it.each(["playing", "paused"])("closes %s", (state) => {
  // spec: player#close-player
  // tc: PLAYER-VL-001
  expect(closePlayer(state)).toEqual({ playing: false, visible: false });
});
```

The checker recognizes inline `it`/`test` callbacks, including `each` factories
and tagged tables, nested `describe`, and Vitest named-import aliases or namespaces.
Only comments between the callback's direct statements bind; strings, JSX, fixture
objects, suite comments, nested helpers, locally shadowed names, skipped/todo tests
and skipped suites do not. Indirect callbacks, dynamic aliases and `skipIf`/`runIf`
are not inferred and cannot establish coverage. Test source is never executed.

Literal options objects are inspected in either supported argument position:
`skip`/`todo` must be absent or explicitly `false`. Options variables, spreads,
computed unknown keys, and unresolved flag values cannot establish coverage.
A literal numeric timeout after the callback is supported.

Vitest scanning requires Node.js 18+ and a TypeScript compiler installed in the
target test package, or the pinned compiler shipped as the SDD package dependency.
The target compiler is used only when its required AST APIs are available; an
incompatible version (such as TypeScript 4.8) falls back to the pinned compiler.
If neither is usable, the diagnostic reports an unavailable/incompatible compiler.
Install the fallback in a source checkout with
`npm ci --ignore-scripts --prefix plugins/sdd`; for an installed plugin, use its
SDD install directory as the prefix. Python-only scans do not require Node.
Missing Node/compiler, invalid syntax, and helper failures exit **2**, not a
fabricated empty binding list or a successful check.

### Quick start

```bash
# During development: every active change, non-strict
# (legacy testplans and unfinished changes only produce WARN)
uv run python plugins/sdd/scripts/check_testplan_trace.py

# Before archiving: one change, strict
uv run python plugins/sdd/scripts/check_testplan_trace.py --strict --change <name>

# Current state: which tests each TC is bound to (stdout only, changes no file)
uv run python plugins/sdd/scripts/check_testplan_trace.py --report
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--repo-root` | git toplevel of cwd | Repository root |
| `--openspec-dir` | `openspec` | OpenSpec directory relative to the repo root (e.g. `docs/openspec`) |
| `--change` | all active changes | Check/report one change, retaining all active/archive TC ownership; an unknown name exits 2 |
| `--tests-dir` | repo root | Repeatable; scans `test_*.py`, `*_test.py`, and `*.test.*`/`*.spec.*` with js/jsx/ts/tsx extensions |
| `--strict` | false | Treat every enforced finding as FAIL and require all Manual Verification items checked |
| `--report` | false | Print the TC-to-test-nodeid table; always exits 0 unless configuration is invalid |
| `--summary` | false | Print every FAIL line, but collapse WARNs into one line per change with per-kind counts (used by the pre-commit hook) |

### Findings

| kind | Condition |
|------|-----------|
| `missing` | An `auto` TC has no test bound to it with `tc:` |
| `orphan` | A `tc:` line cites an ID no testplan defines (e.g. the prefix was renamed during implementation) |
| `mismatch` | A bound test's `spec:` slug is not one the Coverage table maps to that TC, or the test has no `spec:` line |
| `collision` | The same TC-ID is also defined in another active or archived testplan |
| `manual-open` | Under `--strict`, a Manual Verification item is still unchecked |
| `unparsable` | A legacy testplan has no parsable TC table (WARN only) |

Severity: only a testplan that declares `trace: enforced` **and** has a `Kind`
column escalates to FAIL, and only under `--strict` or when its tasks.md has at
least one checkbox and every checkbox is checked. Everything else is WARN.

Exit codes: `0` no FAIL; `1` at least one FAIL; `2` configuration error (repo root
missing, unknown `--change`, enforced testplan without a parsable TC table).

Selected-change scans do not report known IDs from other active/archive plans as
orphans. A genuinely undefined ID owned only by the selected change still fails;
one definitively owned by another active change is outside the selected report.
Unknown or ambiguous ownership remains an explicit WARN. If an ownership
testplan cannot be parsed, `ownership-unparsed` warns instead of treating it as
proof of absence; uncertain orphan ownership is not silently discarded.

### Wiring a host project (manual)

Installing the sdd plugin ships the checker, not the wiring. Add to the host
project's `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: check-testplan-trace
      name: check-testplan-trace
      entry: python3 <sdd-plugin-installPath>/scripts/check_testplan_trace.py --summary --openspec-dir openspec
      language: system
      pass_filenames: false
      files: (^|/)(testplan\.md|tasks\.md|test_[^/]*\.py|[^/]*_test\.py|[^/]*\.(test|spec)\.(js|jsx|ts|tsx))$
      verbose: true
```

Take `<sdd-plugin-installPath>` from the `installPath` of `sdd@yibi-stack` in
`~/.claude/plugins/installed_plugins.json`; adjust `--openspec-dir` when openspec is
not at the repo root. Python and Vitest JS/TS are supported; other frameworks
(e.g. Flutter/Dart) are not parsed and must not use this checker as their
`trace: enforced` evidence.

## Origin (check_spec_coverage.py)

Vendored from `heyu-ai/yibi-mvp` (`backend/scripts/check_spec_coverage.py`)
per yibi-mvp ADR-0008. Parametrized with `--specs-dir` / `--tests-dir`
for use in host projects outside the yibi-mvp layout.
