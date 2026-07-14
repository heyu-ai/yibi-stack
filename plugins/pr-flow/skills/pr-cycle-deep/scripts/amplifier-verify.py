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

_TC_TABLE_HEADER_RE = re.compile(r"\|\s*TC-ID\s*\|", re.IGNORECASE)
_COVERAGE_TABLE_HEADER_RE = re.compile(r"\|\s*Scenario\s+Slug\s*\|.*Status", re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEPARATOR_RE = re.compile(r"^\|[-:\s|]+\|$")

# TC-ID format. Accepts both conventions seen in the wild:
#   3-part  PREFIX-CATEGORY-NUMBER   e.g. YIBI-NFC-001, FBAUTH-UNIT-01
#   2-part  PREFIX-CAT+NUMBER        e.g. FBAUTH-U01, FBAUTH-I12, SMK-001
# The middle CATEGORY-dash segment is optional; the trailing segment is an
# optional letter run fused with a 2-4 digit sequence number.
_TC_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*-(?:[A-Z]{2,}-)?[A-Z]*\d{2,4}\b")

# Column headers are located BY NAME, never by fixed index: real testplans put the
# TC-ID and Scenario Slug columns in different positions, and many have no slug
# column at all. Surveying every testplan.md in a downstream consumer repo found the
# slug column at index 0, 1, 3, 5, 6, or absent — and the single most common TC table
# shape (the `sdd:qa-test-designer` output) has no slug column whatsoever.
_TC_ID_COL_RE = re.compile(r"^\s*TC[-_ ]?ID\s*$", re.IGNORECASE)
_SLUG_COL_RE = re.compile(r"scenario\s*slug|^\s*slug\s*$", re.IGNORECASE)

_MISSING_STATUS_TERMS = {"missing", "partial"}


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
        cells = [c.strip() for c in m.group(1).split("|")]
        rows.append(cells)
    return rows


def _find_col(header_cells: list[str], pattern: re.Pattern[str]) -> int | None:
    """Return the index of the first header cell matching pattern, else None."""
    for idx, cell in enumerate(header_cells):
        if pattern.search(cell):
            return idx
    return None


def parse_tc_table(testplan_text: str) -> list[TCRow]:
    """Extract TC rows from EVERY TC table in testplan.md.

    Real testplans group TCs into one table per requirement / feature area, so a
    parser that stops at the first table sees only a fraction of the plan and then
    reports success — a silent no-op. Observed before this was fixed on two real
    downstream plans: 3 of 101 TCs parsed, and 16 of 57 on the plan that established
    the testplan convention in the first place. The gate passed both times.

    Coverage-analysis tables are skipped here: their header also contains a TC-ID
    column, so they would otherwise be swept in as TC rows and double-count the
    total. parse_coverage_table() owns them.

    TC rows are de-duplicated by TC-ID (first occurrence wins), so a TC restated
    across tables counts once.
    """
    lines = testplan_text.splitlines()
    tc_rows: list[TCRow] = []
    seen_tc_ids: set[str] = set()
    for i, line in enumerate(lines):
        if not _TC_TABLE_HEADER_RE.search(line):
            continue
        if _COVERAGE_TABLE_HEADER_RE.search(line):
            continue  # coverage table, owned by parse_coverage_table()
        header_match = _TABLE_ROW_RE.match(line.strip())
        if not header_match:
            continue
        header_cells = [c.strip() for c in header_match.group(1).split("|")]
        # Locate columns by header name. Absent slug column -> slug stays "".
        tc_col = _find_col(header_cells, _TC_ID_COL_RE)
        if tc_col is None:
            tc_col = 0
        slug_col = _find_col(header_cells, _SLUG_COL_RE)
        for cells in _parse_table_rows(lines, i):
            if len(cells) <= tc_col:
                continue
            m = _TC_ID_RE.search(cells[tc_col])
            if not m:
                continue
            tc_id = m.group(0)
            if tc_id in seen_tc_ids:
                continue
            seen_tc_ids.add(tc_id)
            slug = ""
            if slug_col is not None and len(cells) > slug_col:
                # Strip backtick formatting from testplan.md cells (e.g. `slug-name` -> slug-name)
                slug = cells[slug_col].strip("`").strip()
            tc_rows.append(TCRow(tc_id=tc_id, slug=slug, raw_line=line))
    return tc_rows


def parse_coverage_table(testplan_text: str) -> list[CoverageRow]:
    """Extract Coverage Analysis rows from testplan.md."""
    lines = testplan_text.splitlines()
    coverage_rows: list[CoverageRow] = []
    for i, line in enumerate(lines):
        if _COVERAGE_TABLE_HEADER_RE.search(line):
            for cells in _parse_table_rows(lines, i):
                if len(cells) < 2:
                    continue
                slug = cells[0].strip("`").strip()
                # Status is typically column 1 or 2; look for known terms
                status_raw = cells[1] if len(cells) > 1 else ""
                # Normalise: strip markdown markers like tick/cross
                status_clean = re.sub(r"[^a-zA-Z]", "", status_raw).lower()
                coverage_rows.append(CoverageRow(slug=slug, status=status_clean, raw_line=line))
            break
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
) -> Findings:
    findings = Findings()

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
            # `s and ...` is load-bearing: a TC table with no Scenario Slug column
            # yields slug == "", and `"" in name_lower` is vacuously True. Without
            # the guard an empty slug matches every function name.
            # `any` (not `next`) keeps this order-independent: `next` returns the
            # FIRST match, and since "" always satisfies the condition it could be
            # returned ahead of a genuine slug — and being falsy, it would then
            # suppress the very finding the genuine slug should have raised. Set
            # iteration order over strings is hash-randomised, so that suppression
            # was non-deterministic across runs.
            matched_slug = any(
                s and s.replace("-", "_") in name_lower for s in slug_set_lower
            )
            tc_prefix_match = any(
                tc.tc_id.lower().replace("-", "_") in name_lower for tc in tc_rows
            )
            if matched_slug or tc_prefix_match:
                findings.must.append(
                    f"{fn.filepath}::{fn.name} appears to target a TC"
                    f" but its docstring is missing a `spec: <cap>#<slug>` traceability marker"
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
    tc_rows = parse_tc_table(testplan_text)
    if not tc_rows:
        print(
            f"[FAIL] testplan.md at {testplan_path} contains no TC table"
            f" (expected a table with a 'TC-ID' column header).",
            file=sys.stderr,
        )
        sys.exit(2)

    coverage_rows = parse_coverage_table(testplan_text)

    print(f"[OK]   parsed {len(tc_rows)} TCs, {len(coverage_rows)} coverage rows")

    # Step 4 — parse diff
    test_functions = parse_diff_test_functions(diff_text)
    print(f"[OK]   found {len(test_functions)} new test function(s) in PR diff")

    # Step 5 — analyze
    findings = analyze(tc_rows, coverage_rows, test_functions)

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
