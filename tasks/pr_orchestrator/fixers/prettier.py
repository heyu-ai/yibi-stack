"""Prettier auto-fixer。"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from .base import BaseFixer, FixOutcome, FixOutput

_PRETTIER_SIGNATURE = re.compile(r"Code style issues found|prettier", re.IGNORECASE)
_PRETTIER_EXTS = {".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".css"}


class PrettierFixer(BaseFixer):
    name = "prettier"

    def can_fix(self, log_text: str) -> bool:
        return bool(_PRETTIER_SIGNATURE.search(log_text))

    def run(self, repo_root: Path, pr_files: list[str]) -> FixOutput:
        # Only process existing target-extension files (pr_diff_files may include deleted files)
        target_files = [
            f for f in pr_files if Path(f).suffix in _PRETTIER_EXTS and (repo_root / f).is_file()
        ]
        if not target_files:
            return FixOutput(outcome=FixOutcome.no_change)

        result = subprocess.run(  # nosec B603 B607
            ["npx", "-y", "prettier", "--write", *target_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        if result.returncode != 0:
            return FixOutput(outcome=FixOutcome.failed, error=result.stderr[:500])

        diff = subprocess.run(  # nosec B603 B607
            ["git", "diff", "--name-only", *target_files],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        changed = [f for f in diff.stdout.splitlines() if f.strip()]
        if not changed:
            return FixOutput(outcome=FixOutcome.no_change)
        return FixOutput(outcome=FixOutcome.applied, files_changed=changed)
