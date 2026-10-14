#!/usr/bin/env python3
"""Step 5b 前核對 Step 2 收下的 findings 是否全數列入 final.md。"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from review_scope import ACCEPTED, END, START, load_review

SOURCE = re.compile(r" {0,3}- Code-review source: (CR-[1-9]\d*(?:, CR-[1-9]\d*)*)\s*")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")


def listed_sources(text: str) -> list[str]:
    """只計算正文來源列，不把 scope audit 或 fenced code 當成 findings。"""
    if not text.strip():
        raise ValueError("final.md 不可為空")
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
            raise ValueError("final.md 的 scope audit markers 不完整")
        text = text[: text.index(START)] + text[text.index(END) + len(END) :]
    sources = []
    fence = ""
    for line in text.splitlines():
        delimiter = FENCE.fullmatch(line)
        if fence:
            if (
                delimiter
                and delimiter[1][0] == fence[0]
                and len(delimiter[1]) >= len(fence)
                and not delimiter[2].strip()
            ):
                fence = ""
            continue
        if delimiter:
            fence = delimiter[1]
            continue
        if match := SOURCE.fullmatch(line):
            sources.extend(match[1].split(", "))
        elif line.lstrip().startswith("- Code-review source:"):
            raise ValueError(f"來源列格式錯誤：{line.strip()}")
    if fence:
        raise ValueError("final.md 的 code fence 未關閉")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=Path(".pr-review"))
    args = parser.parse_args()
    try:
        findings = load_review(args.review_dir / ACCEPTED)["findings"]
        sources = listed_sources((args.review_dir / "final.md").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] review-count 輸入錯誤：{exc}", file=sys.stderr)
        return 2
    expected = {f"CR-{index}" for index in range(1, len(findings) + 1)}
    counts = Counter(sources)
    missing = sorted(expected - counts.keys())
    unexpected = sorted(counts.keys() - expected)
    duplicates = sorted(source for source, count in counts.items() if count > 1)
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
