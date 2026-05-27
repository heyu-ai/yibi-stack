"""Spec-Test Traceability Scanner.

Scans spec.md files for Scenario slugs and test files for docstring traces,
then reports covered / missing / orphan.

Vendored from yibi-mvp backend/scripts/check_spec_coverage.py (ADR-0008).
Parametrized: accepts --specs-dir and --tests-dir for use outside yibi-mvp.

Usage:
    # Limit to one capability (recommended during development)
    uv run python plugins/sdd/scripts/check_spec_coverage.py \\
        --specs-dir openspec/changes/<name>/specs \\
        --tests-dir tests/ \\
        --cap <cap-dir-name>

    # Full scan
    uv run python plugins/sdd/scripts/check_spec_coverage.py \\
        --specs-dir openspec/changes/<name>/specs \\
        --tests-dir tests/

Note: spec files must be named exactly spec.md and placed in a subdirectory
whose name becomes the cap (e.g. specs/login/spec.md → cap = login).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Matches: #### Scenario: <slug> followed by " --" separator or end-of-line.
# slug must start and end with [a-z0-9] (no trailing hyphen).
SCENARIO_PATTERN = re.compile(
    r"^#{4}\s+Scenario:\s+([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?=\s+--|$)", re.MULTILINE
)

# Secondary pattern: detect any Scenario heading token for kebab-case validation.
SCENARIO_HEADING_PATTERN = re.compile(r"^#{4}\s+Scenario:\s+(\S+)", re.MULTILINE)

# Matches: spec: <cap>#<slug> anywhere in file text (docstrings, comments).
# Negative lookbehind prevents matching "nospec: ..." false positives.
# Cap accepts uppercase (e.g. E02-child-profile, F015-sleep-routine); slug is lowercase only.
TRACE_PATTERN = re.compile(
    r"(?<![A-Za-z])spec:\s+([A-Za-z0-9][A-Za-z0-9-]*)#([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)"
)


@dataclass
class CoverageResult:
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)


def parse_spec_scenarios(spec_root: Path, cap: str | None = None) -> dict[str, list[str]]:
    """Scan spec_root recursively for spec.md files and extract Scenario slugs.

    Cap is the direct parent directory name of spec.md (not grandparent).
    Returns {cap: [slug, ...]} mapping.
    """
    result: dict[str, list[str]] = {}

    for spec_file in sorted(spec_root.rglob("spec.md")):
        file_cap = spec_file.parent.name

        if cap is not None and file_cap != cap:
            continue

        try:
            text = spec_file.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"[WARN] skipping {spec_file}: {exc}", file=sys.stderr)
            continue

        # Detect duplicate slugs in this spec (ADR-0008: scanner must report ERROR)
        slugs = SCENARIO_PATTERN.findall(text)
        seen: set[str] = set()
        duplicates: list[str] = []
        for s in slugs:
            if s in seen:
                duplicates.append(s)
            else:
                seen.add(s)
        if duplicates:
            print(f"[ERROR] {spec_file}: duplicate slug(s): {duplicates}", file=sys.stderr)
            sys.exit(1)

        # Warn on Scenario headings with non-kebab-case slugs (silent false negatives)
        all_headings = SCENARIO_HEADING_PATTERN.findall(text)
        for raw in all_headings:
            slug_part = raw.split("--")[0].strip()
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", slug_part):
                print(
                    f"[WARN] {spec_file}: Scenario slug '{slug_part}'"
                    " is not kebab-case -- will not be tracked",
                    file=sys.stderr,
                )

        # Detect cap name collision (two spec.md share the same parent dir name)
        if file_cap in result:
            print(
                f"[FAIL] duplicate cap name '{file_cap}' found in two spec.md locations",
                file=sys.stderr,
            )
            sys.exit(1)

        if slugs:
            result[file_cap] = slugs

    return result


def parse_test_traces(test_root: Path, cap: str | None = None) -> dict[str, list[str]]:
    """Scan test_root recursively for test_*.py and extract spec: <cap>#<slug> traces.

    Returns {cap: [slug, ...]} grouped by cap (sorted, deduplicated).
    Cap names are normalized to lowercase for case-insensitive matching.
    """
    result_sets: dict[str, set[str]] = {}

    for test_file in sorted(test_root.rglob("test_*.py")):
        try:
            text = test_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"[WARN] skipping {test_file}: {exc}", file=sys.stderr)
            continue

        for match in TRACE_PATTERN.finditer(text):
            file_cap = match.group(1).lower()
            slug = match.group(2)
            if cap is not None and file_cap != cap:
                continue
            result_sets.setdefault(file_cap, set()).add(slug)

    return {k: sorted(v) for k, v in result_sets.items()}


def compute_coverage(
    spec_scenarios: dict[str, list[str]],
    test_traces: dict[str, list[str]],
) -> CoverageResult:
    """Compare spec scenarios against test traces and return coverage report."""
    covered: list[str] = []
    missing: list[str] = []
    orphan: list[str] = []

    for cap, slugs in spec_scenarios.items():
        traced = set(test_traces.get(cap, []))
        for slug in slugs:
            ref = f"{cap}#{slug}"
            if slug in traced:
                covered.append(ref)
            else:
                missing.append(ref)

    # Detect orphan traces: test references non-existent Scenario
    for cap, slugs in test_traces.items():
        spec_slugs = set(spec_scenarios.get(cap, []))
        for slug in set(slugs):
            if slug not in spec_slugs:
                orphan.append(f"{cap}#{slug}")

    return CoverageResult(covered=covered, missing=missing, orphan=orphan)


def _print_report(result: CoverageResult, cap: str | None) -> None:
    scope = f"cap={cap}" if cap else "all caps"
    print(f"\nSpec-Test Coverage Report ({scope})")
    print("=" * 50)

    for ref in result.covered:
        print(f"  [OK]   {ref}")
    for ref in result.missing:
        print(f"  [WARN] missing: {ref}")
    for ref in result.orphan:
        print(f"  [WARN] orphan:  {ref}")

    total = len(result.covered) + len(result.missing)
    print(
        f"\nSummary: {len(result.covered)}/{total} covered"
        f", {len(result.missing)} missing"
        f", {len(result.orphan)} orphan"
    )


def _resolve_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve spec_root and test_root from CLI args.

    Priority:
    1. Explicit --specs-dir / --tests-dir (both required when either is provided)
    2. Legacy --spec-root / --test-root (both required when either is provided)
    3. Generic fallback: cwd-relative defaults (openspec/specs and tests/)
    """
    specs_dir = args.specs_dir or args.spec_root
    tests_dir = args.tests_dir or args.test_root

    if bool(specs_dir) != bool(tests_dir):
        missing_flag = "--tests-dir" if specs_dir else "--specs-dir"
        print(
            f"[FAIL] {missing_flag} is required when the other is provided",
            file=sys.stderr,
        )
        sys.exit(1)

    if specs_dir and tests_dir:
        return Path(specs_dir), Path(tests_dir)

    # Generic fallback: cwd-relative defaults
    cwd = Path.cwd()
    spec_root = cwd / "openspec" / "specs"
    test_root = cwd / "tests"
    return spec_root, test_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check BDD Scenario-to-test coverage (ADR-0008).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Limit to one capability
  uv run python plugins/sdd/scripts/check_spec_coverage.py \\
      --specs-dir openspec/changes/my-feature/specs \\
      --tests-dir tests/ --cap my-feature

  # Full scan with exit-on-missing gate
  uv run python plugins/sdd/scripts/check_spec_coverage.py \\
      --specs-dir openspec/changes/my-feature/specs \\
      --tests-dir tests/ --exit-on-missing
""",
    )
    parser.add_argument("--cap", help="Limit scan to a single capability (spec directory name)")

    # Preferred flags
    parser.add_argument("--specs-dir", help="Root directory containing specs/<cap>/spec.md")
    parser.add_argument("--tests-dir", help="Root directory containing test_*.py files")

    # Legacy flags (yibi-mvp compat)
    parser.add_argument("--spec-root", help="(legacy) alias for --specs-dir")
    parser.add_argument("--test-root", help="(legacy) alias for --tests-dir")

    parser.add_argument(
        "--exit-on-missing",
        action="store_true",
        help="Exit with non-zero status if any Scenarios are missing or orphaned",
    )
    args = parser.parse_args()

    spec_root, test_root = _resolve_roots(args)

    if not spec_root.is_dir():
        print(f"[FAIL] spec root not found or not a directory: {spec_root}", file=sys.stderr)
        print("Use --specs-dir to specify the spec directory.", file=sys.stderr)
        sys.exit(1)
    if not test_root.is_dir():
        print(f"[FAIL] test root not found or not a directory: {test_root}", file=sys.stderr)
        print("Use --tests-dir to specify the test directory.", file=sys.stderr)
        sys.exit(1)

    spec_scenarios = parse_spec_scenarios(spec_root, cap=args.cap)

    # Validate --cap resolved to at least one spec
    if args.cap and not spec_scenarios:
        print(f"[FAIL] --cap '{args.cap}' not found in spec root {spec_root}", file=sys.stderr)
        sys.exit(1)

    # Warn when no specs found globally (wrong --specs-dir or empty directory)
    if not args.cap and not spec_scenarios:
        print(f"[WARN] no Scenario slugs found under {spec_root}", file=sys.stderr)
        print("[WARN] Check for non-kebab-case headings or wrong --specs-dir.", file=sys.stderr)
        if args.exit_on_missing:
            sys.exit(1)

    # Pass cap to parse_test_traces so it skips unrelated test files early.
    test_traces = parse_test_traces(test_root, cap=args.cap)

    result = compute_coverage(spec_scenarios, test_traces)

    _print_report(result, cap=args.cap)

    if args.exit_on_missing and (result.missing or result.orphan):
        sys.exit(1)


if __name__ == "__main__":
    main()
