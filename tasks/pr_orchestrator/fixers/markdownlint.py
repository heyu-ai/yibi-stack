"""Markdownlint auto-fixer。"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from .base import BaseFixer, FixOutcome, FixOutput

_MD_SIGNATURE = re.compile(r"MD\d{3}/|markdownlint-cli2", re.IGNORECASE)


class MarkdownlintFixer(BaseFixer):
    name = "markdownlint"

    def can_fix(self, log_text: str) -> bool:
        return bool(_MD_SIGNATURE.search(log_text))

    def run(self, repo_root: Path, pr_files: list[str]) -> FixOutput:
        # Only process existing .md files (pr_diff_files may include deleted files)
        md_files = [f for f in pr_files if f.endswith(".md") and (repo_root / f).is_file()]
        if not md_files:
            return FixOutput(outcome=FixOutcome.no_change)

        result = subprocess.run(  # nosec B603 B607
            ["npx", "-y", "markdownlint-cli2", "--fix", *md_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        # markdownlint-cli2 --fix exits with 1 when lint errors were found and fixed,
        # 0 when no issues exist. Exit codes > 1 indicate a tool crash.
        if result.returncode > 1:
            return FixOutput(outcome=FixOutcome.failed, error=result.stderr[:500])

        diff = subprocess.run(  # nosec B603 B607
            ["git", "diff", "--name-only", *md_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        changed = [f for f in diff.stdout.splitlines() if f.strip()]
        if not changed:
            return FixOutput(outcome=FixOutcome.no_change)
        return FixOutput(outcome=FixOutcome.applied, files_changed=changed)
