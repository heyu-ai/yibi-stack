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

### Origin

Vendored from `heyu-ai/yibi-mvp` (`backend/scripts/check_spec_coverage.py`)
per yibi-mvp ADR-0008. Parametrized with `--specs-dir` / `--tests-dir`
for use in host projects outside the yibi-mvp layout.
