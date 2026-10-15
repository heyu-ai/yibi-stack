#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown-it-py==4.2.0"]
# ///
"""Capture setup's fetched base, then scope normalized /code-review findings.

setup-review-dir.sh owns fetch/remote policy and calls capture --base <object ID>.
filter --input <JSON file> never edits that input; owned output filenames are reserved.
The manifest freezes commit IDs, not mutable refs. Refresh only through setup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from review_markdown import END, START, parse_report

ACCEPTED = "code-review-filtered.json"
AUDIT = "code-review-scope.md"
CAPTURED = ("review-scope.json", "diff.patch", "changed-files.txt")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
LINE_SUFFIX = re.compile(r"(?::\d+(?::\d+)?(?:-\d+)?|#L\d+(?:-L?\d+)?)\Z")


class ScopeError(ValueError):
    """A review cannot safely be accepted."""


def git(root: Path | None, *args: str) -> bytes:
    result = subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=root, capture_output=True, check=False
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ScopeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def atomic_write(path: Path, data: bytes, *, readonly: bool = False) -> None:
    """Publish a complete artifact, including replacement of a prior readonly snapshot."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        if readonly:
            temporary.chmod(0o444)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def update_final(directory: Path, section: str | None) -> None:
    """Replace only our delimited section, leaving amplifier/other findings untouched."""
    final = directory / "final.md"
    if not final.exists():
        return
    # 直接解碼 bytes，避免 universal-newline 轉換改動其他 reviewer 的文字。
    text = final.read_bytes().decode("utf-8")
    span = parse_report(text).audit_span
    if span is not None:
        start, end = span
        replacement = section.rstrip("\r\n") if section is not None else ""
        text = text[:start] + replacement + text[end:]
    elif section is not None:
        text += ("" if not text or text.endswith("\n\n") else "\n\n") + section
    else:
        return
    atomic_write(final, text.encode("utf-8"))


def invalidate(directory: Path, *, capture: bool = False, final: bool = True) -> None:
    for name in (ACCEPTED, AUDIT, *(CAPTURED if capture else ())):
        (directory / name).unlink(missing_ok=True)
    if capture:
        (directory / "code-review.json").unlink(missing_ok=True)
    if final:
        update_final(directory, None)


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    # No rename pairing: both old and new names are reviewable, as are deleted paths.
    raw = git(root, "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}", "--")
    return sorted({os.fsdecode(item) for item in raw.split(b"\0") if item})


def warn_stale_main(root: Path, base: str) -> None:
    result = subprocess.run(  # nosec B603 B607
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads/main"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    # show-ref --quiet returns 1 for both absent and malformed refs. for-each-ref
    # reports broken refs on stderr, so never mistake that warning for absence.
    if result.returncode or result.stderr:
        raise ScopeError(f"cannot inspect refs/heads/main: {os.fsdecode(result.stderr).strip()}")
    if b"refs/heads/main" not in result.stdout.splitlines():
        return
    behind = int(git(root, "rev-list", "--count", f"refs/heads/main..{base}"))
    if behind:
        print(
            f"[WARN] local refs/heads/main is behind fetched base by {behind} commit(s); "
            "review scope uses the fetched base, not local main",
            file=sys.stderr,
        )


def capture_scope(root: Path, directory: Path, base: str) -> None:
    if not SHA.fullmatch(base):
        raise ScopeError("capture --base must be the full fetched commit object ID")
    head = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    warn_stale_main(root, base)
    paths = changed_paths(root, base, head)
    patch = git(root, "diff", "--no-ext-diff", "--no-textconv", f"{base}...{head}", "--")
    names = git(root, "diff", "--no-renames", "--name-only", f"{base}...{head}", "--")
    if git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise ScopeError("HEAD moved during scope capture; rerun setup-review-dir.sh")
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / "diff.patch", patch)
    atomic_write(directory / "changed-files.txt", names)
    atomic_write(
        directory / "review-scope.json",
        json_bytes({"version": 1, "base": base, "head": head, "changed_paths": paths}),
        readonly=True,
    )


def load_scope(directory: Path) -> dict[str, Any]:
    scope = json.loads((directory / "review-scope.json").read_text(encoding="utf-8"))
    if (
        not isinstance(scope, dict)
        or type(scope.get("version")) is not int
        or scope["version"] != 1
    ):
        raise ScopeError("review-scope.json must be a version 1 object; rerun setup-review-dir.sh")
    for name in ("base", "head"):
        if not isinstance(scope.get(name), str) or not SHA.fullmatch(scope[name]):
            raise ScopeError(f"review-scope.json has invalid {name}")
    paths = scope.get("changed_paths")
    if not isinstance(paths, list) or any(
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\0" in path
        or ".." in path.split("/")
        or str(PurePosixPath(path)) != path
        for path in paths
    ):
        raise ScopeError("review-scope.json has invalid canonical changed_paths")
    if paths != sorted(set(paths)):
        raise ScopeError("review-scope.json changed_paths must be sorted and unique")
    return scope


def load_review(path: Path) -> dict[str, Any]:
    review = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(review, dict):
        raise ScopeError("review input must be an object with verdict, summary, findings")
    if review.get("verdict") not in ("LGTM", "NEEDS_CHANGES"):
        raise ScopeError("review verdict must be LGTM or NEEDS_CHANGES")
    if not isinstance(review.get("summary"), str) or not review["summary"].strip():
        raise ScopeError("review summary must be a nonempty string")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ScopeError("review findings must be a list")
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict) or not isinstance(finding.get("file"), str):
            raise ScopeError(f"findings[{index}] must be an object with a string file")
    return review


def canonical_file(value: str, root: Path, allowed: set[str]) -> tuple[str | None, str | None]:
    if not value or "\0" in value:
        return None, "empty or invalid file path"
    if ".." in value.split("/"):
        return None, "path traversal is not allowed"
    path = PurePosixPath(value)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None, "absolute path is outside the repository"
    if str(path) == ".":
        return None, "file path does not resolve to a repository file"
    raw_path = str(path)
    if raw_path in allowed:
        return raw_path, None
    if LINE_SUFFIX.search(value):
        return None, "line-suffixed file path; use separate line_start/line_end fields"
    return raw_path, "file is not in the captured changed_paths (or cannot resolve exactly)"


def audit_section(scope: dict[str, Any], dropped: list[dict[str, Any]]) -> str:
    lines = [
        START,
        "## Code-review scope audit",
        "",
        f"Base: `{scope['base']}`; HEAD: `{scope['head']}`.",
        "",
        f"{len(dropped)} out-of-scope discarded. Only code-review-filtered.json feeds fixes.",
        "",
    ]
    for item in dropped:
        # Preserve JSON values while preventing a rejected finding from closing the fence
        # or injecting our delimiter into final.md.
        data = json_bytes(item).decode().replace("`", "\\u0060").replace("<", "\\u003c")
        lines.extend(["```json", data.rstrip("\n"), "```", ""])
    return "\n".join([*lines, END, ""])


def filter_review(root: Path, directory: Path, input_path: Path) -> None:
    if input_path.resolve() in {
        (directory / name).resolve() for name in (ACCEPTED, AUDIT, "final.md", *CAPTURED)
    }:
        raise ScopeError("--input must not use a reserved scope/output artifact path")
    scope = load_scope(directory)
    if git(root, "rev-parse", "HEAD").decode().strip() != scope["head"]:
        raise ScopeError("HEAD moved since scope capture; rerun setup-review-dir.sh and review")
    review = load_review(input_path)
    allowed = set(scope["changed_paths"])
    accepted = []
    dropped = []
    for index, finding in enumerate(review["findings"]):
        canonical, reason = canonical_file(finding["file"], root, allowed)
        if reason is not None:
            dropped.append({"index": index, "reason": reason, "finding": finding})
        else:
            accepted.append({**finding, "file": canonical})
    filtered = {**review, "findings": accepted}
    section = audit_section(scope, dropped)
    atomic_write(directory / AUDIT, section.encode("utf-8"))
    update_final(directory, section)
    if git(root, "rev-parse", "HEAD").decode().strip() != scope["head"]:
        raise ScopeError("HEAD moved during filtering; rerun setup-review-dir.sh and review")
    atomic_write(directory / ACCEPTED, json_bytes(filtered))
    print(json_bytes(filtered).decode(), end="")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ScopeError(message)


def main() -> int:
    if not Path(__file__).resolve().with_suffix(".py.lock").is_file():
        print("[FAIL] review-scope 缺少 script lockfile；請更新完整 skill", file=sys.stderr)
        return 1
    directory = None
    reset_capture = False
    try:
        root = Path(os.fsdecode(git(None, "rev-parse", "--show-toplevel")).rstrip("\n")).resolve()
        directory = root / ".pr-review"
        # Argument failures invalidate in the exception handler; --help is read-only.
        reset_capture = len(sys.argv) > 1 and sys.argv[1] in ("reset", "capture")
        parser = Parser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("reset", help="invalidate the previous capture and accepted findings")
        capture = commands.add_parser("capture", help="freeze setup's fetched object ID")
        capture.add_argument("--base", required=True)
        filtered = commands.add_parser("filter", help="scope a normalized review envelope")
        filtered.add_argument("--input", type=Path, required=True)
        args = parser.parse_args()
        invalidate(directory, capture=reset_capture, final=reset_capture)
        if args.command == "capture":
            capture_scope(root, directory, args.base)
        elif args.command == "filter":
            filter_review(root, directory, args.input)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        if directory is not None:
            try:
                invalidate(directory, capture=reset_capture)
            except (OSError, ValueError) as cleanup_error:
                print(f"[FAIL] invalidating scope output: {cleanup_error}", file=sys.stderr)
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
