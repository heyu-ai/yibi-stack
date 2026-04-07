---
globs: tasks/**/parsers/**
---
# Parser 擴充規範

## 目錄結構

```text
parsers/
├── __init__.py
├── base.py        # Abstract base class + ParseResult dataclass
├── registry.py    # _REGISTRY dict + get_parser / list_parsers / detect_parser
├── generic.py     # GenericParser（fallback）
└── <name>.py      # 每個 parser 獨立一個檔案
```

## Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ParseResult:
    rows: list[ParsedRow]
    parser_name: str
    warnings: list[str]

class BaseBillingParser(ABC):
    name: str = ""  # 必須在子類設定

    @abstractmethod
    def parse(self, pdf_path: Path) -> ParseResult: ...

    def can_parse(self, text_content: str) -> bool:
        """可選：用於自動偵測。預設回傳 False。"""
        return False
```

## 新增 Parser

1. 建立 `parsers/<name>.py`，繼承 base class，設定 `name` 屬性
2. 實作 `parse()`，可選實作 `can_parse()`
3. 在 `registry.py` 的 `_REGISTRY` 加入新 parser

```python
# parsers/cathay_cc.py
class CathayCCParser(BaseBillingParser):
    name = "cathay_cc"

    def parse(self, pdf_path: Path) -> ParseResult:
        import pdfplumber  # 延遲 import
        ...
```

```python
# registry.py
_REGISTRY: dict[str, type[BaseBillingParser]] = {
    "cathay_cc": CathayCCParser,
    "generic": GenericParser,
}
```

## Registry API 規範

- `get_parser(name)` — 找不到時靜默 fallback 到 `GenericParser`，不 raise
- `list_parsers()` — 回傳所有已註冊 parser 名稱
- `detect_parser(content)` — 依序呼叫各 parser 的 `can_parse()`，回傳第一個匹配的

## Parser 內部資料

用 `@dataclass`（不用 Pydantic）：輕量、不需序列化到 JSON。
PDF 庫（`pikepdf`, `pdfplumber`, `tabula`）在 method body 內 import。
