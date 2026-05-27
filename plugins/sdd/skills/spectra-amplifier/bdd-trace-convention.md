# BDD Spec-Test Trace Convention

This file documents the traceability convention used by `spectra-amplifier` to link
Gherkin Scenarios in spec files to pytest test functions.

Convention source: yibi-mvp ADR-0008 (BDD Spec-Test Traceability — docstring trace 機制,
2026-05-19). Adapted for plugin distribution; no third-party dependency added.

---

## Scenario Anchor Slug (in spec files)

Every `#### Scenario:` heading **MUST** carry an explicit slug:

```markdown
#### Scenario: <slug> -- <可讀標題>
```

### Slug Rules

| Rule | Detail | Example |
|------|--------|---------|
| Format | kebab-case, lowercase | `require-current-password` |
| Length | < 50 characters | — |
| Naming | Explicit (do not auto-derive from title) | — |
| CJK / digit start | Use English slug; keep CJK in title after `--` | `#### Scenario: age-4-story-gen -- 4 歲孩子生成故事` |
| Uniqueness | Must be unique within one spec.md | Scanner exits 1 on duplicate |

> Quoting ADR-0008 Consequences:
> "若 Scenario 改名，docstring 引用需同步更新"
> — changing a slug after tests exist requires updating all matching `spec: <cap>#<slug>` lines.

---

## Pytest Docstring Trace (in test files)

```python
def test_password_change_requires_current_password() -> None:
    """
    spec: account-settings-page#require-current-password
    """
```

### Docstring Format Rules

| Field | Rule | Example |
|-------|------|---------|
| Keyword | `spec:` at start of the first docstring line | `spec:` |
| `<cap>` | Direct parent directory name of `spec.md`; scanner lowercases it | `account-settings-page`, `e02-child-profile` |
| `<slug>` | Matches the slug in the spec heading exactly | `require-current-password` |
| Prefix | No `scenario-` prefix | correct: `spec: login#require-password` |

### Cap Naming

- Cap = **direct parent directory** of `spec.md`, not the grandparent
- Spec files must be named exactly `spec.md`; the cap is the containing directory
- Example: `docs/openspec/changes/my-feature/specs/login/spec.md` → cap = `login`
- Nested: `docs/openspec/specs/E12-device/F015-sleep/spec.md` → cap = `F015-sleep`

---

## Traceability Matrix (in testplan.md / proposal.md)

`spectra-amplifier` Step 5 generates a Traceability table:

```markdown
| US | Scenario slug | TC-ID | pytest trace |
|----|--------------|-------|-------------|
| US-001 | require-current-password | LOGIN-VL-001 | spec: login#require-current-password |
```

---

## Scanner

Use `check_spec_coverage.py` to verify coverage:

```bash
# Limit to one spec directory (recommended during development)
uv run python plugins/sdd/scripts/check_spec_coverage.py \
  --specs-dir openspec/changes/<name>/specs \
  --tests-dir tests/ \
  --cap <feature-name>

# Full scan (use when coverage is mostly complete)
uv run python plugins/sdd/scripts/check_spec_coverage.py \
  --specs-dir openspec/changes/<name>/specs \
  --tests-dir tests/
```

See `plugins/sdd/scripts/README.md` for full usage.

### Scanner Output Semantics

| Prefix | Meaning |
|--------|---------|
| `[OK]` | Scenario has a matching `spec: <cap>#<slug>` docstring |
| `[WARN] missing:` | Scenario exists in spec but no test trace found |
| `[WARN] orphan:` | Test docstring references non-existent Scenario slug |
| `[ERROR]` | Duplicate slug in spec (fatal; exit 1) |
| `[FAIL]` | Configuration error (bad paths, etc.) |

---

## Migration from Legacy ST-NNN Smoke Tests

Specs written before this convention may use `**ST-001:**` for Smoke Tests.
These are valid legacy format. For new specs:

- Use `#### Scenario: <slug> -- <title>` (BDD heading format)
- Use `SMK-NNN` for Smoke Test TC-IDs in `testplan.md`
- Do not rename existing `ST-NNN` entries in active specs (creates orphan traces)
