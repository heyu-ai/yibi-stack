# Plugin Test Convention (Self-Contained)

This file ships with the `sdd` plugin so that `spectra-amplifier` works correctly
in host projects that do not have their own test-convention rules.

## TC-ID Format

```text
[FEATURE]-[CATEGORY]-[NUMBER]   e.g. LOGIN-VL-001
```

## Category Abbreviations

| Code | Name | Scope | Description |
|------|------|-------|-------------|
| VL | Validation | unit | Input format / boundary / required-field checks |
| DT | Decision Table | unit | Multi-condition branch coverage |
| ST | Service Test | integration | Cross-component integration flow |
| EG | Edge Case | unit or integration | Boundary, error path, concurrency |
| CV | Conversion | unit | Data format transformation |
| SMK | Smoke Test | end-to-end | Step 5 quick sanity scenarios only |
| PERF | Performance | integration | SLA verification |
| SEC | Security | integration | Auth, authz, injection vectors |

> **ST disambiguation**: in this plugin, `ST` = Service Test (cross-component).
> In qa-test-design's technique list, `ST` = State Transition (a test technique).
> Context distinguishes them: TC-ID prefix (`ST`) vs. qa-test-design technique label.
> Smoke Tests use `SMK` exclusively to eliminate any ambiguity.

## Test Type Mapping

| TC-ID code | Test type | Typical location |
|-----------|-----------|-----------------|
| VL, DT, CV | unit | `tests/unit/` |
| ST, PERF, SEC | integration | `tests/integration/` |
| EG | depends on scope | either |
| SMK | end-to-end | `tests/e2e/` or CI smoke suite |

## Install-time Behaviour

When `spectra-amplifier` runs in a host project, it checks in order:

1. `.claude/rules/09-test-conventions.md` exists → **use host convention**,
   log `[OK] Using host test convention from .claude/rules/09-test-conventions.md`
2. Not found → use this plugin default, log
   `[OK] Using sdd plugin default test convention`
3. **Never overwrite** host convention files silently

## Sequence Numbers

- Start at `001` per `[FEATURE]-[CATEGORY]` combination
- Reset per feature, not globally
- Example: `LOGIN-VL-001`, `LOGIN-VL-002`, `PROFILE-VL-001`
