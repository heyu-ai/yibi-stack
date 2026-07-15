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


def test_coverage_table_is_not_read_as_tc_definitions():
    """A coverage table carries a TC-ID column but defines nothing.

    "Coverage table" is decided structurally and identically by both parsers via
    `_coverage_cols` — has a slug column AND an exactly-`Status` column. Measured over
    an 18-plan corpus: 5 tables carry ID + slug + Status and all 5 are genuine
    coverage tables, so this excludes them with zero false negatives.

    Reading them as TC definitions is not merely a wrong count: their slugs feed
    Check 2, which BLOCKS, so a scenario listed as `missing` could manufacture a MUST
    finding against a test that legitimately has no TC yet.
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
    # Only the real definition; ACME-ST-002 exists solely in the coverage table.
    assert [r.tc_id for r in rows] == ["ACME-EP-001"]
    assert rows[0].slug == "pairing-code-valid"
    # ...and the coverage parser owns the coverage table.
    cov = amplifier_verify.parse_coverage_table(testplan)
    assert [(c.slug, c.status) for c in cov] == [
        ("pairing-code-valid", "covered"),
        ("deferred-scenario", "missing"),
    ]


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


# ---------------------------------------------------------------------------
# Table discrimination by COLUMN SCHEMA, not header shape.
#
# A TC-ID column alone does not make a table authoritative. Measured across every
# testplan.md in a downstream consumer repo: requiring one canonical TC-definition
# column keeps 66 tables and rejects 23, and all 23 are genuinely summary / trace /
# coverage tables. The fixtures below are real observed header shapes, not invented.
# ---------------------------------------------------------------------------


def test_tc_table_with_a_status_column_is_not_mistaken_for_a_coverage_table():
    """Regression: the coverage-skip regex `.*Status` is unanchored.

    Coupling parse_tc_table to _COVERAGE_TABLE_HEADER_RE made any TC table carrying
    both a Scenario Slug column and an "Expected Status Code" column vanish entirely
    — the same silent-drop class the multi-table fix exists to remove, reintroduced.
    Discriminating by column schema removes the coupling instead of tightening it.
    """
    testplan = """\
| TC-ID | Test Purpose | Scenario Slug | Expected Status Code |
|-------|-------------|---------------|----------------------|
| ACME-EP-001 | valid pairing | pairing-code-valid | 201 |
| ACME-EP-002 | expired code | pairing-code-expired | 410 |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001", "ACME-EP-002"]
    assert rows[0].slug == "pairing-code-valid"


def test_no_tc_table_vanishes_because_of_its_header_vocabulary():
    """No table may be dropped for not using an expected header word.

    Regression for the second attempt at table discrimination: requiring a keyword-y
    "TC-definition" column (test purpose / expected / steps / ...) silently dropped
    every table below. That is the same silent-blindness class as the `break` this PR
    set out to remove, re-spelled -- and a mixed plan (one keyword table + one of
    these) parsed a fraction and still printed [OK].

    A table is a TC table if it has an ID column. Full stop.
    """
    for header, row in [
        ("| TC-ID | Scenario Slug | Assertion |", "| ACME-EP-001 | s | asserts x |"),
        ("| TC-ID | What it checks | Result |", "| ACME-EP-001 | checks x | ok |"),
        ("| TC-ID | Case | Outcome |", "| ACME-EP-001 | c | o |"),
        ("| TC-ID | 測項 | 結果 |", "| ACME-EP-001 | m | r |"),
        ("| TC-ID | Scenario Slug | Given | When | Then |", "| ACME-EP-001 | s | g | w | t |"),
    ]:
        testplan = f"{header}\n|---|---|---|---|---|\n{row}\n"
        rows = amplifier_verify.parse_tc_table(testplan)
        assert [r.tc_id for r in rows] == ["ACME-EP-001"], f"vanished: {header}"


def test_id_column_regex_does_not_match_words_ending_in_id():
    """`[A-Z]{2,}[-_ ]?ID` also matched VALID / GRID / UUID / RAPID / Invalid.

    A table headed `| Valid | TC-ID | ... |` then resolved its ID column to column 0,
    read "yes" as the TC-ID, matched nothing, and the whole table vanished — silently,
    and invisibly to reconcile, which skips tables the parser did enter. Same
    silent-under-report class as the bug this PR exists to fix, fourth spelling.
    """
    for header in ("VALID", "GRID", "UUID", "RAPID", "Invalid", "ID"):
        assert not amplifier_verify._TC_ID_COL_RE.match(header), header
    for header in ("TC-ID", "SMK-ID", "TC_ID", "TC ID", "Device ID"):
        assert amplifier_verify._TC_ID_COL_RE.match(header), header

    testplan = """\
| Valid | TC-ID | Test Purpose |
|-------|-------|--------------|
| yes | ACME-EP-001 | real tc |
| yes | ACME-EP-002 | real tc |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001", "ACME-EP-002"]


def test_non_tc_id_prefixes_are_parsed():
    """A real plan heads its smoke table `| SMK-ID | ... |`; a TC-ID-only gate dropped
    all 5 of its slug-bearing TCs silently."""
    testplan = """\
| SMK-ID | Scenario Slug | Purpose | Steps | Expected |
|--------|---------------|---------|-------|----------|
| SMK-001 | smk-exchange-happy-path | alive | GET | 200 |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [(r.tc_id, r.slug) for r in rows] == [("SMK-001", "smk-exchange-happy-path")]


def test_example_tables_inside_fenced_code_blocks_are_not_read():
    """A plan documenting its own table format contains example tables.

    Reading those as real puts example TC-IDs and slugs into Check 2, which then
    demands a `spec:` trace for any test whose name happens to match an illustration
    — a MUST finding manufactured from documentation.
    """
    testplan = """\
Testplans use this shape:

```markdown
| TC-ID | Scenario Slug | Test Purpose |
|-------|---------------|--------------|
| ACME-EP-999 | example-slug | an illustration |
```

## Test Cases

| TC-ID | Scenario Slug | Test Purpose |
|-------|---------------|--------------|
| ACME-EP-001 | real-slug | a real TC |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001"]

    fn = amplifier_verify.TestFunction(
        name="test_example_slug_behaviour",
        docstring="no trace",
        filepath="tests/test_x.py",
        spec_trace=None,
    )
    assert amplifier_verify.analyze(rows, [], [fn]).must == []


def test_slug_bearing_row_wins_over_slugless_restatement_either_order():
    """De-dup must not let a slug-less table displace the real slug.

    The most common TC-table shape has no Scenario Slug column, so under
    first-occurrence-wins a slug-less summary table appearing FIRST silently
    discarded the real slug — and a TC with no slug is invisible to Check 2, so the
    gate went quiet on exactly the test it should block.
    """
    slugless_first = """\
| TC-ID | Test Purpose | Technique | Steps | Expected Result |
|-------|-------------|-----------|-------|-----------------|
| SMK-001 | endpoint alive | EP | GET /health | 200 |

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| SMK-001 | endpoint alive | health-endpoint-alive |
"""
    rows = amplifier_verify.parse_tc_table(slugless_first)
    assert [(r.tc_id, r.slug) for r in rows] == [("SMK-001", "health-endpoint-alive")]

    # ... and the reverse order must not regress it either.
    slug_first = """\
| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| SMK-001 | endpoint alive | health-endpoint-alive |

| TC-ID | Test Purpose | Technique | Steps | Expected Result |
|-------|-------------|-----------|-------|-----------------|
| SMK-001 | endpoint alive | EP | GET /health | 200 |
"""
    rows = amplifier_verify.parse_tc_table(slug_first)
    assert [(r.tc_id, r.slug) for r in rows] == [("SMK-001", "health-endpoint-alive")]


def test_slugless_displacement_no_longer_silences_check_2():
    """End-to-end companion to the above: the MUST finding must actually fire."""
    testplan = """\
| TC-ID | Test Purpose | Technique | Steps | Expected Result |
|-------|-------------|-----------|-------|-----------------|
| SMK-001 | endpoint alive | EP | GET /health | 200 |

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| SMK-001 | endpoint alive | health-endpoint-alive |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    fn = amplifier_verify.TestFunction(
        name="test_health_endpoint_alive",
        docstring="no trace here",
        filepath="tests/test_health.py",
        spec_trace=None,
    )
    findings = amplifier_verify.analyze(rows, [], [fn])
    assert len(findings.must) == 1
    assert "test_health_endpoint_alive" in findings.must[0]


def test_conflicting_slugs_for_one_tc_id_are_surfaced_not_swallowed():
    """Two different non-empty slugs for one TC-ID is an authoring error."""
    testplan = """\
| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | first | slug-one |

| TC-ID | Test Purpose | Scenario Slug |
|-------|-------------|---------------|
| ACME-EP-001 | restated | slug-two |
"""
    conflicts: list[tuple[str, str, str]] = []
    rows = amplifier_verify.parse_tc_table(testplan, conflicts_out=conflicts)
    assert [(r.tc_id, r.slug) for r in rows] == [("ACME-EP-001", "slug-one")]
    assert conflicts == [("ACME-EP-001", "slug-one", "slug-two")]
    findings = amplifier_verify.analyze(rows, [], [], slug_conflicts=conflicts)
    assert any("two different Scenario Slugs" in s for s in findings.should)


def test_conflicts_are_passed_in_not_read_from_module_state():
    """analyze() must not depend on a global mutated by a previous parse.

    _slug_conflicts used to be module-level state: parse_tc_table(A) followed by
    analyze(rows_from_B) reported A's conflicts against B's rows. main() happens to
    call them in order, so it was not a live bug — but an invisible ordering
    dependency is exactly the class of coupling this file keeps getting caught by.
    """
    assert not hasattr(amplifier_verify, "_slug_conflicts")
    rows = [amplifier_verify.TCRow(tc_id="ACME-EP-001", slug="s", raw_line="")]
    assert amplifier_verify.analyze(rows, [], []).should == []


def test_escaped_pipe_does_not_shift_the_slug_column():
    """Markdown escapes a literal pipe as `\\|`; splitting on a bare | shifts columns.

    The old code read cells[1], upstream of free-text cells. Reading the slug from a
    far-right column (index 5-6 in real plans, after Steps / Test Data) makes this
    latent bug live: the slug became 'b', which is truthy garbage that matches nearly
    every test-function name, flipping Check 2 to mass FALSE MUST findings.
    """
    testplan = """\
| TC-ID | Test Purpose | Steps | Scenario Slug |
|-------|-------------|-------|---------------|
| ACME-EP-001 | alternation | run a \\| b | pairing-code-valid |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert rows[0].slug == "pairing-code-valid"
    assert rows[0].slug != "b"


def test_tc_id_column_is_located_by_header_not_assumed_at_index_zero():
    """The TC-ID half of "locate columns by header name" needs its own coverage.

    Every other fixture puts TC-ID at index 0, so a broken _TC_ID_COL_RE would be
    rescued by position and go unnoticed.
    """
    testplan = """\
| Scenario Slug | TC-ID | Test Purpose |
|---------------|-------|--------------|
| pairing-code-valid | ACME-EP-001 | valid pairing |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [(r.tc_id, r.slug) for r in rows] == [("ACME-EP-001", "pairing-code-valid")]


def test_ragged_row_is_skipped_without_dropping_the_rest_of_the_table():
    """A row shorter than the header must not crash or truncate the table."""
    testplan = """\
| Scenario Slug | TC-ID | Test Purpose |
|---------------|-------|--------------|
| slug-one | ACME-EP-001 | first |
| oops-short-row |
| slug-two | ACME-EP-002 | third |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001", "ACME-EP-002"]


def test_slugless_plan_reports_unverified_as_info_not_should():
    """The gate must say when it is structurally unable to check — as INFO.

    On the most common table shape (no Scenario Slug column) Check 2 can never fire,
    so reporting only "0/N traced" reads as "nothing to do" rather than "not
    verified". But this describes the PLAN's shape, not a defect in the PR: as a
    SHOULD it would attach an Important finding to every such plan no matter how clean
    the change is — alarm fatigue on the gate's own signal.
    """
    testplan = """\
| TC-ID | Test Purpose | Technique | Risk | Precondition | Steps | Expected Result |
|-------|-------------|-----------|------|--------------|-------|-----------------|
| TC-001 | login succeeds | EP | H | user exists | do it | ok |
| TC-002 | login fails | BVA | H | no user | do it | err |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    findings = amplifier_verify.analyze(rows, [], [])
    assert any("UNVERIFIED" in s and "2/2" in s for s in findings.info)
    assert not any("UNVERIFIED" in s for s in findings.should)


# ---------------------------------------------------------------------------
# parse_coverage_table — the twin of parse_tc_table, which carried the same two
# defects (stop after the first table; read columns by hardcoded index). Fixing
# only one of a duplicated pair is how the bug survived its first review.
# ---------------------------------------------------------------------------


def test_parse_coverage_table_reads_every_table_not_just_the_first():
    testplan = """\
## Coverage Analysis

| Scenario Slug | Status | Notes |
|---------------|--------|-------|
| slug-one | Covered | - |

### Second area

| Scenario Slug | Status | Notes |
|---------------|--------|-------|
| slug-two | Missing | - |
"""
    rows = amplifier_verify.parse_coverage_table(testplan)
    assert [(r.slug, r.status) for r in rows] == [("slug-one", "covered"), ("slug-two", "missing")]


def test_parse_coverage_table_finds_status_column_by_header_not_index():
    """Hardcoded cells[1] read 'ACME-EP-001' as the status, so 'Missing' never fired."""
    testplan = """\
| Scenario Slug | TC-ID | Status |
|---------------|-------|--------|
| slug-one | ACME-EP-001 | Missing |
"""
    rows = amplifier_verify.parse_coverage_table(testplan)
    assert [(r.slug, r.status) for r in rows] == [("slug-one", "missing")]
    findings = amplifier_verify.analyze([], rows, [])
    assert any("slug-one" in s for s in findings.should)


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
    satisfies that condition unconditionally, and CPython special-cases
    `hash("") == 0` so "" always iterates first, `next` returned "" ahead of any real
    slug — and being falsy, it then suppressed the MUST finding the real slug should
    have raised. Deterministically, on every run. The `s and ...` guard fixes it.
    (This test is reliable rather than 50/50 flaky precisely because the ordering is
    deterministic — do not "fix" the fixture on the assumption that it is random.)
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
