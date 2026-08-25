#!/usr/bin/env python3
"""amplifier-verify.py — TC coverage + docstring traceability check for /pr-cycle-deep.

Exit codes:
  0 — no spectra change in this PR (nothing to check)
  0 — the PR touches only archived material, or names a change that has since been
      archived (finished work; nothing to gate)
  0 — all TCs traced (only INFO gaps; non-blocking)
  1 — MUST findings (missing spec: trace on test that targets a TC) — blocks merge
  1 — SHOULD findings only (coverage gap; printed as [WARN]; document reason before deferring)
  2 — fatal error: change directory not found, testplan.md missing, testplan contains no TC
      table, or a `gh` / `git` invocation failed (binary not found, timed out, or non-zero)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

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


@dataclass
class PRMetadata:
    base_oid: str
    head_oid: str
    changed_file_count: int


@dataclass
class PRFileChange:
    status: str
    old_path: str | None
    new_path: str | None


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
#
# Group 1 captures the `archive/` container when present, so a header can be attributed to the
# tree it points into; group 2 is the directory name. Without the group, a header under
# `changes/archive/<YYYY-MM-DD>-<name>/` reported the change as the literal string `archive` and
# the gate went looking for `openspec/changes/archive/testplan.md`, aborting the whole PR review.
#
# Capturing the dated name as an ordinary slug was worse, not better: it made the archived name a
# *resolvable* candidate, and since only the first matching header was returned and git emits
# headers in path byte order, the archived name won over any active slug sorting after `"archive"`
# — turning a loud failure into a silent skip of that active change's verification. Attribution by
# tree is what fixes it; see `detect_change_refs_from_diff`.
#
# The name capture is `[^/\s]+`, not `[^/\n]+`: git path fields on a header line are
# space-separated, and a greedy newline-only capture can span the a/b boundary. On a rename
# whose a-side is a stray file directly under `changes/` (`a/openspec/changes/notes.md
# b/openspec/changes/real-change/notes.md`) it captured `notes.md b` — rejected by slug
# validation, but the `b/` anchor was already consumed, so the destination change was never
# seen and the gate exited 0. Excluding whitespace loses no legitimate capture:
# _VALID_CHANGE_SLUG_RE rejects any name containing it.
_CHANGE_DIR_RE = re.compile(r"[ab]/(?:docs/)?openspec/changes/(archive/)?([^/\s]+)/")
_VALID_CHANGE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Both layout roots a change directory can live under, in the order they are tried.
_CHANGE_ROOTS = ("openspec/changes", "docs/openspec/changes")
# The container an archived change is moved into, and the date prefix it gains there.
# Concatenated rather than str.format()-ed into a template: `{4}` in `\d{4}` is a
# positional replacement field to str.format, which raises IndexError.
_ARCHIVE_SEGMENT = "archive"
_ARCHIVE_DATE_PREFIX_RE = r"\d{4}-\d{2}-\d{2}-"
_TESTPLAN_NAME = "testplan.md"


@dataclass
class DiffChangeRefs:
    """Change directories a diff's FILE HEADERS point at, split by which tree they are in.

    The split is the whole fix for the shadowing bug. **Only a header under the active tree
    creates an obligation to verify**; a header under ``changes/archive/`` creates none,
    whether or not that directory still exists on disk.

    Ranking by which tree the header points into rather than by what each candidate *resolves*
    to is deliberate, and the alternative is worse in both directions. A candidate can resolve
    nowhere — an archive-*deletion* PR emits a header under ``changes/archive/<dated>/`` with
    nothing left on disk — and a resolve-based ranking has no correct slot for it: make
    "nowhere" fatal and the gate aborts on exactly the retirement/cleanup PRs this script was
    fixed to stop blocking; rank it below "archived" so another archived candidate can mask it
    and an unresolvable *active* name gets masked too, which is the shadowing bug one level
    down. Attribution by tree has no such state, because an archive-origin name never reaches
    :func:`locate_change`.
    """

    active_tree: list[str] = field(default_factory=list)
    archive_tree: list[str] = field(default_factory=list)


def classify_spectra_path(path: str) -> tuple[str, str | None]:
    """將儲存庫相對路徑分類為啟用中、封存或非 Spectra 變更。"""
    segments = path.split("/")
    for root in _CHANGE_ROOTS:
        root_segments = root.split("/")
        if segments[: len(root_segments)] != root_segments:
            continue
        remainder = segments[len(root_segments) :]
        if len(remainder) < 2:
            return ("none", None)
        if remainder[0] == _ARCHIVE_SEGMENT:
            if len(remainder) < 3 or not _VALID_CHANGE_SLUG_RE.fullmatch(remainder[1]):
                return ("none", None)
            return ("archive", remainder[1])
        if not _VALID_CHANGE_SLUG_RE.fullmatch(remainder[0]):
            return ("none", None)
        return ("active", remainder[0])
    return ("none", None)


def derive_change_refs(changes: list[PRFileChange]) -> DiffChangeRefs:
    """依檔案變更的舊路徑再新路徑推導 Spectra 變更參照。"""
    refs = DiffChangeRefs()
    for change in changes:
        for path in (change.old_path, change.new_path):
            if path is None:
                continue
            tree, slug = classify_spectra_path(path)
            if tree == "active" and slug is not None and slug not in refs.active_tree:
                refs.active_tree.append(slug)
            elif tree == "archive" and slug is not None and slug not in refs.archive_tree:
                refs.archive_tree.append(slug)
    return refs


def detect_change_refs_from_diff(diff_text: str) -> DiffChangeRefs:
    """Attribute every change directory named by a diff FILE HEADER to its tree.

    Scans only git file-header lines so a real changed file under ``openspec/changes/<slug>/``
    is required; a placeholder-looking slug (angle brackets or other non-slug chars, e.g. the
    literal ``<name>`` in generated skill docs) is rejected as defense-in-depth.

    Both lists preserve header order and drop duplicates, so a change touched by several files
    appears once.

    The literal ``archive`` capture is still rejected explicitly, for a reason the optional
    group does not cover: ``changes/archive/README.md`` — a file directly in the container —
    cannot take that branch, because the group needs a trailing ``/`` after the captured
    segment and ``README.md/`` has none. The regex backtracks and captures ``archive`` as an
    *active-tree* slug, which without the guard becomes an obligation to verify a change named
    ``archive``.
    """
    refs = DiffChangeRefs()
    for line in diff_text.splitlines():
        if not (
            line.startswith("diff --git ") or line.startswith("+++ ") or line.startswith("--- ")
        ):
            continue
        # EVERY match on the line, not just the first. A `diff --git a/…old/… b/…new/…` header
        # carries two paths, and a 100%-similarity rename emits no `---`/`+++` lines at all, so
        # this header is the only line THIS SCANNER READS that carries either of them (the
        # `rename from`/`rename to` lines also do, but are deliberately not scanned). Reading
        # just the first attributed
        # only the `a/` side: it happened to be right for the archiving direction (whose `a/` side
        # is the active path) and silently wrong for the reverse — restoring a change out of the
        # archive lost the obligation entirely and the gate exited 0.
        #
        # Ordinary `a/P b/P` headers name the same directory twice; the dedup below collapses them,
        # so scanning both sides costs nothing on the common shape.
        for m in _CHANGE_DIR_RE.finditer(line):
            in_archive, name = m.group(1), m.group(2)
            if not _VALID_CHANGE_SLUG_RE.match(name):
                continue
            if in_archive:
                if name not in refs.archive_tree:
                    refs.archive_tree.append(name)
                continue
            if name == _ARCHIVE_SEGMENT:
                continue  # the container itself, not a change
            if name not in refs.active_tree:
                refs.active_tree.append(name)
    return refs


def detect_change_from_diff(diff_text: str) -> str:
    """Return the change slug this PR obliges the gate to verify, or "" if none.

    That is the first **active-tree** slug. A diff touching only archived material returns "",
    because archived work has nothing left to gate — see :class:`DiffChangeRefs`.
    """
    refs = detect_change_refs_from_diff(diff_text)
    return refs.active_tree[0] if refs.active_tree else ""


@dataclass
class ChangeLocation:
    """Where a change name resolves on disk: active, archived, or nowhere.

    The distinction is what separates "nothing to gate" from "the gate is broken".
    An archived change is finished work whose artifacts have moved out of the *active*
    ``openspec/changes/<name>/`` into ``openspec/changes/archive/<YYYY-MM-DD>-<name>/``
    (``archive`` is a child of ``changes/``, not a sibling); treating its absence from the
    active path as a fatal error blocks exactly the PRs most likely to name it — docs changes
    fixing trace paths and other retirement cleanup, which carry historical change names by
    their very nature and have no active change to verify at all.
    """

    active_dir: Path | None = None
    archived_dir: Path | None = None

    @property
    def is_active(self) -> bool:
        return self.active_dir is not None

    @property
    def is_archived_only(self) -> bool:
        return self.active_dir is None and self.archived_dir is not None


def probed_locations(change_name: str) -> list[str]:
    """Every location :func:`locate_change` looks at, in the same order, as display strings.

    Derived from the same constants as the lookup and kept adjacent to it so the fatal
    "not found" message cannot drift from what was actually searched. Listing only the two
    active roots was misleading in a specific way: an explicit ``--change`` can name a dated
    archive directory, which by construction never exists at an active root, so the message
    pointed at a path that could not have been there.
    """
    active = [f"{root}/{change_name}/" for root in _CHANGE_ROOTS]
    archived = []
    for root in _CHANGE_ROOTS:
        archived.append(f"{root}/{_ARCHIVE_SEGMENT}/{change_name}/")
        archived.append(f"{root}/{_ARCHIVE_SEGMENT}/<YYYY-MM-DD>-{change_name}/")
    return active + archived


def locate_change(repo_root: Path, change_name: str) -> ChangeLocation:
    """Resolve a change name against the active and archived layouts.

    Active wins over an archived namesake: a name reused after archival is a real
    change that must still be verified.

    Two archived spellings are accepted, because the name can arrive by two routes — neither
    of which is a prose mention: :func:`detect_change_refs_from_diff` reads only file headers,
    so a content line that merely names a path yields nothing.
    1. The **archiving PR's own rename header**, whose first path is still the active
       ``a/openspec/changes/<name>/``, so the bare ``<name>`` arrives and its directory is now
       ``archive/<YYYY-MM-DD>-<name>/``.
    2. An explicit ``--change <name>``, in either spelling, including the dated directory name
       verbatim.

    The date prefix is matched with ``fullmatch``, never a ``*-<name>`` glob and never a bare
    ``match``: the glob matches ``2026-01-01-bar-foo`` for the name ``foo``, and ``match``
    — anchored only at the start — matches ``2026-01-01-foo-extra``. Either would report an
    unrelated change as archived, exit 0, and silently skip a verification that should have
    run. An explicit ``^…$`` with ``re.match`` would be equally correct; ``fullmatch`` is
    preferred only because it puts both anchors in the call rather than half in the pattern.
    """
    if change_name == _ARCHIVE_SEGMENT:
        # The container is not a change, even though the directory exists. Only
        # reachable through an explicit --change; reported as "found nowhere".
        return ChangeLocation()

    # Prefer an active directory that actually holds a testplan, so a name present under
    # both layout roots resolves the same way it did before this function existed (the
    # old code picked the first candidate whose testplan.md existed as a file -- note
    # is_file() proves type and existence, not that the contents can be read).
    active_dirs = [
        d for d in (repo_root / root / change_name for root in _CHANGE_ROOTS) if d.is_dir()
    ]
    for candidate in active_dirs:
        if (candidate / _TESTPLAN_NAME).is_file():
            return ChangeLocation(active_dir=candidate)
    if active_dirs:
        return ChangeLocation(active_dir=active_dirs[0])

    dated_re = re.compile(_ARCHIVE_DATE_PREFIX_RE + re.escape(change_name))
    for root in _CHANGE_ROOTS:
        archive_root = repo_root / root / _ARCHIVE_SEGMENT
        verbatim = archive_root / change_name
        if verbatim.is_dir():
            return ChangeLocation(archived_dir=verbatim)
        if not archive_root.is_dir():
            continue
        # sorted() so a repo that somehow holds two dated copies of one change picks
        # deterministically (oldest first) instead of following directory order.
        for entry in sorted(archive_root.iterdir()):
            if dated_re.fullmatch(entry.name) and entry.is_dir():
                return ChangeLocation(archived_dir=entry)
    return ChangeLocation()


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


def _run_json(args: list[str], timeout: int = 180) -> Any:
    """執行命令並解析 JSON 標準輸出，失敗時以狀態碼 2 結束。"""
    stdout = _run(args, timeout=timeout)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        print(
            f"[FAIL] 無法解析 {' '.join(args)} 的 JSON 輸出：{e}",
            file=sys.stderr,
        )
        sys.exit(2)


def fetch_pr_metadata(pr: int) -> PRMetadata:
    """取得用於一致性驗證的 PR 中繼資料。"""
    data = _run_json(["gh", "pr", "view", str(pr), "--json", "baseRefOid,headRefOid,changedFiles"])
    if not isinstance(data, dict):
        print("[FAIL] PR 中繼資料不是 JSON 物件。", file=sys.stderr)
        sys.exit(2)
    base_oid = data.get("baseRefOid")
    head_oid = data.get("headRefOid")
    changed_file_count = data.get("changedFiles")
    if (
        not isinstance(base_oid, str)
        or not isinstance(head_oid, str)
        or type(changed_file_count) is not int
    ):
        print(
            "[FAIL] PR 中繼資料缺少有效的 baseRefOid、headRefOid 或 changedFiles。", file=sys.stderr
        )
        sys.exit(2)
    return PRMetadata(
        base_oid=base_oid,
        head_oid=head_oid,
        changed_file_count=changed_file_count,
    )


@lru_cache(maxsize=1)
def _get_repo_slug() -> str:
    """取得並快取目前儲存庫的 owner/name 識別字。"""
    slug = _run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()
    if not slug:
        print("[FAIL] gh repo view 未回傳 repository 識別字。", file=sys.stderr)
        sys.exit(2)
    return slug


def fetch_pr_file_changes(pr: int) -> list[PRFileChange]:
    """取得並正規化 PR 的所有分頁檔案變更。"""
    slug = _get_repo_slug()
    pages = _run_json(
        [
            "gh",
            "api",
            f"repos/{slug}/pulls/{pr}/files?per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        print("[FAIL] PR 檔案 API 未回傳預期的分頁 JSON 陣列。", file=sys.stderr)
        sys.exit(2)

    changes: list[PRFileChange] = []
    known_statuses = {"added", "removed", "renamed", "modified", "changed", "copied"}
    for page in pages:
        for record in page:
            if not isinstance(record, dict):
                print("[FAIL] PR 檔案 API 回傳非物件紀錄。", file=sys.stderr)
                sys.exit(2)
            status = record.get("status")
            if not isinstance(status, str) or status not in known_statuses:
                print(f"[FAIL] PR 檔案 API 回傳未知狀態：{status!r}。", file=sys.stderr)
                sys.exit(2)
            filename = record.get("filename")
            if not isinstance(filename, str):
                print("[FAIL] PR 檔案 API 紀錄缺少有效的 filename。", file=sys.stderr)
                sys.exit(2)

            if status == "renamed":
                previous_filename = record.get("previous_filename")
                if not isinstance(previous_filename, str):
                    print("[FAIL] renamed 檔案缺少有效的 previous_filename。", file=sys.stderr)
                    sys.exit(2)
                changes.append(
                    PRFileChange(status=status, old_path=previous_filename, new_path=filename)
                )
            elif status == "removed":
                changes.append(PRFileChange(status=status, old_path=filename, new_path=None))
            elif status == "added":
                changes.append(PRFileChange(status=status, old_path=None, new_path=filename))
            else:
                changes.append(PRFileChange(status=status, old_path=filename, new_path=filename))
    return changes


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

    diff_text = ""
    if opts.change:
        candidates = [opts.change]
        diff_text = _run(["gh", "pr", "diff", str(opts.pr)])
    else:
        pre_meta = fetch_pr_metadata(opts.pr)
        file_changes = fetch_pr_file_changes(opts.pr)
        refs = derive_change_refs(file_changes)
        candidates = refs.active_tree
        if candidates:
            # 文字 diff 僅用於測試函式 docstring 的追溯分析。
            diff_text = _run(["gh", "pr", "diff", str(opts.pr)])

        post_meta = fetch_pr_metadata(opts.pr)
        if pre_meta != post_meta:
            print(
                "[FAIL] PR 在檔案掃描期間發生變更，請重新執行驗證。"
                f" 掃描前：{pre_meta}；掃描後：{post_meta}。",
                file=sys.stderr,
            )
            sys.exit(2)
        if len(file_changes) != pre_meta.changed_file_count:
            print(
                "[FAIL] PR 檔案 API 回傳數量與 changedFiles 不一致："
                f"取得 {len(file_changes)} 筆，預期 {pre_meta.changed_file_count} 筆。",
                file=sys.stderr,
            )
            sys.exit(2)
        checkout_head = _run(["git", "rev-parse", "HEAD"]).strip()
        if checkout_head != pre_meta.head_oid:
            print(
                "[FAIL] 目前 checkout 的 HEAD 與 PR headRefOid 不一致："
                f"本機 {checkout_head}，PR {pre_meta.head_oid}。",
                file=sys.stderr,
            )
            sys.exit(2)

        if not candidates:
            # No obligation to verify. Distinguish "touched archived material" from "touched no
            # change at all": both are exit 0, but a reader debugging a gate that passed needs
            # to know which one happened.
            if refs.archive_tree:
                print(
                    "no active spectra change: this PR touches only archived material"
                    f" ({', '.join(refs.archive_tree)})"
                )
            else:
                print("no spectra change")
            sys.exit(0)

    # Step 2 — resolve every candidate, then locate testplan.md
    # Resolve the CURRENT checkout's root with --show-toplevel (not --git-common-dir,
    # whose parent is the MAIN repo). The change under review is committed on the PR
    # branch, which is checked out in the worktree we are running from; an unmerged
    # change's testplan does not yet exist in the main checkout. --show-toplevel also
    # handles being invoked from a subdir, returning the worktree (or repo) root.
    repo_root = Path(_run(["git", "rev-parse", "--show-toplevel"]).strip())
    resolved = [(name, locate_change(repo_root, name)) for name in candidates]

    # An ACTIVE candidate wins over an archived one regardless of position. Stopping at the
    # first candidate was a second shadowing bug, one layer below the first: the canonical
    # SDD PR archives one change and proposes another, the archived one arrives first (its
    # rename header's `a/` side is still the active path), and exiting 0 there left the
    # proposed change ungated.
    active = [(name, loc) for name, loc in resolved if loc.is_active]
    if not active:
        archived = [(name, loc) for name, loc in resolved if loc.is_archived_only]
        if len(archived) == len(resolved):
            # Every candidate is finished work: nothing to gate.
            described = ", ".join(
                f"'{name}' ({loc.archived_dir.relative_to(repo_root)})"
                for name, loc in archived
                if loc.archived_dir is not None
            )
            print(f"no active spectra change: exists only in the archive: {described}")
            sys.exit(0)
        # At least one candidate resolves NOWHERE. Report that one — an archived sibling must
        # not excuse it, or an unresolvable active name vanishes the same way.
        name = next(n for n, loc in resolved if not loc.is_active and not loc.is_archived_only)
        roots = " or ".join(probed_locations(name))
        print(
            f"[FAIL] no change directory found for '{name}'. Searched {roots}."
            f" If this name came from the PR diff, the change may have been renamed,"
            f" deleted rather than archived, or the local checkout may not be on the PR branch.",
            file=sys.stderr,
        )
        sys.exit(2)

    change_name, location = active[0]
    if len(active) > 1:
        # First-active-wins predates this script's archive awareness and is left as-is:
        # failing loud on several changes would block PRs that legitimately touch two, and
        # verifying all of them is a wider contract than this gate has. What is not
        # acceptable is doing it invisibly, so name every candidate and which one was used.
        print(
            f"[WARN] {len(active)} active change dirs in this diff"
            f" ({', '.join(name for name, _ in active)}); verifying only '{change_name}'",
            file=sys.stderr,
        )

    print(f"[OK]   spectra change detected: {change_name}")

    assert location.active_dir is not None  # nosec B101 — implied by is_active
    testplan_path = location.active_dir / _TESTPLAN_NAME
    if not testplan_path.is_file():
        print(
            f"[FAIL] {_TESTPLAN_NAME} not found for change '{change_name}'."
            f" Expected at {testplan_path.relative_to(repo_root)}",
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
