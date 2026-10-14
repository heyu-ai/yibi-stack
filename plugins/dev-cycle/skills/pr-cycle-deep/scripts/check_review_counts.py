#!/usr/bin/env python3
"""Step 5b 前核對 Step 2 收下的 findings 是否全數列入 final.md。"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from review_scope import ACCEPTED, END, START, load_review

SOURCE = re.compile(r"- Code-review source: (CR-[1-9]\d*(?:, CR-[1-9]\d*)*)\s*")
SOURCE_CANDIDATE = re.compile(r"(?:[-+*]|\d+[.)])?\s*[*_]*code-review\s+source\b", re.IGNORECASE)
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
LIST_ITEM = re.compile(r"([-+*]|\d{1,9}[.)])( +)(.*)")


def _without_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """保留 HTML 註解外的文字；fence 內容不經此處處理。"""
    visible = []
    while line:
        before, delimiter, after = line.partition("-->" if in_comment else "<!--")
        if not in_comment:
            visible.append(before)
        if not delimiter:
            break
        in_comment = not in_comment
        line = after
    return "".join(visible), in_comment


def listed_sources(text: str) -> list[str]:
    """按清單容器縮排辨識正文；audit 不計來源，但仍驗證 fence 結構。"""
    if not text.strip():
        raise ValueError("final.md 不可為空")
    sources = []
    fence = ""
    fence_indent = 0
    list_indents: list[int] = []
    in_comment = False
    in_audit = False
    seen_audit = False
    for raw_line in text.splitlines():
        line = raw_line.expandtabs(4)
        if fence:
            delimiter = None
            if not fence_indent or line[:fence_indent].isspace():
                delimiter = FENCE.fullmatch(line[fence_indent:])
            if (
                delimiter
                and delimiter[1][0] == fence[0]
                and len(delimiter[1]) >= len(fence)
                and not delimiter[2].strip()
            ):
                fence = ""
            continue
        # 只認正文中獨立成行的 owned marker，不把 inline/fenced 引用當成邊界。
        if not in_comment and line in (START, END):
            if line == START:
                if seen_audit:
                    raise ValueError("final.md 的 scope audit markers 重複")
                seen_audit = in_audit = True
            else:
                if not in_audit:
                    raise ValueError("final.md 的 scope audit markers 順序錯誤")
                in_audit = False
            list_indents.clear()
            continue
        line, in_comment = _without_comments(line, in_comment)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        while list_indents and indent < list_indents[-1]:
            list_indents.pop()
        container_indent = list_indents[-1] if list_indents else 0
        if indent - container_indent >= 4:
            # 相對清單容器再縮四格是 indented code，不是來源列。
            continue
        body = line[container_indent:]
        item = LIST_ITEM.fullmatch(line.lstrip(" "))
        if item:
            padding = len(item[2]) if len(item[2]) <= 4 else 1
            container_indent = indent + len(item[1]) + padding
            list_indents.append(container_indent)
            body = line[container_indent:]
        delimiter = FENCE.fullmatch(body)
        if delimiter and (delimiter[1][0] != "`" or "`" not in delimiter[2]):
            fence = delimiter[1]
            fence_indent = container_indent
            continue
        if in_audit:
            continue
        source_line = line.lstrip(" ")
        if match := SOURCE.fullmatch(source_line):
            sources.extend(match[1].split(", "))
        elif SOURCE_CANDIDATE.match(source_line):
            raise ValueError(f"來源列格式錯誤：{source_line}")
    if fence:
        raise ValueError("final.md 的 code fence 未關閉")
    if in_comment:
        raise ValueError("final.md 的 HTML 註解未關閉")
    if in_audit:
        raise ValueError("final.md 的 scope audit markers 不完整")
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
