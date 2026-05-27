"""Markdownlint auto-fixer。"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from .base import BaseFixer, FixOutcome, FixResult

_MD_SIGNATURE = re.compile(r"MD\d{3}/|markdownlint-cli2", re.IGNORECASE)


class MarkdownlintFixer(BaseFixer):
    name = "markdownlint"

    def can_fix(self, log_text: str) -> bool:
        return bool(_MD_SIGNATURE.search(log_text))

    def run(self, repo_root: Path, pr_files: list[str]) -> FixResult:
        md_files = [f for f in pr_files if f.endswith(".md")]
        if not md_files:
            return FixResult(outcome=FixOutcome.no_change)

        subprocess.run(  # nosec B603 B607
            ["npx", "markdownlint-cli2", "--fix", *md_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        # markdownlint-cli2 --fix exits non-zero even when fixes applied; check git diff
        diff = subprocess.run(  # nosec B603 B607
            ["git", "diff", "--name-only", *md_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        changed = [f for f in diff.stdout.splitlines() if f.strip()]
        if not changed:
            return FixResult(outcome=FixOutcome.no_change)
        return FixResult(outcome=FixOutcome.applied, files_changed=changed)
