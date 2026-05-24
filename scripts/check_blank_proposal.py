#!/usr/bin/env python3
"""Pre-commit gate：偵測 openspec proposal.md 是否仍含未替換的 HTML comment 佔位符。

spectra new change 產生的模板含 <!-- ... --> 佔位符，開發者填寫後不應再出現。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"<!--")
_PROPOSAL_GLOB = "openspec/changes/**/proposal.md"


def check_file(path: Path, from_index: bool = False) -> list[str]:
    """回傳含佔位符的行號清單；空清單表示通過。"""
    violations: list[str] = []
    try:
        if from_index:
            proc = subprocess.run(  # nosec B603 B607
                ["git", "show", f":{path}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                violations.append(f"  無法從 git index 讀取：{proc.stderr.strip()}")
                return violations
            lines = proc.stdout.splitlines()
        else:
            lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        violations.append(f"  無法讀取：{e}")
        return violations
    for lineno, line in enumerate(lines, start=1):
        if _PLACEHOLDER_RE.search(line):
            snippet = line.strip()[:80]
            violations.append(f"  行 {lineno}: {snippet}")
    return violations


def main(argv: list[str]) -> int:
    from_index = "--from-index" in argv
    args = [a for a in argv if a != "--from-index"]
    targets = [Path(p) for p in args] if args else list(Path(".").glob(_PROPOSAL_GLOB))

    failed: list[tuple[Path, list[str]]] = []
    for target in targets:
        violations = check_file(target, from_index=from_index)
        if violations:
            failed.append((target, violations))

    if not failed:
        return 0

    print("[FAIL] openspec proposal.md 仍含未填寫的 HTML comment 佔位符：", file=sys.stderr)
    for path, violations in failed:
        print(f"\n  {path}", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
    print(
        "\n  修復：用實際內容取代所有 <!-- ... --> 再重新 commit。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
