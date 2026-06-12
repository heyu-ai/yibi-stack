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
  - fail-loud checks (fix 3): timeout marker, agentic-narration prefix, missing
    Verdict section, and content sanity (must mention >=1 changed file path).

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
# ~/.gemini/antigravity-cli/brain/<uuid>/<name>.md and prints only a pointer.
# Match a "~"- or "/"-anchored path containing /brain/<hexish>/ ending in .md.
_BRAIN_POINTER = re.compile(
    r"""(?P<path>[~/][^\s"'`<>]*?/brain/[0-9a-fA-F-]{6,}/[^\s"'`<>]+?\.md)"""
)

# agy agentic-narration markers: output whose first non-blank line starts with
# one of these is the model "thinking out loud" / searching, not a review.
_NARRATION_PREFIXES = (
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

# Agentic tool-call markers (PR #303 signature).
_TOOLCALL_PREFIXES = ("call:", "tool_use:")

_TIMEOUT_MARKERS = (
    "error: timed out",
    "timed out waiting for response",
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


def rescue_brain_artifact(text: str, home: Path) -> tuple[str, str | None]:
    """Resolve a brain-artifact pointer to its real content.

    Returns ``(content, rescued_from_path)``. When no pointer is found, or the
    artifact is missing / empty / unreadable, returns ``(text, None)`` so the
    caller falls through to the normal fail-loud checks on the original text.
    """
    pointer = find_brain_pointer(text)
    if pointer is None:
        return text, None
    artifact = _expand_home(pointer, home)
    try:
        content = artifact.read_text(encoding="utf-8")
    except OSError:
        return text, None
    if not content.strip():
        return text, None
    return content, pointer


def check_timeout(text: str) -> str | None:
    """Flag agentic-search timeouts."""
    low = text.lower()
    for marker in _TIMEOUT_MARKERS:
        if marker in low:
            return (
                f"output contains timeout marker ({marker!r}) — agentic search "
                "exceeded --print-timeout"
            )
    return None


def first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def check_agentic_narration(text: str) -> str | None:
    """Flag output that begins with agentic narration or tool-call markers."""
    first = first_nonblank_line(text)
    low = first.lower()
    for prefix in _NARRATION_PREFIXES:
        if low.startswith(prefix):
            return (
                f"output starts with agentic narration ({first[:60]!r}) — model "
                "entered file-search mode instead of reviewing"
            )
    for prefix in _TOOLCALL_PREFIXES:
        if low.startswith(prefix):
            return (
                f"output starts with agentic tool-call marker ({first[:60]!r}) "
                "— agentic mode triggered"
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
    """Content sanity: the review must mention at least one changed path.

    Guards against the wrong-target failure mode (agy reviewed a stale input
    from a different repo and returned valid-looking output). An empty list is
    treated as "nothing to check" and never blocks.
    """
    if not changed:
        return None
    for path in changed:
        if path in text:
            return None
        base = path.rsplit("/", 1)[-1]
        if base and base in text:
            return None
    sample = ", ".join(changed[:3])
    return (
        f"output mentions none of the {len(changed)} changed files "
        f"(e.g. {sample}) — likely reviewed the WRONG target"
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

    content, rescued_from = rescue_brain_artifact(text, home)
    if rescued_from is not None:
        try:
            args.raw.write_text(content, encoding="utf-8")
        except OSError as e:
            print(
                f"[FAIL] {args.label}: brain rescue read OK but rewrite of "
                f"{args.raw} failed: {e}",
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
                f"[FAIL] {args.label}: cannot read changed-files "
                f"{args.changed_files}: {e}",
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
