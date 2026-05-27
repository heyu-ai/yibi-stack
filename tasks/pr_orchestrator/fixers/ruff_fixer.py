"""Ruff lint + format auto-fixer。"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from .base import BaseFixer, FixOutcome, FixOutput

_RUFF_SIGNATURE = re.compile(
    r"ruff\s+check|ruff\s+format|\bF\d{3}\b|\bE\d{3}\b|\bW\d{3}\b",
    re.IGNORECASE,
)


class RuffFixer(BaseFixer):
    name = "ruff"

    def can_fix(self, log_text: str) -> bool:
        return bool(_RUFF_SIGNATURE.search(log_text))

    def run(self, repo_root: Path, pr_files: list[str]) -> FixOutput:
        # Only process existing .py files (pr_diff_files may include deleted files)
        py_files = [f for f in pr_files if f.endswith(".py") and (repo_root / f).is_file()]
        if not py_files:
            return FixOutput(outcome=FixOutcome.no_change)

        # ruff check --fix exits non-zero when unfixable violations remain (expected);
        # non-zero exit is NOT treated as a tool crash — outcome is determined by git diff.
        subprocess.run(  # nosec B603 B607
            ["uv", "run", "ruff", "check", "--fix", *py_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        subprocess.run(  # nosec B603 B607
            ["uv", "run", "ruff", "format", *py_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        diff = subprocess.run(  # nosec B603 B607
            ["git", "diff", "--name-only", *py_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        changed = [f for f in diff.stdout.splitlines() if f.strip()]
        if not changed:
            return FixOutput(outcome=FixOutcome.no_change)
        return FixOutput(outcome=FixOutcome.applied, files_changed=changed)
