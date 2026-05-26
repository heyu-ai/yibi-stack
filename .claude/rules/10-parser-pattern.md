---
globs: tasks/**/parsers/**
---
# Parser Extension Pattern

## Directory Structure

```text
parsers/
├── __init__.py
├── base.py        # Abstract base class + ParseResult dataclass
├── registry.py    # _REGISTRY dict + get_parser / list_parsers / detect_parser
├── generic.py     # GenericParser (fallback)
└── <name>.py      # one file per parser
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
    name: str = ""  # must be set in each subclass

    @abstractmethod
    def parse(self, pdf_path: Path) -> ParseResult: ...

    def can_parse(self, text_content: str) -> bool:
        """可選：用於自動偵測。預設回傳 False。"""
        return False
```

## Adding a Parser

1. Create `parsers/<name>.py`, inherit from the base class, set the `name` attribute
2. Implement `parse()`, optionally implement `can_parse()`
3. Add the new parser to `_REGISTRY` in `registry.py`

```python
# parsers/cathay_cc.py
class CathayCCParser(BaseBillingParser):
    name = "cathay_cc"

    def parse(self, pdf_path: Path) -> ParseResult:
        import pdfplumber  # deferred import
        ...
```

```python
# registry.py
_REGISTRY: dict[str, type[BaseBillingParser]] = {
    "cathay_cc": CathayCCParser,
    "generic": GenericParser,
}
```

## Registry API Rules

- `get_parser(name)` — silently falls back to `GenericParser` when not found; does not raise
- `list_parsers()` — returns all registered parser names
- `detect_parser(content)` — calls each parser's `can_parse()` in order; returns the first match

## Parser Internal Data

Use `@dataclass` (not Pydantic): lightweight and does not need to serialize to JSON.
PDF libraries (`pikepdf`, `pdfplumber`, `tabula`) are imported inside method bodies.
