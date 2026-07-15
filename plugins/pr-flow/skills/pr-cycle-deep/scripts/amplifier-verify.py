#!/usr/bin/env python3
"""amplifier-verify.py — TC coverage + docstring traceability check for /pr-cycle-deep.

Exit codes:
  0 — no spectra change in this PR (nothing to check)
  0 — all TCs traced (only INFO gaps; non-blocking)
  1 — MUST findings (missing spec: trace on test that targets a TC) — blocks merge
  1 — SHOULD findings only (coverage gap; printed as [WARN]; document reason before deferring)
  2 — fatal error (testplan.md missing, unparseable, or gh pr diff failed)
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TCRow:
    tc_id: str
    slug: str
    raw_line: str


@dataclass
class CoverageRow:
    slug: str
    status: str  # e.g. "covered", "partial", "missing", "redundant"
    raw_line: str


@dataclass
class TestFunction:
    name: str
    docstring: str
    filepath: str
    spec_trace: str | None  # extracted from "spec: <cap>#<slug>"


@dataclass
class Findings:
    must: list[str] = field(default_factory=list)
    should: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def has_blocking(self) -> bool:
        return bool(self.must)

    def is_empty(self) -> bool:
        return not (self.must or self.should or self.info)


# ---------------------------------------------------------------------------
# Markdown table parsers
# ---------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEPARATOR_RE = re.compile(r"^\|[-:\s|]+\|$")

# Markdown escapes a literal pipe inside a cell as `\|`. Splitting on a bare "|"
# injects a phantom cell and shifts every column to its right, so a slug read from
# a far-right column silently becomes garbage from the middle of a Steps cell.
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")

# TC-ID format. Accepts both conventions seen in the wild:
#   3-part  PREFIX-CATEGORY-NUMBER   e.g. YIBI-NFC-001, FBAUTH-UNIT-01
#   2-part  PREFIX-CAT+NUMBER        e.g. FBAUTH-U01, FBAUTH-I12, SMK-001
# The middle CATEGORY-dash segment is optional; the trailing segment is an
# optional letter run fused with a 2-4 digit sequence number.
_TC_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*-(?:[A-Z]{2,}-)?[A-Z]*\d{2,4}\b")

# Tables are identified STRUCTURALLY (a header row followed by a separator row), and
# their role is decided by WHICH COLUMNS THEY HAVE — never by keyword-matching the
# header text, and never by the enclosing `##` heading.
#
# Both of those were tried and both failed, in the same direction — silently:
#   * matching the header line for a coverage-ish shape used an unanchored regex, so
#     any TC table carrying an "Expected Status Code" column vanished;
#   * requiring a keyword-y "TC-definition" column dropped real TC tables whose
#     headers say Description / Objective / Assertion / 測項, and its keywords
#     overlapped the coverage vocabulary it was meant to exclude, so coverage tables
#     leaked in anyway;
#   * heading names do not identify TC tables at all — measured, they live under
#     arbitrary headings including "redundant items" and "traceability matrix".
#
# What survives is a purely structural pair of predicates, anchored and
# order-independent, shared by both parsers so they cannot drift apart:
#   * a TC table HAS an ID column;
#   * a coverage table HAS a slug column AND an exactly-`Status` column, and is
#     therefore NOT a TC table even when it carries an ID column too.
#
# Measured across an 18-plan corpus: 101 tables have an ID column only (all real TC
# tables), 3 have slug+Status only, and 5 have all three — every one of those 5 is a
# genuine coverage table (`| Scenario Slug | Status | TC-ID | Notes |`). Zero false
# exclusions.
#
# The ID column is not literally "TC-ID": a real plan heads its smoke-test table
# `| SMK-ID | Scenario Slug | Purpose | ... |`, and a TC-ID-only gate dropped all 5 of
# its slug-bearing TCs silently.
#
# The `[-_ ]` separator is MANDATORY, not optional. With `[-_ ]?` this also matched
# VALID, GRID, UUID, RAPID and Invalid (`[A-Z]{2,}` happily eats VAL / GR / UU / RAP),
# so a table headed `| Valid | TC-ID | Test Purpose |` resolved its "ID column" to
# column 0, read "yes" as the TC-ID, matched nothing, and vanished silently.
# Requiring the separator costs only the unattested `TCID` spelling.
_TC_ID_COL_RE = re.compile(r"^\s*[A-Z]{2,}[-_ ]ID\s*$", re.IGNORECASE)
_SLUG_COL_RE = re.compile(r"scenario\s*slug|^\s*slug\s*$", re.IGNORECASE)
_STATUS_COL_RE = re.compile(r"^\s*status\s*$", re.IGNORECASE)

_MISSING_STATUS_TERMS = {"missing", "partial"}


def _split_cells(row_body: str) -> list[str]:
    """Split a markdown table row body into cells, honouring escaped pipes."""
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT_RE.split(row_body)]


def _header_cells(line: str) -> list[str] | None:
    """Return the header row's cells, or None if the line is not a table row."""
    m = _TABLE_ROW_RE.match(line.strip())
    if not m:
        return None
    return _split_cells(m.group(1))


def _iter_table_headers(lines: list[str]) -> Iterator[tuple[int, list[str]]]:
    """Yield (line index, header cells) for every markdown table in the document.

    A table header is identified STRUCTURALLY -- a table row whose next non-empty
    line is a separator row -- not by pattern-matching its text. Every attempt to
    recognise tables by what their header *says* has failed in this file, always in
    the same direction: a predicate that is too loose swallows real TC tables, one
    that is too tight drops them, and both do it silently.

    Fenced code blocks are skipped. A testplan documenting its own table format
    contains example tables; reading those as real ones puts example TC-IDs and slugs
    into the blocking check, which then demands a `spec:` trace for a test whose name
    happens to match an illustration.
    """
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _header_cells(line) is None:
            continue
        nxt = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
        if _SEPARATOR_RE.match(nxt):
            yield i, _header_cells(line)  # type: ignore[misc]


def _parse_table_rows(lines: list[str], start: int) -> list[list[str]]:
    """Parse markdown table rows starting from the header row index."""
    rows: list[list[str]] = []
    # Skip header and separator
    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            break
        if _SEPARATOR_RE.match(line):
            continue
        m = _TABLE_ROW_RE.match(line)
        if not m:
            break
        rows.append(_split_cells(m.group(1)))
    return rows


def _find_col(header_cells: list[str], pattern: re.Pattern[str]) -> int | None:
    """Return the index of the first header cell matching pattern, else None."""
    for idx, cell in enumerate(header_cells):
        if pattern.search(cell):
            return idx
    return None


def _coverage_cols(header_cells: list[str]) -> tuple[int, int] | None:
    """Return (slug_col, status_col) if this is a coverage table, else None.

    The single definition of "coverage table", used by BOTH parsers -- one to read
    them, the other to exclude them. They previously each decided this for
    themselves and drifted: parse_tc_table skipped on an unanchored `.*Status`
    header match while parse_coverage_table required an exactly-`Status` column, so a
    table headed `Expected Status` was skipped by the first and rejected by the
    second, and vanished from both.
    """
    slug_col = _find_col(header_cells, _SLUG_COL_RE)
    status_col = _find_col(header_cells, _STATUS_COL_RE)
    if slug_col is None or status_col is None:
        return None
    id_col = _find_col(header_cells, _TC_ID_COL_RE)
    if id_col is not None and id_col < slug_col:
        # Subject-first: a coverage table is ABOUT scenarios and merely references TC
        # IDs, so its slug column comes first; a TC table is ABOUT the TCs. Measured
        # over 57 real plans: all 5 tables carrying ID+slug+Status are coverage and
        # all 5 put slug before ID; no TC-shaped one exists. Without this an
        # ID-first TC table that happens to track per-TC `Status` would be excluded
        # from TC parsing entirely -- silently. Narrowing the exclusion can only
        # over-collect (visible), never under-collect (silent), so it errs the safe
        # way for a gate whose defining bug is silent under-reporting.
        return None
    return slug_col, status_col


def parse_tc_table(
    testplan_text: str,
    conflicts_out: list[tuple[str, str, str]] | None = None,
) -> list[TCRow]:
    """Extract TC rows from EVERY TC table in testplan.md.

    Real testplans group TCs into one table per requirement / feature area, so a
    parser that stops at the first table sees only a fraction of the plan and then
    reports success — a silent no-op. Observed before this was fixed on two real
    downstream plans: 3 of 101 TCs parsed, and 16 of 57 on the plan that established
    the testplan convention in the first place. The gate passed both times.

    A table is a TC table if it HAS an ID column and is not a coverage table. Both
    predicates are structural -- see the _TC_ID_COL_RE block above for the three
    text-matching designs that preceded this and how each one silently dropped real
    tables.

    De-duplication is by ID, but a slug-bearing row always wins over a slug-less one
    regardless of order: the most common table shape has no slug column, so
    first-occurrence-wins would let a slug-less summary table displace the real slug
    and silently blind Check 2 to that TC. An ID restated with two DIFFERENT non-empty
    slugs is an authoring error; pass `conflicts_out` to collect those.
    """
    lines = testplan_text.splitlines()
    by_tc_id: dict[str, TCRow] = {}
    order: list[str] = []
    for i, header_cells in _iter_table_headers(lines):
        tc_col = _find_col(header_cells, _TC_ID_COL_RE)
        if tc_col is None:
            continue  # no ID column -> not a TC table
        if _coverage_cols(header_cells) is not None:
            continue  # a coverage table; parse_coverage_table() owns it
        slug_col = _find_col(header_cells, _SLUG_COL_RE)
        for cells in _parse_table_rows(lines, i):
            if len(cells) <= tc_col:
                continue
            m = _TC_ID_RE.search(cells[tc_col])
            if not m:
                continue
            tc_id = m.group(0)
            slug = ""
            if slug_col is not None and len(cells) > slug_col:
                # Strip backtick formatting from testplan.md cells (e.g. `slug-name` -> slug-name)
                slug = cells[slug_col].strip("`").strip()
            prev = by_tc_id.get(tc_id)
            if prev is None:
                by_tc_id[tc_id] = TCRow(tc_id=tc_id, slug=slug, raw_line=lines[i])
                order.append(tc_id)
                continue
            if not slug or slug == prev.slug:
                continue  # nothing new to learn
            if not prev.slug:
                by_tc_id[tc_id] = TCRow(tc_id=tc_id, slug=slug, raw_line=lines[i])
                continue  # a real slug beats a slug-less restatement
            if conflicts_out is not None:
                conflicts_out.append((tc_id, prev.slug, slug))
    return [by_tc_id[t] for t in order]


def parse_coverage_table(testplan_text: str) -> list[CoverageRow]:
    """Extract Coverage Analysis rows from EVERY coverage table in testplan.md.

    Mirrors parse_tc_table deliberately. This function carried the same two defects
    -- stop after the first table, and read columns by hardcoded index -- and fixing
    only its twin is how those defects survived their first review: Check 1 (SHOULD)
    is driven entirely by these rows, so a `missing` row in a second coverage table
    produced no finding at all.

    A coverage table is one that HAS both a slug column and a status column. The old
    header regex (`Scenario Slug ... .*Status`) was wrong twice over: it required slug
    to appear BEFORE status, silently skipping reversed-column tables, and its
    unanchored `.*Status` matched headers like "Expected Status" that the anchored
    _STATUS_COL_RE then refused -- so the table matched the outer gate, found no
    status column, and vanished.
    """
    lines = testplan_text.splitlines()
    coverage_rows: list[CoverageRow] = []
    for i, header_cells in _iter_table_headers(lines):
        cols = _coverage_cols(header_cells)
        if cols is None:
            continue  # not a coverage table
        slug_col, status_col = cols
        for cells in _parse_table_rows(lines, i):
            if len(cells) <= max(slug_col, status_col):
                continue
            slug = cells[slug_col].strip("`").strip()
            # Normalise: strip markdown markers like tick/cross
            status_clean = re.sub(r"[^a-zA-Z]", "", cells[status_col]).lower()
            coverage_rows.append(CoverageRow(slug=slug, status=status_clean, raw_line=lines[i]))
    return coverage_rows


# ---------------------------------------------------------------------------
# PR diff parser
# ---------------------------------------------------------------------------

_SPEC_TRACE_RE = re.compile(r"spec:\s*(\S+#\S+)", re.IGNORECASE)
_TEST_FUNC_RE = re.compile(r"^\+\s*def\s+(test_\w+)\s*\(")
_DOCSTRING_START_RE = re.compile(r'^\+\s*"""')
_FILE_HEADER_RE = re.compile(r"^\+\+\+\s+b/(.+)$")

# Spectra change directory detected from a PR diff. Only diff *file-header* lines
# (`diff --git`, `+++ `, `--- `) count — a real change adds/edits files under
# openspec/changes/<slug>/, which appear as headers. Content lines that merely
# mention such a path (e.g. the `<name>` placeholder examples inside generated
# skill docs) must NOT be treated as a change, or a spectra-init PR that only
# vendors those docs fails spuriously with "testplan.md not found for change
# '<name>'". The slug is also validated to reject placeholder-looking matches.
_CHANGE_DIR_RE = re.compile(r"[ab]/(?:docs/)?openspec/changes/([^/\n]+)/")
_VALID_CHANGE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def detect_change_from_diff(diff_text: str) -> str:
    """Return the spectra change slug from a PR diff, or "" if none.

    Scans only git file-header lines so a real changed file under
    openspec/changes/<slug>/ is required; a placeholder-looking slug (angle
    brackets or other non-slug chars, e.g. the literal ``<name>`` in generated
    skill docs) is rejected as defense-in-depth.
    """
    for line in diff_text.splitlines():
        if not (
            line.startswith("diff --git ") or line.startswith("+++ ") or line.startswith("--- ")
        ):
            continue
        # First path wins: on a `diff --git a/…old/… b/…new/…` change-dir rename this
        # returns the old slug. Renaming a spectra change dir mid-review is rare and the
        # worst case is looking for testplan.md under the stale slug (a clear failure).
        m = _CHANGE_DIR_RE.search(line)
        if m and _VALID_CHANGE_SLUG_RE.match(m.group(1)):
            return m.group(1)
    return ""


def parse_diff_test_functions(diff_text: str) -> list[TestFunction]:
    """Extract new/modified test functions and their spec traces from a PR diff."""
    functions: list[TestFunction] = []
    current_file = ""
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Track current file
        fhm = _FILE_HEADER_RE.match(line)
        if fhm:
            current_file = fhm.group(1)
            i += 1
            continue

        # New test function added
        fm = _TEST_FUNC_RE.match(line)
        if fm:
            func_name = fm.group(1)
            # Collect docstring — scan up to 50 lines after def to handle blank/setup lines
            docstring_lines: list[str] = []
            j = i + 1
            in_doc = False
            while j < min(i + 50, len(lines)):
                dl = lines[j]
                if _DOCSTRING_START_RE.match(dl):
                    in_doc = True
                if in_doc:
                    docstring_lines.append(dl.lstrip("+").strip())
                    # End of docstring: closing """ on same line or on subsequent line
                    if dl.count('"""') >= 2 or (len(docstring_lines) > 1 and '"""' in dl):
                        break
                elif _TEST_FUNC_RE.match(dl):
                    # Hit the next def — stop scanning this function's docstring
                    break
                j += 1
            docstring = " ".join(docstring_lines)
            trace_m = _SPEC_TRACE_RE.search(docstring)
            trace = trace_m.group(1) if trace_m else None
            functions.append(
                TestFunction(
                    name=func_name,
                    docstring=docstring,
                    filepath=current_file,
                    spec_trace=trace,
                )
            )
        i += 1
    return functions


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze(
    tc_rows: list[TCRow],
    coverage_rows: list[CoverageRow],
    test_functions: list[TestFunction],
    slug_conflicts: list[tuple[str, str, str]] | None = None,
) -> Findings:
    findings = Findings()
    slug_conflicts = slug_conflicts or []

    # Build slug → TC-ID map
    slug_to_tc: dict[str, str] = {}
    for tc in tc_rows:
        slug_to_tc[tc.slug.lower()] = tc.tc_id

    # Check 1 (SHOULD): coverage table has "missing" or "partial" entries
    # where the PR modifies relevant paths — we flag all missing/partial as SHOULD
    for cov in coverage_rows:
        normalised = re.sub(r"[^a-z]", "", cov.status.lower())
        if any(term in normalised for term in _MISSING_STATUS_TERMS):
            slug = cov.slug
            tc_id = slug_to_tc.get(slug.lower(), "unknown TC")
            findings.should.append(
                f"scenario '{slug}' ({tc_id}) is marked '{cov.status}' in Coverage Analysis"
                f" but no test covering it was found in this PR"
            )

    # Check 2 (MUST): new test functions referencing a TC-ID but missing spec: trace
    slug_set_lower = {s.lower() for s in slug_to_tc}
    for fn in test_functions:
        if fn.spec_trace is None:
            # Check if name contains a slug keyword (heuristic)
            name_lower = fn.name.lower()
            # `s and ...` is load-bearing. A TC table with no Scenario Slug column
            # yields slug == "", and `"" in name_lower` is vacuously True, so an
            # unguarded empty slug matches every function name.
            #
            # Before the guard this was a DETERMINISTIC gate bypass, not a flake:
            # the old code used `next(...)`, which returns the first match, and
            # CPython special-cases `hash("") == 0` (verified across PYTHONHASHSEED
            # 0/1/42/9999/random), so "" always lands in slot 0 and is always iterated
            # first. `next` therefore returned "" ahead of any genuine slug, and ""
            # being falsy then suppressed the finding that slug should have raised --
            # on every run, for any plan containing one slug-less TC.
            #
            # `any` is used over `next` because existence is what this asks; with the
            # guard in place the two are behaviourally identical.
            matched_slug = any(s and s.replace("-", "_") in name_lower for s in slug_set_lower)
            tc_prefix_match = any(
                tc.tc_id.lower().replace("-", "_") in name_lower for tc in tc_rows
            )
            if matched_slug or tc_prefix_match:
                findings.must.append(
                    f"{fn.filepath}::{fn.name} appears to target a TC"
                    f" but its docstring is missing a `spec: <cap>#<slug>` traceability marker"
                )

    # Check 3 (SHOULD): a TC-ID defined twice with two different slugs is an authoring
    # error. De-duplication keeps one; without this the other vanishes silently.
    for tc_id, kept, dropped in slug_conflicts:
        findings.should.append(
            f"{tc_id} is defined with two different Scenario Slugs"
            f" ('{kept}' and '{dropped}'); only '{kept}' is used for traceability"
        )

    # Info: say when the gate is structurally unable to check. Check 2 matches tests
    # to TCs by slug, so a TC with no slug can never be matched, and reporting only
    # "0/N traced" reads as "nothing to do" rather than "not verified".
    #
    # INFO, not SHOULD: the most common table shape has no slug column at all, so a
    # SHOULD here would attach an Important finding to every such plan regardless of
    # the PR's quality -- describing the plan's shape, not a defect in the change.
    # That is alarm fatigue on the gate's own signal. Whether to escalate it is
    # tracked separately.
    slugless = sum(1 for tc in tc_rows if not tc.slug)
    if slugless:
        findings.info.append(
            f"{slugless}/{len(tc_rows)} TCs have no Scenario Slug; Check 2 cannot match"
            f" tests to them by name, so their traceability is UNVERIFIED (not clean)."
        )

    # Info: coverage map summary
    total_tcs = len(tc_rows)
    traced = sum(1 for fn in test_functions if fn.spec_trace is not None)
    findings.info.append(f"Coverage map: {traced}/{total_tcs} TCs have `spec:` trace in this PR")

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run(args: list[str], timeout: int = 180) -> str:
    """Run a shell command and return stdout; exit 2 on failure."""
    try:
        result = subprocess.run(  # nosec B603
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        print(f"[FAIL] command not found: {args[0]}: {e}", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        print(
            f"[FAIL] {' '.join(args)} timed out after {timeout}s",
            file=sys.stderr,
        )
        sys.exit(2)
    if result.returncode != 0:
        print(
            f"[FAIL] {' '.join(args)} exited {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Amplifier-verifier for /pr-cycle-deep")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument(
        "--change",
        required=False,
        default="",
        help="Spectra change name (directory under openspec/changes/)",
    )
    opts = parser.parse_args()

    # Step 1 — detect spectra change from diff if not provided
    diff_text = _run(["gh", "pr", "diff", str(opts.pr)])

    change_name = opts.change
    if not change_name:
        change_name = detect_change_from_diff(diff_text)
        if not change_name:
            print("no spectra change")
            sys.exit(0)

    print(f"[OK]   spectra change detected: {change_name}")

    # Step 2 — locate testplan.md
    # Resolve the CURRENT checkout's root with --show-toplevel (not --git-common-dir,
    # whose parent is the MAIN repo). The change under review is committed on the PR
    # branch, which is checked out in the worktree we are running from; an unmerged
    # change's testplan does not yet exist in the main checkout. --show-toplevel also
    # handles being invoked from a subdir, returning the worktree (or repo) root.
    repo_root = Path(_run(["git", "rev-parse", "--show-toplevel"]).strip())
    candidates = [
        repo_root / f"openspec/changes/{change_name}/testplan.md",
        repo_root / f"docs/openspec/changes/{change_name}/testplan.md",
    ]
    testplan_path: Path | None = None
    for c in candidates:
        if c.is_file():
            testplan_path = c
            break

    if testplan_path is None:
        print(
            f"[FAIL] testplan.md not found for change '{change_name}'."
            f" Expected at openspec/changes/{change_name}/testplan.md",
            file=sys.stderr,
        )
        sys.exit(2)

    testplan_text = testplan_path.read_text(encoding="utf-8")

    # Step 3 — parse testplan
    slug_conflicts: list[tuple[str, str, str]] = []
    tc_rows = parse_tc_table(testplan_text, conflicts_out=slug_conflicts)
    if not tc_rows:
        print(
            f"[FAIL] testplan.md at {testplan_path} contains no TC table"
            f" (expected a table with an ID column header, e.g. 'TC-ID').",
            file=sys.stderr,
        )
        sys.exit(2)

    coverage_rows = parse_coverage_table(testplan_text)

    print(f"[OK]   parsed {len(tc_rows)} TCs, {len(coverage_rows)} coverage rows")

    # Step 4 — parse diff
    test_functions = parse_diff_test_functions(diff_text)
    print(f"[OK]   found {len(test_functions)} new test function(s) in PR diff")

    # Step 5 — analyze
    findings = analyze(tc_rows, coverage_rows, test_functions, slug_conflicts=slug_conflicts)

    # Step 6 — report
    print()
    print("=== Amplifier-Verifier Report ===")
    if findings.is_empty():
        print("[OK]   No issues found.")
    else:
        for msg in findings.must:
            print(f"[MUST]   {msg}")
        for msg in findings.should:
            print(f"[SHOULD] {msg}")
        for msg in findings.info:
            print(f"[INFO]   {msg}")

    if findings.has_blocking():
        print()
        print(
            "[FAIL] MUST findings present — fix before merge"
            " (add `spec: <cap>#<slug>` to affected test docstrings)."
        )
        sys.exit(1)

    if findings.should:
        print()
        print("[WARN] SHOULD findings present — document reason in PR description if deferring.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
