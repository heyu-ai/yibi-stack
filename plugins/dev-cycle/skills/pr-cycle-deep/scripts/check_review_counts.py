#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown-it-py==4.2.0"]
# ///
"""進入 Step 5b／Step 6 前核對來源，包含 resume 與 Step 7 重新彙整。"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from review_markdown import parse_report
from review_scope import ACCEPTED, load_review


def main() -> int:
    if not Path(__file__).resolve().with_suffix(".py.lock").is_file():
        print("[FAIL] review-count 缺少 script lockfile；請更新完整 skill", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=Path(".pr-review"))
    args = parser.parse_args()
    try:
        findings = load_review(args.review_dir / ACCEPTED)["findings"]
        text = (args.review_dir / "final.md").read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("final.md 不可為空")
        sources = parse_report(text).sources
    except (OSError, ValueError) as exc:
        print(f"[FAIL] review-count 輸入錯誤：{exc}", file=sys.stderr)
        return 2
    expected = {f"CR-{index}" for index in range(1, len(findings) + 1)}
    counts = Counter(sources)
    missing = sorted(expected - counts.keys(), key=lambda source: (len(source), source))
    unexpected = sorted(counts.keys() - expected, key=lambda source: (len(source), source))
    duplicates = sorted(
        (source for source, count in counts.items() if count > 1),
        key=lambda source: (len(source), source),
    )
    summary = f"accepted={len(findings)} listed={len(sources)}"
    if missing or unexpected or duplicates:
        print(
            f"[FAIL] review-count {summary}; missing={missing}; "
            f"unexpected={unexpected}; duplicates={duplicates}",
            file=sys.stderr,
        )
        return 1
    print(f"[OK] review-count {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
