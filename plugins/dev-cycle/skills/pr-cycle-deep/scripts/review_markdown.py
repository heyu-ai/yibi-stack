"""用 CommonMark token 解析彙整報告的來源欄位與 owned audit 區段。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it.token import Token

START = "<!-- code-review-scope:start -->"
END = "<!-- code-review-scope:end -->"
SOURCE = re.compile(r"Code-review source: (CR-[1-9][0-9]*(?:, CR-[1-9][0-9]*)*)[ \t]*")
SOURCE_CANDIDATE = re.compile(r"^code-review[ \t]+source[ \t]*[:：]", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ParsedReport:
    """保留來源順序及重複項；audit 邊界使用原文的字元位置。"""

    sources: tuple[str, ...]
    audit_span: tuple[int, int] | None


def parse_report(text: str) -> ParsedReport:
    """解析正文；audit 不計來源，但仍檢查欄位、marker 與區塊是否完整。"""
    from markdown_it import MarkdownIt

    # CommonMark 只正規化 CRLF／CR；不能用 splitlines 把其他 Unicode 字元也當換行。
    line_starts = [0]
    line_ends = []
    for newline in re.finditer(r"\r\n?|\n", text):
        line_ends.append(newline.start())
        line_starts.append(newline.end())
    line_ends.append(len(text))

    sources: list[str] = []
    parents: list[Token] = []
    audit_start: int | None = None
    audit_span: tuple[int, int] | None = None
    in_audit = False
    parser = MarkdownIt("commonmark")
    for token in parser.parse(text):
        if token.nesting == 1:
            # parser 達到安全上限時會略過更深的內容；不可把省略誤認為零來源。
            if token.level + 1 >= parser.options["maxNesting"]:
                raise ValueError("final.md 的巢狀層級達到 parser 安全上限")
            parents.append(token)
            continue
        if token.nesting == -1:
            parents.pop()
            continue
        if token.type == "fence":
            # map 包含開頭與（若有）結尾 delimiter；content 只包含內文。
            # 用 parser 的行數差辨別容器結束／EOF 隱式關閉，不重做縮排或 fence 文法。
            content_lines = token.content.count("\n") + int(
                bool(token.content) and not token.content.endswith("\n")
            )
            if token.map is None or token.map[1] - token.map[0] != content_lines + 2:
                raise ValueError("final.md 的 code fence 未關閉")
        elif token.type == "html_block":
            if token.content.lstrip().startswith("<!--") and "-->" not in token.content:
                raise ValueError("final.md 的 HTML 註解未關閉")
            if token.map is None or token.map[1] - token.map[0] != 1:
                continue
            line = token.map[0]
            marker = text[line_starts[line] : line_ends[line]].strip(" \t")
            if marker not in (START, END) or token.content.strip() != marker:
                continue
            if marker == START:
                if audit_start is not None:
                    raise ValueError("final.md 的 scope audit markers 重複")
                audit_start = line_starts[line]
                in_audit = True
            else:
                if not in_audit or audit_start is None:
                    raise ValueError("final.md 的 scope audit markers 順序錯誤")
                audit_span = (audit_start, line_ends[line])
                in_audit = False
        elif token.type == "inline":
            # 用可見文字找欄位候選，讓粗體／連結等近似寫法失敗，而非偷偷漏計。
            # code_inline 與 HTML 註解是引用／隱藏內容，不構成欄位標籤。
            visible = "".join(
                child.content
                if child.type == "text"
                else "\n"
                if child.type in ("softbreak", "hardbreak")
                else ""
                for child in token.children or ()
            )
            if not SOURCE_CANDIDATE.search(visible):
                continue
            match = SOURCE.fullmatch(token.content)
            if (
                match is None
                or len(parents) < 2
                or parents[-1].type != "paragraph_open"
                or parents[-2].type != "list_item_open"
                or parents[-2].markup != "-"
                or token.map is None
                or parents[-2].map is None
                or token.map[0] != parents[-2].map[0]
                or any(child.type != "text" for child in token.children or ())
            ):
                raise ValueError(f"來源列格式錯誤：{token.content}")
            if not in_audit:
                sources.extend(match[1].split(", "))
    if in_audit:
        raise ValueError("final.md 的 scope audit markers 不完整")
    return ParsedReport(tuple(sources), audit_span)
