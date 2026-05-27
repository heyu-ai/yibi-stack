"""Fixer abstract base class。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class FixOutcome(StrEnum):
    applied = "applied"
    no_change = "no_change"
    failed = "failed"


@dataclass
class FixOutput:
    """fixer.run() 的回傳值（與 models.FixResult StrEnum 不同，勿混淆）。"""

    outcome: FixOutcome
    files_changed: list[str] = field(default_factory=list)
    error: str = ""


class BaseFixer(ABC):
    name: str = ""

    @abstractmethod
    def can_fix(self, log_text: str) -> bool:
        """回傳 True 表示此 fixer 能處理 log_text 裡的失敗。"""

    @abstractmethod
    def run(self, repo_root: Path, pr_files: list[str]) -> FixOutput:
        """在 pr_files 範圍內執行 fix，回傳結果。"""
