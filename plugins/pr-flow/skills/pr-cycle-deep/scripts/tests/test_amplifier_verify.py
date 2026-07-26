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

import pytest

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


def test_tc_prefix_match_is_the_whole_gate_on_slugless_plans():
    """Check 2's `tc_prefix_match` branch carries the gate for slug-less plans.

    Measured over 57 real plans: 6 of them have NO slug on any TC. On those,
    `matched_slug` can never fire and this branch IS the entire blocking check — yet
    every other Check-2 fixture supplies a slug, so deleting `or tc_prefix_match`
    used to leave the whole suite green.
    """
    tc_rows = [amplifier_verify.TCRow(tc_id="ACME-EP-001", slug="", raw_line="")]
    fn = amplifier_verify.TestFunction(
        name="test_acme_ep_001_behaviour",
        docstring="no trace here",
        filepath="tests/test_x.py",
        spec_trace=None,
    )
    findings = amplifier_verify.analyze(tc_rows, [], [fn])
    assert len(findings.must) == 1
    assert "test_acme_ep_001_behaviour" in findings.must[0]


def test_backticked_slugs_are_stripped_in_both_parsers():
    """Real plans backtick their slugs — 1446 such cells across the corpus.

    Without the strip, the slug is `` `a-slug` ``, which matches no test-function
    name: Check 2 goes silently quiet and Check 1's lookup degrades to "unknown TC".
    """
    testplan = """\
| TC-ID | Scenario Slug | Test Purpose |
|-------|---------------|--------------|
| ACME-EP-001 | `age-resolved-from-binding` | resolve age |

## Coverage Analysis

| Scenario Slug | Status | Notes |
|---------------|--------|-------|
| `age-resolved-from-binding` | missing | - |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert rows[0].slug == "age-resolved-from-binding"

    cov = amplifier_verify.parse_coverage_table(testplan)
    assert cov[0].slug == "age-resolved-from-binding"

    # ...and the two must still join up, or Check 1 reports "unknown TC".
    findings = amplifier_verify.analyze(rows, cov, [])
    assert any("ACME-EP-001" in s for s in findings.should)


def test_id_first_tc_table_tracking_status_is_not_excluded_as_coverage():
    """A TC table that tracks per-TC status must not be eaten by the coverage rule.

    The exclusion is narrowed by subject-first ordering: a coverage table is ABOUT
    scenarios (slug first) and only references TC IDs; a TC table is ABOUT the TCs
    (ID first). Measured over 57 plans: all 5 ID+slug+Status tables are coverage and
    all 5 put slug first. Without the narrowing this table vanished silently.
    """
    testplan = """\
| TC-ID | Scenario Slug | Steps | Status |
|-------|---------------|-------|--------|
| ACME-EP-001 | real-slug | do it | done |
| ACME-EP-002 | other-slug | do it | todo |
"""
    rows = amplifier_verify.parse_tc_table(testplan)
    assert [r.tc_id for r in rows] == ["ACME-EP-001", "ACME-EP-002"]

    # ...while a real coverage table (slug first) is still excluded.
    coverage = """\
| Scenario Slug | Status | TC-ID | Notes |
|---------------|--------|-------|-------|
| real-slug | covered | ACME-EP-001 | - |
"""
    assert amplifier_verify.parse_tc_table(coverage) == []
    assert len(amplifier_verify.parse_coverage_table(coverage)) == 1


def test_a_table_is_identified_by_its_separator_row():
    """Round 4's structural gate: header + separator row, not a text pattern.

    A pipe-delimited block with no separator row is not a markdown table. Reading it
    anyway would mine TC-IDs out of prose that merely looks tabular — and the header
    row of a real table is the only thing that tells the parser which column is which,
    so without the separator there is nothing distinguishing header from data.
    """
    no_separator = """\
| TC-ID | Scenario Slug |
| ACME-EP-001 | not-a-real-table |

## Test Cases

| TC-ID | Scenario Slug |
|-------|---------------|
| ACME-EP-002 | real |
"""
    rows = amplifier_verify.parse_tc_table(no_separator)
    assert [r.tc_id for r in rows] == ["ACME-EP-002"]
    assert "ACME-EP-001" not in [r.tc_id for r in rows]


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
    # would accept "add-login", so this test fails if the header filter is dropped.
    #
    # The content line carries the `b/` prefix deliberately. Without it the line does not
    # match `[ab]/(?:docs/)?openspec/changes/…` in the first place, so the test would stay
    # green with the header filter removed and prove nothing -- which is what the earlier
    # `See \`openspec/changes/add-login/proposal.md\`` fixture did once the regex gained its
    # `[ab]/` prefix requirement.
    diff = """\
diff --git a/.claude/skills/spectra-ask/SKILL.md b/.claude/skills/spectra-ask/SKILL.md
--- a/.claude/skills/spectra-ask/SKILL.md
+++ b/.claude/skills/spectra-ask/SKILL.md
@@ -1 +1,2 @@
 existing
+  The header would read b/openspec/changes/add-login/proposal.md in that example.
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


# ---------------------------------------------------------------------------
# Archive awareness.
#
# Regression: a PR that touches or merely references an ARCHIVED change aborted the
# gate with a fatal `[FAIL] testplan.md not found for change '<name>'`, even though
# such a PR has no active change to verify at all. The PRs most exposed are exactly
# the ones doing retirement / path-cleanup work on docs, because those legitimately
# carry historical change names.
#
# Two independent mechanisms produce it, and both are covered below:
#   * `changes/([^/\\n]+)/` captures the literal container segment `archive` from a
#     file header under `changes/archive/<date>-<name>/`, so the gate then hunts for
#     `changes/archive/testplan.md`;
#   * a change that has since been archived no longer exists at the active path, so
#     even a correctly-read name resolves to nothing.
#
# Both mean "no active spectra change" -> exit 0. The load-bearing counterpart is the
# positive control: a change that IS active but has no testplan.md must still exit 2.
# A fix verified only against the first half would pass everything and look correct.
# ---------------------------------------------------------------------------


def _make_repo(tmp_path, active=(), archived=(), root="openspec/changes", testplans=()):
    """Build a fake checkout with the given active and archived change dirs.

    `root` is parameterised because BOTH layout roots are live in this repo and a helper
    hardwired to one of them leaves the other's resolution path unexercised -- a mutation
    truncating `_CHANGE_ROOTS` to a single entry then survives.
    `testplans` writes `testplan.md` into the named active dirs, which is what the
    cross-root preference loop keys on.
    """
    changes = tmp_path.joinpath(*root.split("/"))
    for name in active:
        (changes / name).mkdir(parents=True, exist_ok=True)
    for name in archived:
        (changes / "archive" / name).mkdir(parents=True, exist_ok=True)
    for name in testplans:
        (changes / name).mkdir(parents=True, exist_ok=True)
        (changes / name / "testplan.md").write_text("| TC-ID |\n|---|\n", encoding="utf-8")
    return tmp_path


def _stub_run(monkeypatch, diff, repo_root):
    """Replace _run so main() gets a canned `gh pr diff` and repo root."""

    def fake_run(args, timeout=180):
        if args[0] == "gh":
            return diff
        if args[0] == "git":
            return f"{repo_root}\n"
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(amplifier_verify, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["amplifier-verify.py", "--pr", "1"])


def _one_file_diff(path):
    """A minimal single-file modification hunk for `path`."""
    return f"""\
diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""


def _two_file_diff(first, second):
    """Two file hunks in the given order -- git emits headers in path byte order."""
    return _one_file_diff(first) + _one_file_diff(second)


def _archive_diff(dirname):
    return _one_file_diff(f"openspec/changes/archive/{dirname}/tasks.md")


def _deleted_file_diff(path):
    """A deletion hunk: the `--- a/` header is present but nothing exists on disk."""
    return f"""\
diff --git a/{path} b/{path}
deleted file mode 100644
--- a/{path}
+++ /dev/null
@@ -1 +0,0 @@
-old
"""


def test_archive_header_creates_no_obligation_to_verify():
    """A header under `changes/archive/` names no change to verify.

    Two bugs met here. The old regex stopped at the first segment after `changes/`, so such
    a header reported the change as the container string `archive` and the gate hunted for
    `openspec/changes/archive/testplan.md`. Capturing the dated name instead was worse: it
    made the archived name a *resolvable* candidate that could win the scan over a real
    active change later in the same diff. Ranking is therefore by which tree the header
    points into -- archived material carries no obligation at all.
    """
    diff = _archive_diff("2026-07-18-add-login")
    assert amplifier_verify.detect_change_from_diff(diff) == ""
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == []
    assert refs.archive_tree == ["2026-07-18-add-login"]


def test_an_archive_header_does_not_shadow_an_active_change_in_the_same_diff():
    """The blocking regression: an archive header must not win the scan.

    git emits file headers in path byte order, so `changes/archive/...` precedes every
    active slug sorting after "archive". While the archived name was a resolvable candidate
    it won, `main()` took the archived-only branch, and the active change was never verified
    -- exit 0 where the pre-fix code exited 2. Asserted in BOTH orders so the fix cannot be
    a reordering that merely happens to work for one of them.
    """
    archived = "openspec/changes/archive/2026-07-18-old-thing/tasks.md"
    active = "openspec/changes/zz-new/tasks.md"
    for first, second in ((archived, active), (active, archived)):
        diff = _two_file_diff(first, second)
        assert amplifier_verify.detect_change_from_diff(diff) == "zz-new"
        refs = amplifier_verify.detect_change_refs_from_diff(diff)
        assert refs.active_tree == ["zz-new"]
        assert refs.archive_tree == ["2026-07-18-old-thing"]


def test_a_container_only_header_is_neither_tree():
    """`changes/archive/README.md` cannot take the `archive/` branch, so it needs the guard.

    The optional group needs a trailing `/` after the captured segment; `README.md/` has
    none, so the regex backtracks and captures the literal `archive` as an ACTIVE-tree slug.
    Without the guard that becomes an obligation to verify a change named `archive`.
    """
    diff = _one_file_diff("openspec/changes/archive/README.md")
    assert amplifier_verify.detect_change_from_diff(diff) == ""
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == []
    assert refs.archive_tree == []


def test_a_container_header_does_not_shadow_a_later_active_change():
    diff = _two_file_diff("openspec/changes/archive/README.md", "openspec/changes/zz-new/t.md")
    assert amplifier_verify.detect_change_from_diff(diff) == "zz-new"


def test_every_active_tree_candidate_is_reported_in_order_without_duplicates():
    diff = _two_file_diff(
        "openspec/changes/alpha/tasks.md", "openspec/changes/alpha/design.md"
    ) + _one_file_diff("openspec/changes/beta/tasks.md")
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == ["alpha", "beta"]


def test_locate_change_finds_an_active_change(tmp_path):
    repo = _make_repo(tmp_path, active=["add-login"])
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_active
    assert not location.is_archived_only


def test_locate_change_finds_a_date_prefixed_archived_change(tmp_path):
    """The common case: the diff names the change, the dir is `archive/<date>-<name>`."""
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login"])
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_archived_only
    assert not location.is_active


def test_locate_change_finds_an_archived_dir_named_verbatim(tmp_path):
    """A file header under the archive yields the dated dir name itself."""
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login"])
    location = amplifier_verify.locate_change(repo, "2026-07-18-add-login")
    assert location.is_archived_only


def test_active_wins_over_an_archived_namesake(tmp_path):
    """A name reused after archival is still an active change and must be verified."""
    repo = _make_repo(tmp_path, active=["add-login"], archived=["2026-07-18-add-login"])
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_active
    assert not location.is_archived_only


def test_archive_lookup_does_not_match_a_longer_name(tmp_path):
    """`<date>-<name>` must anchor: `foo` must not resolve to `...-bar-foo`.

    A `*-{name}` glob would match it, silently exit 0, and skip a real verification.
    """
    repo = _make_repo(tmp_path, archived=["2026-01-01-bar-foo"])
    location = amplifier_verify.locate_change(repo, "foo")
    assert not location.is_archived_only
    assert not location.is_active


def test_archive_lookup_does_not_match_a_name_with_a_suffix(tmp_path):
    """The match must end at the name: `foo` must not resolve to `...-foo-extra`.

    Distinct from the prefix case above, and it is the half a bare `re.match` lets
    through -- `match` anchors only at the start, so `\\d{4}-\\d{2}-\\d{2}-foo` happily
    matches `2026-01-01-foo-extra`. Only `fullmatch` (or a trailing `$`) closes it.
    """
    repo = _make_repo(tmp_path, archived=["2026-01-01-foo-extra"])
    location = amplifier_verify.locate_change(repo, "foo")
    assert not location.is_archived_only
    assert not location.is_active


def test_archive_lookup_ignores_an_undated_archive_entry(tmp_path):
    """Only `<YYYY-MM-DD>-<name>` counts as this change's archived form."""
    repo = _make_repo(tmp_path, archived=["notes-add-login"])
    location = amplifier_verify.locate_change(repo, "add-login")
    assert not location.is_archived_only
    assert not location.is_active


def test_the_archive_container_is_never_an_active_change(tmp_path):
    """`archive` names a container whose directory really does exist.

    Detection no longer emits it, but `--change archive` still can, and a bare
    directory-exists check would report the container as an active change and then
    demand a testplan.md for it.
    """
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login"])
    location = amplifier_verify.locate_change(repo, "archive")
    assert not location.is_active
    assert not location.is_archived_only


def test_main_exits_zero_when_an_active_tree_name_has_since_been_archived(
    tmp_path, monkeypatch, capsys
):
    """Negative control, via the route that actually produces a bare archived name.

    The archiving PR's own rename header is `a/openspec/changes/<name>/...` ->
    `b/openspec/changes/archive/<date>-<name>/...`; the `a/` side is the active path, so the
    bare `<name>` arrives as an ACTIVE-tree slug (the dated `b/` side also lands in
    `archive_tree` -- every match on the header is attributed to its tree). That name no
    longer resolves at an active root, and this is the case `locate_change`'s archived branch
    exists for -- without it the gate would abort on every archiving PR.
    """
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login"])
    rename = (
        "diff --git a/openspec/changes/add-login/tasks.md"
        " b/openspec/changes/archive/2026-07-18-add-login/tasks.md\n"
        "similarity index 100%\n"
        "rename from openspec/changes/add-login/tasks.md\n"
        "rename to openspec/changes/archive/2026-07-18-add-login/tasks.md\n"
    )
    assert amplifier_verify.detect_change_from_diff(rename) == "add-login"
    _stub_run(monkeypatch, rename, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "exists only in the archive" in captured.out
    assert "[FAIL]" not in captured.out + captured.err


def test_main_still_fails_when_an_active_change_has_no_testplan(tmp_path, monkeypatch, capsys):
    """Positive control: the gate must keep firing on a real active change.

    This is the test that makes the negative control above mean something -- a fix
    that simply exits 0 whenever testplan.md is missing would satisfy that one and
    disable the gate entirely.
    """
    repo = _make_repo(tmp_path, active=["add-login"])
    diff = """\
diff --git a/openspec/changes/add-login/tasks.md b/openspec/changes/add-login/tasks.md
--- a/openspec/changes/add-login/tasks.md
+++ b/openspec/changes/add-login/tasks.md
@@ -1 +1 @@
-old
+new
"""
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "testplan.md not found" in err


def test_main_verifies_the_active_change_despite_an_earlier_archive_header(
    tmp_path, monkeypatch, capsys
):
    """End-to-end form of the blocking regression: exit 2, not a silent exit 0.

    The archive header sorts first (git's path order), and the active change has no
    testplan.md. If the archived name wins, `main()` exits 0 and this change is never gated.
    """
    repo = _make_repo(tmp_path, active=["zz-new"], archived=["2026-07-18-old-thing"])
    diff = _two_file_diff(
        "openspec/changes/archive/2026-07-18-old-thing/tasks.md",
        "openspec/changes/zz-new/tasks.md",
    )
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    assert "testplan.md not found" in capsys.readouterr().err


def test_main_exits_zero_when_only_archived_material_is_touched(tmp_path, monkeypatch, capsys):
    """An archive-only diff has nothing to gate, and says so distinguishably."""
    repo = _make_repo(tmp_path, archived=["2026-07-18-old-thing"])
    _stub_run(monkeypatch, _archive_diff("2026-07-18-old-thing"), repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "2026-07-18-old-thing" in captured.out
    assert "[FAIL]" not in captured.out + captured.err


def test_main_exits_zero_when_an_archived_change_is_deleted(tmp_path, monkeypatch, capsys):
    """Deleting an archived change must not abort the gate.

    A deletion emits a `--- a/openspec/changes/archive/<dated>/...` header while nothing
    remains on disk. Ranking candidates by what RESOLVES would leave this one resolving
    nowhere and, if that is fatal, abort exactly the retirement/cleanup PR shape this fix
    exists to unblock. Ranking by which tree the header points into has no such state.
    """
    repo = _make_repo(tmp_path)
    diff = _deleted_file_diff("openspec/changes/archive/2026-07-18-gone/tasks.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "[FAIL]" not in captured.out + captured.err


def test_main_warns_when_several_active_changes_are_touched(tmp_path, monkeypatch, capsys):
    """First-active-wins is pre-existing; make the narrowing visible rather than silent."""
    repo = _make_repo(tmp_path, active=["alpha", "beta"])
    diff = _two_file_diff("openspec/changes/alpha/tasks.md", "openspec/changes/beta/tasks.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2  # alpha has no testplan.md
    err = capsys.readouterr().err
    assert "alpha" in err and "beta" in err


def test_locate_change_resolves_under_the_docs_layout_root(tmp_path):
    """The second layout root must resolve, not just appear in the regex.

    Without this, truncating `_CHANGE_ROOTS` to a single entry survives the whole suite.
    """
    repo = _make_repo(tmp_path, active=["add-login"], root="docs/openspec/changes")
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_active
    assert location.active_dir == repo / "docs" / "openspec" / "changes" / "add-login"


def test_locate_change_finds_an_archived_change_under_the_docs_layout_root(tmp_path):
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login"], root="docs/openspec/changes")
    assert amplifier_verify.locate_change(repo, "add-login").is_archived_only


def test_an_active_dir_holding_the_testplan_wins_over_an_empty_one_at_another_root(tmp_path):
    """The cross-root preference loop: prefer whichever active dir actually has a testplan.

    The replaced code picked the first candidate whose `testplan.md` was present, not the
    first directory that existed. Deleting the preference loop otherwise survives the suite.
    """
    repo = _make_repo(tmp_path, active=["add-login"])
    _make_repo(repo, testplans=["add-login"], root="docs/openspec/changes")
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_active
    assert location.active_dir == repo / "docs" / "openspec" / "changes" / "add-login"


def test_a_dot_in_the_change_name_is_not_a_regex_wildcard(tmp_path):
    """`re.escape` is load-bearing: `_VALID_CHANGE_SLUG_RE` permits `.` in a slug.

    Unescaped, name `v1.2` matches archived dir `2026-01-01-v1-2` and the gate exits 0.
    """
    repo = _make_repo(tmp_path, archived=["2026-01-01-v1-2"])
    location = amplifier_verify.locate_change(repo, "v1.2")
    assert not location.is_archived_only
    assert not location.is_active


def test_a_file_in_the_archive_is_not_mistaken_for_an_archived_change(tmp_path):
    """`entry.is_dir()` is load-bearing: without it a regular file resolves as archived."""
    archive_root = tmp_path / "openspec" / "changes" / "archive"
    archive_root.mkdir(parents=True)
    (archive_root / "2026-07-18-add-login").write_text("not a directory", encoding="utf-8")
    location = amplifier_verify.locate_change(tmp_path, "add-login")
    assert not location.is_archived_only
    assert not location.is_active


def test_the_oldest_dated_archive_copy_is_chosen_deterministically(tmp_path):
    """Pins the `sorted()` tie-break the comment claims, which was otherwise untested."""
    repo = _make_repo(tmp_path, archived=["2026-07-18-add-login", "2026-01-02-add-login"])
    location = amplifier_verify.locate_change(repo, "add-login")
    assert location.is_archived_only
    assert location.archived_dir is not None
    assert location.archived_dir.name == "2026-01-02-add-login"


def test_the_missing_directory_message_lists_every_location_that_was_probed(
    tmp_path, monkeypatch, capsys
):
    """The fatal message must not name only the two active roots.

    Detection can hand `main()` a name that never lives at an active root, so a message
    listing only those points at a path that by construction cannot exist.

    The six expected strings are written out **literally** rather than derived from
    `probed_locations()`. Deriving them moves both sides of the assertion together, so the
    test then pins only "main() calls that function" and every mutation of what it returns
    survives -- including `return active`, which reintroduces the exact defect this test's
    docstring claims to guard.
    """
    repo = _make_repo(tmp_path)
    _stub_run(monkeypatch, _one_file_diff("openspec/changes/ghost/tasks.md"), repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    for expected in (
        "openspec/changes/ghost/",
        "docs/openspec/changes/ghost/",
        "openspec/changes/archive/ghost/",
        "openspec/changes/archive/<YYYY-MM-DD>-ghost/",
        "docs/openspec/changes/archive/ghost/",
        "docs/openspec/changes/archive/<YYYY-MM-DD>-ghost/",
    ):
        assert expected in err


def test_main_verifies_a_later_active_candidate_when_the_first_is_archived_only(
    tmp_path, monkeypatch, capsys
):
    """The masking must not survive by moving from detection into resolution.

    The canonical SDD shape: one PR archives finished change `alpha` and proposes `beta`.
    `alpha` arrives as an active-tree name (the archiving rename header's `a/` side) but
    resolves archived-only. Stopping there exits 0 and never gates `beta`.
    """
    repo = _make_repo(tmp_path, active=["beta"], archived=["2026-07-25-alpha"])
    diff = _two_file_diff("openspec/changes/alpha/tasks.md", "openspec/changes/beta/proposal.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "testplan.md not found for change 'beta'" in err


def test_main_exits_zero_only_when_every_active_candidate_is_archived(
    tmp_path, monkeypatch, capsys
):
    repo = _make_repo(tmp_path, archived=["2026-07-25-alpha", "2026-07-25-beta"])
    diff = _two_file_diff("openspec/changes/alpha/tasks.md", "openspec/changes/beta/tasks.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "[FAIL]" not in captured.out + captured.err


def test_main_fails_loud_when_a_candidate_resolves_nowhere_beside_an_archived_one(
    tmp_path, monkeypatch, capsys
):
    """An archived candidate must not mask an unresolvable one.

    Ranking "nowhere" below "archived" so another candidate can excuse it is the shadowing
    bug one level down -- an unresolvable active name would vanish the same way.
    """
    repo = _make_repo(tmp_path, archived=["2026-07-25-alpha"])
    diff = _two_file_diff("openspec/changes/alpha/tasks.md", "openspec/changes/ghost/tasks.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    assert "ghost" in capsys.readouterr().err


def test_main_verifies_the_first_active_candidate_not_the_last(tmp_path, monkeypatch, capsys):
    """Pin WHICH candidate is verified, not merely that a warning is printed.

    `beta` is given a valid testplan and `alpha` is not, so the two choices produce
    different exit codes -- otherwise `active_tree[0]` -> `[-1]` survives.
    """
    repo = _make_repo(tmp_path, active=["alpha"], testplans=["beta"])
    diff = _two_file_diff("openspec/changes/alpha/tasks.md", "openspec/changes/beta/tasks.md")
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "verifying only 'alpha'" in err
    assert "testplan.md not found for change 'alpha'" in err


def test_detection_reads_the_docs_layout_root_too(tmp_path):
    """`(?:docs/)?` in the regex needs a parsing test, not only a resolution one.

    Removing it otherwise survives, because no diff fixture used that root.
    """
    diff = _one_file_diff("docs/openspec/changes/add-login/tasks.md")
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == ["add-login"]
    archived = _one_file_diff("docs/openspec/changes/archive/2026-07-18-add-login/tasks.md")
    assert amplifier_verify.detect_change_refs_from_diff(archived).archive_tree == [
        "2026-07-18-add-login"
    ]


def test_only_file_headers_are_scanned_never_content_lines(tmp_path):
    """Pins the design property the docstring claims, making the Non-goal self-checking.

    The content line must carry the `b/` prefix the regex requires, or the test proves
    nothing: a line reading `see openspec/changes/foo/...` does not match `[ab]/…` at all, so
    it stays empty whether the header filter is present or not. With the prefix, replacing the
    header condition with `True` yields `['add-login']` and the test fails as intended.
    """
    diff = """\
diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1 +1,2 @@
 existing
+the archiving header reads b/openspec/changes/add-login/tasks.md in the example above
"""
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == []
    assert refs.archive_tree == []


def test_an_archiving_rename_yields_the_bare_active_name(tmp_path):
    """Direction 1 of the rename pair: active -> archive. Must keep working."""
    rename = (
        "diff --git a/openspec/changes/add-login/tasks.md"
        " b/openspec/changes/archive/2026-07-18-add-login/tasks.md\n"
        "similarity index 100%\n"
    )
    refs = amplifier_verify.detect_change_refs_from_diff(rename)
    assert refs.active_tree == ["add-login"]


def test_an_unarchiving_rename_creates_the_obligation(tmp_path):
    """Direction 2 of the rename pair: archive -> active. Must create an obligation.

    A 100%-similarity rename emits no `---`/`+++` lines, so the `diff --git` line is the
    only line this scanner reads that carries the paths (`rename from`/`rename to` also do,
    but are deliberately not scanned). Reading only its FIRST path attributed the archive
    side and never saw the active destination, so the obligation disappeared and the gate
    exited 0 -- a silent bypass where the pre-archive-awareness code exited 2.

    Scanning EVERY match on the header line fixes it without disturbing the archiving
    direction, because that direction's first path is the active one and both sides are now
    recorded either way.
    """
    rename = (
        "diff --git a/openspec/changes/archive/2026-07-18-add-login/tasks.md"
        " b/openspec/changes/add-login/tasks.md\n"
        "similarity index 100%\n"
    )
    refs = amplifier_verify.detect_change_refs_from_diff(rename)
    assert refs.active_tree == ["add-login"]
    assert refs.archive_tree == ["2026-07-18-add-login"]


def test_main_gates_a_change_restored_out_of_the_archive(tmp_path, monkeypatch, capsys):
    """End-to-end: the restored change is verified, not silently excused.

    Before this fix `main()` printed "touches only archived material" and exited 0 while the
    PR put a change back into the active tree with no testplan.
    """
    repo = _make_repo(tmp_path, active=["add-login"])
    rename = (
        "diff --git a/openspec/changes/archive/2026-07-18-add-login/tasks.md"
        " b/openspec/changes/add-login/tasks.md\n"
        "similarity index 100%\n"
        "rename from openspec/changes/archive/2026-07-18-add-login/tasks.md\n"
        "rename to openspec/changes/add-login/tasks.md\n"
    )
    _stub_run(monkeypatch, rename, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    assert "testplan.md not found for change 'add-login'" in capsys.readouterr().err


def test_both_sides_of_a_cross_slug_active_rename_are_surfaced(tmp_path):
    """Scanning every match also surfaces the destination of an active->active rename.

    Previously only the source was seen. This test pins the DETECT layer only (both names
    in header order); what main() does with the pair is pinned by
    `test_main_verifies_the_destination_of_a_cross_slug_rename` below.
    """
    rename = (
        "diff --git a/openspec/changes/old-name/tasks.md"
        " b/openspec/changes/new-name/tasks.md\n"
        "similarity index 100%\n"
    )
    refs = amplifier_verify.detect_change_refs_from_diff(rename)
    assert refs.active_tree == ["old-name", "new-name"]


def test_main_verifies_the_destination_of_a_cross_slug_rename(tmp_path, monkeypatch, capsys):
    """The realistic cross-slug state: source dir renamed away, destination active.

    The source candidate resolves NOWHERE and must be superseded by the active destination
    -- silently, because the disappeared source is what a rename means, not an ambiguity.
    Pins three things at once: the destination is the change that gets verified, the
    nowhere candidate does not abort the gate, and no multi-candidate [WARN] fires (that
    warning is for the both-dirs-coexist case only). A fail-loud-on-nowhere mutant
    otherwise survives the whole suite while aborting every real cross-slug rename PR.
    """
    repo = _make_repo(tmp_path, active=["new-name"])
    rename = (
        "diff --git a/openspec/changes/old-name/tasks.md"
        " b/openspec/changes/new-name/tasks.md\n"
        "similarity index 100%\n"
    )
    _stub_run(monkeypatch, rename, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "testplan.md not found for change 'new-name'" in err
    assert "no change directory found" not in err
    assert "[WARN]" not in err


def test_a_stray_file_rename_does_not_eat_the_destination_change(tmp_path):
    """A greedy capture must not span the a/b path boundary of a rename header.

    With `([^/\\n]+)/` the a-side of `a/openspec/changes/notes.md
    b/openspec/changes/real-change/notes.md` captures `notes.md b` -- slug validation
    rejects it, but the match has already consumed the b-side's `b/` anchor, so the
    destination change dir is never seen: both trees empty, gate exits 0, while the PR
    moves a file INTO an active change. `([^/\\s]+)` cannot cross the boundary (git path
    fields on a header line are space-separated) and loses no legitimate capture, because
    `_VALID_CHANGE_SLUG_RE` already rejects any name containing whitespace.
    """
    stray = (
        "diff --git a/openspec/changes/notes.md"
        " b/openspec/changes/real-change/notes.md\n"
        "similarity index 100%\n"
    )
    refs = amplifier_verify.detect_change_refs_from_diff(stray)
    assert refs.active_tree == ["real-change"]
    assert refs.archive_tree == []


def test_an_archive_side_stray_file_rename_still_finds_the_destination(tmp_path):
    stray = (
        "diff --git a/openspec/changes/archive/old-notes.md"
        " b/openspec/changes/real-change/notes.md\n"
        "similarity index 100%\n"
    )
    refs = amplifier_verify.detect_change_refs_from_diff(stray)
    assert refs.active_tree == ["real-change"]
    assert refs.archive_tree == []


def test_a_placeholder_named_directory_in_a_real_header_is_rejected(tmp_path):
    """Slug validation must fire on HEADER lines too, not only guard content lines.

    A template repo can vendor a literal `openspec/changes/<name>/` directory, whose diff
    headers then carry `<name>` as a real path segment. Without `_VALID_CHANGE_SLUG_RE`
    the gate would hunt for `openspec/changes/<name>/testplan.md` and abort. This became
    unpinned when the capture tightened to `[^/\\s]+`: the container test's old kill path
    (a space-containing capture) no longer exists, so this is the only test that reaches
    the validation via a header.
    """
    diff = _one_file_diff("openspec/changes/<name>/proposal.md")
    refs = amplifier_verify.detect_change_refs_from_diff(diff)
    assert refs.active_tree == []
    assert refs.archive_tree == []


def test_an_ordinary_modification_header_still_yields_one_candidate(tmp_path):
    """One `diff --git a/P b/P` line alone names the same path twice; dedup collapses it.

    Header-only fixture deliberately: with the full 3-line fixture (`---`/`+++` included)
    this test could not distinguish same-line dedup from cross-line dedup. The lone
    `diff --git` line is also exactly the shape a 100%-similarity diff emits.
    """
    refs = amplifier_verify.detect_change_refs_from_diff(
        "diff --git a/openspec/changes/add-login/tasks.md b/openspec/changes/add-login/tasks.md\n"
    )
    assert refs.active_tree == ["add-login"]


def test_main_reports_a_change_dir_that_exists_nowhere(tmp_path, monkeypatch, capsys):
    """Neither active nor archived is the genuinely anomalous case -- still fatal.

    The message must say the directory is missing rather than blame testplan.md,
    which was never the reason.
    """
    repo = _make_repo(tmp_path)
    diff = """\
diff --git a/openspec/changes/ghost/tasks.md b/openspec/changes/ghost/tasks.md
--- a/openspec/changes/ghost/tasks.md
+++ b/openspec/changes/ghost/tasks.md
@@ -1 +1 @@
-old
+new
"""
    _stub_run(monkeypatch, diff, repo)
    with pytest.raises(SystemExit) as exc:
        amplifier_verify.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ghost" in err
