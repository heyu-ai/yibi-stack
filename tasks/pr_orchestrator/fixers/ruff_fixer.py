"""Ruff lint + format auto-fixer。"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from .base import BaseFixer, FixOutcome, FixResult

_RUFF_SIGNATURE = re.compile(
    r"ruff\s+check|ruff\s+format|\bF\d{3}\b|\bE\d{3}\b|\bW\d{3}\b",
    re.IGNORECASE,
)


class RuffFixer(BaseFixer):
    name = "ruff"

    def can_fix(self, log_text: str) -> bool:
        return bool(_RUFF_SIGNATURE.search(log_text))

    def run(self, repo_root: Path, pr_files: list[str]) -> FixResult:
        py_files = [f for f in pr_files if f.endswith(".py")]
        if not py_files:
            return FixResult(outcome=FixOutcome.no_change)

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
            return FixResult(outcome=FixOutcome.no_change)
        return FixResult(outcome=FixOutcome.applied, files_changed=changed)
