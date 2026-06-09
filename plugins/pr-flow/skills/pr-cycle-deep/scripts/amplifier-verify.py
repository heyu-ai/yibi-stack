#!/usr/bin/env python3
"""amplifier-verify.py — TC coverage + docstring traceability check for /pr-cycle-deep.

Exit codes:
  0 — no spectra change in this PR (nothing to check)
  0 — all TCs have trace or only INFO-level gaps (non-blocking)
  1 — MUST/SHOULD findings found (blocks merge on MUST; documents reason on SHOULD)
  2 — fatal error (testplan.md missing, unparseable, or gh pr diff failed)
"""
from __future__ import annotations

import argparse
import re
import subprocess
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

_TC_TABLE_HEADER_RE = re.compile(
    r"\|\s*TC-ID\s*\|", re.IGNORECASE
)
_COVERAGE_TABLE_HEADER_RE = re.compile(
    r"\|\s*Scenario\s+Slug\s*\|.*Status", re.IGNORECASE
)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEPARATOR_RE = re.compile(r"^\|[-:\s|]+\|$")

# TC-ID format: UPPER_ALPHA_NUM-CATEGORY-NUMBER
_TC_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*-[A-Z]{2,}-\d{3}\b")

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


def parse_tc_table(testplan_text: str) -> list[TCRow]:
    """Extract TC rows from testplan.md TC table."""
    lines = testplan_text.splitlines()
    tc_rows: list[TCRow] = []
    for i, line in enumerate(lines):
        if _TC_TABLE_HEADER_RE.search(line):
            for cells in _parse_table_rows(lines, i):
                if not cells:
                    continue
                raw = cells[0]
                m = _TC_ID_RE.search(raw)
                if not m:
                    continue
                tc_id = m.group(0)
                slug = cells[1] if len(cells) > 1 else ""
                tc_rows.append(TCRow(tc_id=tc_id, slug=slug, raw_line=line))
            break
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
                slug = cells[0]
                # Status is typically column 1 or 2; look for known terms
                status_raw = cells[1] if len(cells) > 1 else ""
                # Normalise: strip markdown markers like tick/cross
                status_clean = re.sub(r"[^a-zA-Z]", "", status_raw).lower()
                coverage_rows.append(
                    CoverageRow(slug=slug, status=status_clean, raw_line=line)
                )
            break
    return coverage_rows


# ---------------------------------------------------------------------------
# PR diff parser
# ---------------------------------------------------------------------------

_SPEC_TRACE_RE = re.compile(r"spec:\s*(\S+#\S+)", re.IGNORECASE)
_TEST_FUNC_RE = re.compile(r"^\+\s*def\s+(test_\w+)\s*\(")
_DOCSTRING_START_RE = re.compile(r'^\+\s*"""')
_FILE_HEADER_RE = re.compile(r"^\+\+\+\s+b/(.+)$")


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
            # Collect docstring (next few lines)
            docstring_lines: list[str] = []
            j = i + 1
            in_doc = False
            while j < min(i + 10, len(lines)):
                dl = lines[j]
                if _DOCSTRING_START_RE.match(dl):
                    in_doc = True
                if in_doc:
                    docstring_lines.append(dl.lstrip("+").strip())
                    # End of docstring
                    if dl.count('"""') >= 2 or (
                        len(docstring_lines) > 1 and '"""' in dl
                    ):
                        break
                elif dl.startswith("+"):
                    docstring_lines.append(dl.lstrip("+").strip())
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
            matched_slug = next(
                (s for s in slug_set_lower if s.replace("-", "_") in name_lower), None
            )
            if matched_slug or any(
                tc.tc_id.lower()[:6] in name_lower for tc in tc_rows
            ):
                findings.must.append(
                    f"{fn.filepath}::{fn.name} appears to target a TC"
                    f" but its docstring is missing a `spec: <cap>#<slug>` traceability marker"
                )

    # Info: coverage map summary
    total_tcs = len(tc_rows)
    traced = sum(1 for fn in test_functions if fn.spec_trace is not None)
    findings.info.append(
        f"Coverage map: {traced}/{total_tcs} TCs have `spec:` trace in this PR"
    )

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run(args: list[str]) -> str:
    """Run a shell command and return stdout; exit 2 on failure."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        print(f"[FAIL] command not found: {args[0]}: {e}", file=sys.stderr)
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
        m = re.search(r"openspec/changes/([^/\n]+)/", diff_text)
        if not m:
            print("no spectra change")
            sys.exit(0)
        change_name = m.group(1)

    print(f"[OK]   spectra change detected: {change_name}")

    # Step 2 — locate testplan.md
    # Search from repo root (cwd) or well-known paths
    candidates = [
        Path(f"openspec/changes/{change_name}/testplan.md"),
        Path(f"docs/openspec/changes/{change_name}/testplan.md"),
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
        print(
            "[WARN] SHOULD findings present — document reason in PR description"
            " if deferring."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
