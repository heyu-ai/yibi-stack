"""擷取 SaaS invoice PDF 的金額與日期。

用法：
  uv run python scripts/extract_saas_invoice_amounts.py [VENDOR_DIR ...]

無參數時掃描 output/saas/invoice/ 下所有子目錄。
輸出格式：每個 PDF 印出檔名、開頭 300 字 snippet、含金額的行。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

_MONEY_RE = re.compile(
    r"(?:NT\$|US\$|USD|TWD|JPY|EUR|HK\$|HKD|\$|新台幣|台幣)[\s\xa0]*[\d,]+\.?\d*"
    r"|[\d,]+\.\d{2}[\s\xa0]*(?:USD|TWD|JPY|EUR|HKD)"
)

_DEFAULT_ROOT = Path("output/saas/invoice")


def extract(pdf_path: Path) -> tuple[str, str]:
    """回傳 (text_snippet, money_lines)。"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception as e:  # noqa: BLE001
        return (f"[ERROR] {e}", "")

    matches = [line.strip() for line in text.split("\n") if _MONEY_RE.search(line)]
    snippet = text[:300].replace("\n", " | ")
    return (snippet, " || ".join(matches[:8]))


def iter_pdfs(roots: list[Path]) -> list[Path]:
    """收集所有 PDF 檔案路徑，遞迴搜尋指定目錄。"""
    results: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".pdf":
            results.append(root)
        elif root.is_dir():
            results.extend(sorted(root.rglob("*.pdf")))
            results.extend(sorted(root.rglob("*.PDF")))
    return sorted(set(results))


def main(argv: list[str]) -> int:
    if argv:
        roots = [Path(a) for a in argv]
    else:
        if not _DEFAULT_ROOT.exists():
            print(f"[FAIL] 預設目錄不存在：{_DEFAULT_ROOT}", file=sys.stderr)
            print("請傳入 vendor 目錄或 PDF 路徑作為參數", file=sys.stderr)
            return 1
        roots = [_DEFAULT_ROOT]

    pdfs = iter_pdfs(roots)
    if not pdfs:
        print(f"[INFO] 在 {roots} 找不到任何 PDF", file=sys.stderr)
        return 1

    for p in pdfs:
        snippet, money = extract(p)
        print(f"=== {p.relative_to(p.parent.parent) if p.parent.parent.exists() else p.name} ===")
        print(f"  snippet: {snippet}")
        print(f"  amounts: {money}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
