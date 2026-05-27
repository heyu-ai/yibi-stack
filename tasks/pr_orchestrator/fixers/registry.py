"""Fixer registry：按順序嘗試所有 fixer。"""

from __future__ import annotations

from .base import BaseFixer
from .markdownlint import MarkdownlintFixer
from .prettier import PrettierFixer
from .ruff_fixer import RuffFixer

_FIXERS: list[BaseFixer] = [
    MarkdownlintFixer(),
    RuffFixer(),
    PrettierFixer(),
]


def all_fixers() -> list[BaseFixer]:
    return list(_FIXERS)


def fixers_for(log_text: str) -> list[BaseFixer]:
    return [f for f in _FIXERS if f.can_fix(log_text)]
