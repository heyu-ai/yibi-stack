#!/usr/bin/env python3
"""agy_validate.py — fail-loud validation + brain-artifact rescue for agy output.

Addresses issue #153: in a nested worktree (``.claude/worktrees/<name>/``) agy
fails to resolve an ``@file`` reference and silently enters agentic file-search
mode, producing three failure modes that all pass the legacy "non-empty" gate:

  1. wrong-target review — agy finds a *stale* scratch input from a previous
     session, reviews the WRONG repo, and returns valid-looking output.
  2. brain-artifact detour — agy writes the real review to
     ``~/.gemini/antigravity-cli/brain/<uuid>/<name>.md`` and only prints a
     pointer + narration to stdout.
  3. agentic timeout — the file search exceeds ``--print-timeout`` and the
     output is ``Error: timed out waiting for response``.

The companion shell scripts now inline the prompt (no ``@file``), which removes
the agentic trigger. This script is the defence-in-depth layer that turns any
residual silent failure into a loud one. It post-processes the raw output file
*in place*:

  - brain-artifact rescue (fix 4): if the output is a pointer to a
    ``brain/<uuid>/*.md`` artifact, read that file and replace the output with
    its real content.
  - fail-loud checks (fix 3): timeout marker; agentic narration (tool-call openers
    always fail; a brain-pointer opener fails only when a brain-artifact path is
    present; an agentic-search or pointer-less brain-phrase opener fails only when
    no review-structure heading follows — see check_agentic_narration); missing
    Verdict section; and content sanity (fails only when the review references file
    paths yet none are the changed paths — a review with no file refs passes).

Exit codes:
  0 — output passed all enabled checks (after any rescue)
  1 — a check failed (message on stderr); the caller must treat the review as
      unusable
  2 — usage / IO error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Brain-artifact pointer: agy in agentic mode writes the real review to
# ~/.gemini/antigravity-cli/brain/<uuid-ish>/<name>.md and prints only a pointer.
# Match a "~"- or "/"-anchored path containing /brain/<hex-or-dash run>/ ending in
# .md. The dir segment is intentionally lenient (not a strict UUID) so the tests
# can use short ids like "abcdef12"; the real source dir is constrained at rescue
# time to live under ~/.gemini/antigravity-cli/brain (see rescue_brain_artifact).
_BRAIN_POINTER = re.compile(
    r"""(?P<path>[~/][^\s"'`<>]*?/brain/[0-9a-fA-F-]{6,}/[^\s"'`<>]+?\.md)"""
)

# agy agentic-narration markers, split by what the prefix actually means:
#
#   _AGENTIC_SEARCH_PREFIXES — the model is "thinking out loud" / searching before
#   it reviews. This is HARMLESS PREAMBLE when a real review body follows. agy
#   often narrates one line ("I will look at the diff") and then returns a full
#   review; the legacy check looked only at the first line and rejected the whole
#   output, a false reject (issue #153). check_agentic_narration now downgrades
#   these to a pass when a review-structure heading (## Verdict / ## Summary /
#   ## Findings) is present, and lets the verdict / changed-files checks decide.
#
#   _BRAIN_POINTER_PREFIXES — the canonical openers for the brain-artifact detour
#   (issue #153 mode 2): agy narrates "I have written my analysis to <brain
#   artifact>" and the real review is NOT on stdout. These hard-fail ONLY when an
#   actual brain-artifact path is present in the text (rescue_brain_artifact, run
#   before validate, recovers the content when the pointer resolves; if it could
#   not, the stdout body is a pointer + narration, never a review). Without a
#   pointer path, the same phrases ("I have finished reviewing ...") are ordinary
#   completion-phrase openers on a real review, so check_agentic_narration treats
#   them like an agentic-search preamble — downgradable when a review body follows.
_AGENTIC_SEARCH_PREFIXES = (
    "i will ",
    "i'll ",
    "i am going to ",
    "i'm going to ",
    "i am waiting",
    "i'm waiting",
    "let me ",
    "first, i ",
    "searching for ",
    "looking for ",
)
_BRAIN_POINTER_PREFIXES = (
    "i have written",
    "i've written",
    "i have finished",
    "i've finished",
    "i have completed",
)
# Preserved union for callers/tests that iterate the full marker set.
_NARRATION_PREFIXES = _AGENTIC_SEARCH_PREFIXES + _BRAIN_POINTER_PREFIXES

# Agentic tool-call markers (PR #303 signature).
_TOOLCALL_PREFIXES = ("call:", "tool_use:")

# A review-structure heading anywhere in the output: the signal that a real review
# followed the leading narration. Requires a markdown ATX heading line whose text
# mentions verdict / summary / findings (matches both the R1 format — ## Summary /
# ## Findings / ## Verdict — and the R2 format — ## Cross-review verdict / ## New
# findings / ## Final verdict). A bare substring is intentionally NOT enough, so
# prose like "I will determine the verdict" cannot fake a review body.
_REVIEW_BODY = re.compile(
    r"(?mi)^[ \t]{0,3}#{1,6}[ \t].*\b(?:verdicts?|summar(?:y|ies)|findings?)\b"
)

# Fenced code blocks are stripped before the heading search: the review prompt
# template itself contains "## Summary" / "## Findings" / "## Verdict" headings,
# so agy echoing a prompt/diff fragment inside a ``` (or ~~~) fence must NOT be
# read as a real review heading (it would let agentic-search narration + an echoed
# fenced heading falsely pass). A real review's headings are top-level markdown,
# never fenced, so stripping fences cannot hide a genuine review body.
_FENCE_BLOCK = re.compile(r"(?ms)^[ \t]{0,3}(`{3,}|~{3,}).*?^[ \t]{0,3}\1[ \t]*$")

_TIMEOUT_MARKERS = (
    "error: timed out",
    "timed out waiting for response",
)

# A source-file reference inside review prose: either a path with a directory
# separator and an extension, or a bare filename with a known source extension.
# Used by check_changed_files to tell "clean review with no file refs" (pass)
# apart from "review that discusses files, none of them ours" (wrong target).
#
# The path branch uses ``[\w.\-]+(?:/[\w.\-]+)+`` — ``/`` appears ONLY as the
# explicit separator, never inside an adjacent char class. The earlier form
# ``[\w.\-/]+/[\w.\-/]+`` let two quantifiers both consume ``/``, giving
# super-linear backtracking on long slash-runs (a ReDoS on model-controlled
# review text up to the 256KB cap). This form backtracks linearly.
_SRC_EXT = (
    "py|ts|tsx|js|jsx|go|rs|java|rb|md|sh|ya?ml|json|sql|toml|c|h|cpp|hpp|kt|swift|dart|php|cs"
)
_FILE_REF = re.compile(
    r"[\w.\-]+(?:/[\w.\-]+)+\.\w{1,5}\b"  # a path: seg(/seg)+.ext
    rf"|\b[\w\-]+\.(?:{_SRC_EXT})\b",  # a bare filename with a known extension
    re.IGNORECASE,
)


def find_brain_pointer(text: str) -> str | None:
    """Return the first brain-artifact path mentioned in ``text``, or None."""
    m = _BRAIN_POINTER.search(text)
    return m.group("path") if m else None


def _expand_home(path: str, home: Path) -> Path:
    if path == "~":
        return home
    if path.startswith("~/"):
        return home / path[2:]
    return Path(path)


def _under_brain_dir(artifact: Path, home: Path) -> bool:
    """True if ``artifact`` resolves under ~/.gemini/antigravity-cli/brain."""
    brain_root = (home / ".gemini" / "antigravity-cli" / "brain").resolve()
    resolved = artifact.resolve()
    return brain_root == resolved or brain_root in resolved.parents


def rescue_brain_artifact(text: str, home: Path) -> tuple[str, str | None]:
    """Resolve a brain-artifact pointer to its real content.

    Returns ``(content, rescued_from_path)``. When no pointer is found, the
    pointer resolves outside the legitimate brain dir, the artifact is missing
    (dangling pointer), or it is empty, returns ``(text, None)`` so the caller
    falls through to the normal fail-loud checks on the original text.

    Raises ``OSError`` when the artifact *exists* but cannot be read (e.g. a
    permission error): that is an artifact-present-but-blocked condition the
    caller must surface loudly (exit 2), not silently validate the pointer text.
    """
    pointer = find_brain_pointer(text)
    if pointer is None:
        return text, None
    artifact = _expand_home(pointer, home)
    # Only trust pointers under the real brain dir — never read an arbitrary
    # absolute path the model happened to print.
    if not _under_brain_dir(artifact, home):
        return text, None
    try:
        content = artifact.read_text(encoding="utf-8")
    except FileNotFoundError:
        return text, None  # dangling pointer: fall through to fail-loud checks
    # any other OSError (PermissionError, IsADirectoryError, ...) propagates
    if not content.strip():
        return text, None
    return content, pointer


def check_timeout(text: str) -> str | None:
    """Flag agentic-search timeouts.

    Anchored to line starts (like check_agentic_narration) so a legitimate
    review whose *body* quotes "Error: timed out ..." is not mistaken for an
    actual timeout — agy's real timeout output is the marker as a standalone
    leading/trailing line.
    """
    for line in text.splitlines():
        stripped = line.strip().lower()
        for marker in _TIMEOUT_MARKERS:
            if stripped.startswith(marker):
                return (
                    f"output line starts with timeout marker ({marker!r}) — "
                    "agentic search exceeded --print-timeout"
                )
    return None


def first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def has_review_body(text: str) -> bool:
    """True if ``text`` has a review-structure heading (## Verdict/Summary/Findings).

    Fenced code blocks are stripped first so a heading echoed inside a ``` fence
    (the prompt template contains these exact headings) does not count as a real
    review body.
    """
    return _REVIEW_BODY.search(_FENCE_BLOCK.sub("", text)) is not None


def check_agentic_narration(text: str) -> str | None:
    """Flag output that is agentic narration, a tool-call, or a brain-pointer detour.

    Tool-call openers are always a hard fail. A brain-pointer opener is a hard
    fail only when an actual brain-artifact path is present (the real review is in
    the artifact, not on stdout, and rescue could not recover it); without a
    pointer path it is an ordinary completion-phrase opener, handled like the
    agentic-search case below.

    An agentic-search opener ("I will ...", "Let me ...") — and a pointer-less
    brain-phrase opener — fails only when NO review body follows. agy often
    narrates a one-line preamble and then returns a complete review (issue #153
    false reject); when a ## Verdict / ## Summary / ## Findings heading is present
    the preamble is harmless, so this returns None and the verdict / changed-files
    checks decide the outcome.
    """
    first = first_nonblank_line(text)
    low = first.lower()
    for prefix in _TOOLCALL_PREFIXES:
        if low.startswith(prefix):
            return (
                f"output starts with agentic tool-call marker ({first[:60]!r}) "
                "— agentic mode triggered"
            )
    is_brain_opener = any(low.startswith(p) for p in _BRAIN_POINTER_PREFIXES)
    if is_brain_opener and find_brain_pointer(text) is not None:
        return (
            f"output starts with brain-artifact narration ({first[:60]!r}) — "
            "real review is in a brain artifact, not on stdout (rescue failed)"
        )
    # agentic-search opener, or a pointer-less brain-phrase opener: downgrade to a
    # pass when a real review body follows the preamble.
    if any(low.startswith(p) for p in _NARRATION_PREFIXES):
        if has_review_body(text):
            return None  # narration was harmless preamble; a review followed
        return (
            f"output starts with agentic narration ({first[:60]!r}) — model "
            "entered file-search mode instead of reviewing"
        )
    return None


def check_verdict(text: str) -> str | None:
    """Require a Verdict section (R1 raw markdown / R2 markdown)."""
    if "verdict" not in text.lower():
        return "output has no Verdict section — incomplete or wrong-format review"
    return None


def load_changed_files(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def check_changed_files(text: str, changed: list[str]) -> str | None:
    """Content sanity: detect a review that targeted the WRONG files.

    Defence-in-depth against the wrong-target failure mode (agy reviewed a stale
    input from a previous session). The check is deliberately biased toward NOT
    blocking legitimate reviews — it fails only when the review *references files*
    yet none of them are the changed paths:

    - references a changed path (full path) or basename  -> pass (right target)
    - references no file at all (e.g. a terse clean LGTM) -> pass (cannot be
      wrong-target; nothing file-specific to be wrong about)
    - references file paths but none are ours             -> fail (wrong target)

    An empty changed list is treated as "nothing to check" and never blocks.
    Residual gap (accepted, defence-in-depth): a stale review of a *different*
    module in the *same* repo that cites only a generic shared basename
    (``service.py``) still passes — the primary defences (inline prompt + scratch
    hygiene) prevent that input from reaching the model in the first place.
    """
    if not changed:
        return None
    if any(path in text for path in changed):
        return None
    basenames = {path.rsplit("/", 1)[-1] for path in changed if path}
    if any(base and base in text for base in basenames):
        return None
    if not _FILE_REF.search(text):
        return None  # no file references at all -> not a wrong-target review
    sample = ", ".join(sorted(changed)[:3])
    return (
        f"output references files but none of the {len(changed)} changed paths "
        f"({sample}) — likely reviewed the WRONG target"
    )


def validate(
    content: str,
    *,
    require_verdict: bool,
    changed_files: list[str] | None,
) -> list[str]:
    """Run all enabled checks and return the list of failure messages."""
    errors: list[str] = []
    for check in (check_timeout, check_agentic_narration):
        err = check(content)
        if err:
            errors.append(err)
    if require_verdict:
        err = check_verdict(content)
        if err:
            errors.append(err)
    if changed_files is not None:
        err = check_changed_files(content, changed_files)
        if err:
            errors.append(err)
    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-loud validation + brain-artifact rescue for agy output."
    )
    parser.add_argument(
        "--raw",
        required=True,
        type=Path,
        help="agy raw output file (rewritten in place after a brain rescue)",
    )
    parser.add_argument(
        "--changed-files",
        type=Path,
        default=None,
        help="changed-files.txt for the wrong-target content-sanity check",
    )
    parser.add_argument(
        "--require-verdict",
        action="store_true",
        help="fail when the output has no Verdict section",
    )
    parser.add_argument(
        "--label",
        default="agy review",
        help="label prefixed to log messages",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="override HOME for brain-artifact resolution (testing only)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    home = args.home or Path.home()

    try:
        text = args.raw.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[FAIL] {args.label}: cannot read {args.raw}: {e}", file=sys.stderr)
        return 2

    try:
        content, rescued_from = rescue_brain_artifact(text, home)
    except OSError as e:
        print(
            f"[FAIL] {args.label}: brain artifact present but unreadable: {e}",
            file=sys.stderr,
        )
        return 2
    if rescued_from is not None:
        try:
            args.raw.write_text(content, encoding="utf-8")
        except OSError as e:
            print(
                f"[FAIL] {args.label}: brain rescue read OK but rewrite of {args.raw} failed: {e}",
                file=sys.stderr,
            )
            return 2
        print(
            f"[WARN] {args.label}: rescued review from brain artifact {rescued_from}",
            file=sys.stderr,
        )

    changed: list[str] | None = None
    if args.changed_files is not None:
        try:
            changed = load_changed_files(args.changed_files)
        except OSError as e:
            print(
                f"[FAIL] {args.label}: cannot read changed-files {args.changed_files}: {e}",
                file=sys.stderr,
            )
            return 2

    errors = validate(
        content,
        require_verdict=args.require_verdict,
        changed_files=changed,
    )
    if errors:
        for err in errors:
            print(f"[FAIL] {args.label}: {err}", file=sys.stderr)
        return 1

    print(f"[OK] {args.label}: output passed fail-loud validation", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
