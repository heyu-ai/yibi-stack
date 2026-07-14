"""Tests for plugins/pr-flow/skills/pr-cycle-deep/scripts/amplifier-verify.py.

Locks the TC-ID parser so it accepts BOTH testplan conventions:
  3-part  PREFIX-CATEGORY-NUMBER  (YIBI-NFC-001, FBAUTH-UNIT-01)
  2-part  PREFIX-CAT+NUMBER       (FBAUTH-U01, FBAUTH-I12, SMK-001)

Regression: a 2-part testplan (e.g. change 0032's FBAUTH-U01) previously made
parse_tc_table return zero rows, so amplifier-verify exited 2 with a spurious
"no TC table" against a perfectly valid testplan.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "amplifier-verify.py"
_spec = importlib.util.spec_from_file_location("amplifier_verify", _SCRIPT)
amplifier_verify = importlib.util.module_from_spec(_spec)
# Register before exec so the module's @dataclass decorators can resolve
# sys.modules[cls.__module__] during class creation.
sys.modules["amplifier_verify"] = amplifier_verify
_spec.loader.exec_module(amplifier_verify)


def test_tc_id_regex_accepts_two_part_ids():
    rx = amplifier_verify._TC_ID_RE
    for tc in ("FBAUTH-U01", "FBAUTH-I12", "FBAUTH-W04", "SMK-001"):
        m = rx.search(tc)
        assert m is not None and m.group(0) == tc, tc


def test_tc_id_regex_still_accepts_three_part_ids():
    rx = amplifier_verify._TC_ID_RE
    for tc in ("YIBI-NFC-001", "FBAUTH-UNIT-01"):
        m = rx.search(tc)
        assert m is not None and m.group(0) == tc, tc


def test_parse_tc_table_two_part_ids():
    testplan = """\
## 1. TC Table

| TC-ID | Scenario Slug | Test Purpose |
|-------|--------------|-------------|
| FBAUTH-U01 | exchange-valid | verify claims |
| FBAUTH-I12 | lazy-backfill | backfill row |
| SMK-001 | smk-happy-path | endpoint alive |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["FBAUTH-U01", "FBAUTH-I12", "SMK-001"]
    assert rows[0].slug == "exchange-valid"


def test_parse_tc_table_three_part_ids():
    testplan = """\
## 1. TC Table

| TC-ID | Scenario Slug | Test Purpose |
|-------|--------------|-------------|
| YIBI-NFC-001 | bind-device | bind |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["YIBI-NFC-001"]


# ---------------------------------------------------------------------------
# Multi-table testplans, slug column position, and the empty-slug interaction.
#
# Regression: parse_tc_table() used to `break` after the FIRST TC table and read
# the slug from a hardcoded cells[1]. Real testplans group TCs into one table per
# requirement area and put the slug column wherever they like. Measured across every
# testplan.md in a downstream consumer repo: the slug column appears at index 0, 1,
# 3, 5, 6, or not at all, and the single most common TC-table shape (the
# `sdd:qa-test-designer` output) has NO slug column. Consequences before the fix, on
# two real plans: 3 of 101 TCs parsed, and 16 of 57 — while the gate reported [OK]
# and exit 0 both times. A silent no-op, not a loud failure.
# ---------------------------------------------------------------------------


def test_parse_tc_table_reads_every_table_not_just_the_first():
    """A testplan with one TC table per requirement area must be fully parsed."""
    testplan = """\
## Test Cases

### 1. Pairing

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | code accepted | pairing-code-valid |

### 2. Unbind

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-002 | token revoked | unbind-revokes-auth |

### 3. Greeting

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-ST-003 | greeting plays once | greeting-first-activation |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001", "ACME-EP-002", "ACME-ST-003"]
    assert rows[1].slug == "unbind-revokes-auth"


def test_parse_tc_table_finds_slug_column_by_header_not_by_index():
    """Slug lives in the last column here; cells[1] would wrongly yield 'Test Purpose'."""
    testplan = """\
| TC-ID | Test Purpose | Technique | Risk | Test Data | Expected | Scenario Slug |
|-------|-------------|-----------|------|-----------|----------|---------------|
| ACME-EP-001 | valid profile | EP | P0 | name ok | 201 | submit-valid-basic-profile |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert len(rows) == 1
    assert rows[0].slug == "submit-valid-basic-profile"
    assert rows[0].slug != "valid profile"


def test_parse_tc_table_slug_empty_when_no_slug_column():
    """The most common real shape (qa-test-designer output) has no slug column."""
    testplan = """\
| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Test Data | Expected Result |
|-------|-------------|-----------|------|--------------|-------|-----------|-----------------|
| SMK-001 | endpoint alive | EP | P0 | deployed | GET /health | n/a | 200 |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["SMK-001"]
    # Must be empty, NOT the "Test Purpose" text that a hardcoded cells[1] would grab.
    assert rows[0].slug == ""


def test_parse_tc_table_skips_coverage_table():
    """Coverage tables carry a TC-ID column too; they must not be read as TC rows.

    The coverage table below cites ACME-ST-002, a TC that is planned but not yet in
    any TC table (a normal state: Coverage Analysis is where gaps get recorded).
    Without the explicit skip it would be counted as a real TC, inflating total_tcs
    and inventing a TC the plan does not define. Note the TC-ID must differ from the
    TC table's, or de-duplication alone would mask the bug.
    """
    testplan = """\
## Test Cases

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | code accepted | pairing-code-valid |

## Coverage Analysis

| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| pairing-code-valid | covered | ACME-EP-001 | - |
| deferred-scenario | missing | ACME-ST-002 | blocked on telemetry |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001"]
    assert "ACME-ST-002" not in [r.tc_id for r in rows]


def test_parse_tc_table_dedupes_repeated_tc_ids():
    testplan = """\
| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | first | pairing-code-valid |

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | restated | pairing-code-valid |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001"]


def test_empty_slug_does_not_flag_every_test_function():
    """An empty slug must not act as a match-anything wildcard in Check 2.

    A TC table with no Scenario Slug column yields slug == "", and `"" in name_lower`
    is vacuously True. Without the `s and ...` guard, every untraced test function in
    the PR becomes a MUST finding and the merge is blocked on nothing.
    """
    tc_rows = [amplifier_verify.TCRow(tc_id="SMK-001", slug="", raw_line="")]
    test_functions = [
        amplifier_verify.TestFunction(
            name="test_totally_unrelated_thing",
            docstring="no trace here",
            filepath="tests/test_x.py",
            spec_trace=None,
        )
    ]
    findings = amplifier_verify.analyze(tc_rows, [], test_functions)
    assert findings.must == []


def test_empty_slug_does_not_shadow_a_real_slug_match():
    """An empty slug must not suppress a genuine slug match (false negative).

    Check 2 used `next(s for s in slugs if s.replace(...) in name)`. Because ""
    satisfies that condition unconditionally, it could be returned ahead of a real
    slug — and being falsy, it then suppressed the MUST finding the real slug should
    have raised. Set iteration over strings is hash-randomised, so the suppression
    was non-deterministic. `any(s and ...)` makes it order-independent.
    """
    tc_rows = [
        amplifier_verify.TCRow(tc_id="SMK-001", slug="", raw_line=""),
        amplifier_verify.TCRow(tc_id="ACME-EP-001", slug="pairing-code-valid", raw_line=""),
    ]
    test_functions = [
        amplifier_verify.TestFunction(
            name="test_pairing_code_valid",
            docstring="no spec trace here",
            filepath="tests/test_pairing.py",
            spec_trace=None,
        )
    ]
    findings = amplifier_verify.analyze(tc_rows, [], test_functions)
    assert len(findings.must) == 1
    assert "test_pairing_code_valid" in findings.must[0]


# ---------------------------------------------------------------------------
# detect_change_from_diff — a spectra change must come from a diff FILE HEADER,
# not from prose that merely mentions an openspec/changes/<...>/ path.
#
# Regression: a spectra-INIT PR vendors generated skill docs whose example paths
# read `openspec/changes/<name>/proposal.md`. The old whole-text regex captured
# the literal `<name>` placeholder as a change slug, so amplifier-verify exited 2
# with "testplan.md not found for change '<name>'" on a PR that has no change at all.
# ---------------------------------------------------------------------------


def test_detect_change_from_real_diff_header():
    diff = """\
diff --git a/openspec/changes/add-login/testplan.md b/openspec/changes/add-login/testplan.md
new file mode 100644
--- /dev/null
+++ b/openspec/changes/add-login/testplan.md
@@ -0,0 +1,2 @@
+# testplan
"""
    assert amplifier_verify.detect_change_from_diff(diff) == "add-login"


def test_detect_change_from_docs_openspec_layout_header():
    diff = """\
diff --git a/docs/openspec/changes/auth/proposal.md b/docs/openspec/changes/auth/proposal.md
--- a/docs/openspec/changes/auth/proposal.md
+++ b/docs/openspec/changes/auth/proposal.md
@@ -1 +1 @@
-old
+new
"""
    assert amplifier_verify.detect_change_from_diff(diff) == "auth"


def test_detect_change_ignores_placeholder_in_generated_docs():
    # Mimics a spectra-init PR: added content mentions the <name> placeholder path,
    # but no file under openspec/changes/<slug>/ is actually added or edited.
    diff = """\
diff --git a/.claude/skills/spectra-commit/SKILL.md b/.claude/skills/spectra-commit/SKILL.md
new file mode 100644
--- /dev/null
+++ b/.claude/skills/spectra-commit/SKILL.md
@@ -0,0 +1,2 @@
+   Filter files under `docs/openspec/changes/<name>/`. These are the change's files.
+   - M  openspec/changes/<name>/proposal.md
"""
    assert amplifier_verify.detect_change_from_diff(diff) == ""


def test_detect_change_ignores_valid_slug_in_content_line():
    # A *valid* slug that appears ONLY in a content line (single `+`), never in a
    # file header. This isolates the header-line restriction: slug validation alone
    # would accept "add-login", so this test fails if the header filter is dropped
    # (or against the old whole-text regex, which returns "add-login").
    diff = """\
diff --git a/.claude/skills/spectra-ask/SKILL.md b/.claude/skills/spectra-ask/SKILL.md
--- a/.claude/skills/spectra-ask/SKILL.md
+++ b/.claude/skills/spectra-ask/SKILL.md
@@ -1 +1,2 @@
 existing
+  See `openspec/changes/add-login/proposal.md` for the worked example.
"""
    assert amplifier_verify.detect_change_from_diff(diff) == ""


def test_detect_change_returns_empty_when_no_spectra_path():
    diff = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""
    assert amplifier_verify.detect_change_from_diff(diff) == ""
