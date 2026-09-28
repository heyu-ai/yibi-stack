"""HSBC: scripts/categorize_hsbc.py 的科目 enum 不變式與 classify_batch 回應解析測試。

Test ID 規則見 .claude/rules/09-test-conventions.md。

core venv 沒有安裝 `anthropic` 與 `sqlalchemy`（屬 `ledger` extra），故載入模組前先以
`patch.dict(sys.modules, ...)` 塞入替身；`classify_batch` 以參數接收 client，
測試傳入假 client，只替換外部 API 邊界。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = REPO_ROOT / "scripts" / "categorize_hsbc.py"


def _load_module(source: str | None = None) -> ModuleType:
    """以替身 anthropic／sqlalchemy 載入腳本；`source` 可覆寫原始碼以測不變式。"""
    stubs = {"anthropic": MagicMock(), "sqlalchemy": MagicMock()}
    with patch.dict(sys.modules, stubs):
        if source is None:
            spec = importlib.util.spec_from_file_location(
                "categorize_hsbc_under_test", _SCRIPT_PATH
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        module = ModuleType("categorize_hsbc_mutated")
        exec(compile(source, str(_SCRIPT_PATH), "exec"), module.__dict__)  # nosec B102
        return module


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    return _load_module()


def _block(block_type: str, text: str = "") -> MagicMock:
    block = MagicMock()
    block.type = block_type
    block.text = text
    return block


def _client(stop_reason: str, content: list[Any]) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = MagicMock(stop_reason=stop_reason, content=content)
    return client


_TXNS = [
    {"id": "t1", "date": "2025-07-01", "desc": "NETFLIX", "amount": 390.0},
    {"id": "t2", "date": "2025-07-02", "desc": "中華電信", "amount": 1200.0},
]


class TestPromptCategoriesInvariant:
    def test_hsbc_dt_001_invariant_holds_today(self, mod: ModuleType) -> None:
        """HSBC-DT-001：enum 非空、數量等於 prompt 的條列行、每個都對得到 EXPENSE_ACCOUNTS。"""
        bullets = re.findall(r"^- ", mod.SYSTEM_PROMPT, re.MULTILINE)
        assert mod.PROMPT_CATEGORIES
        assert len(mod.PROMPT_CATEGORIES) == len(bullets)
        assert set(mod.PROMPT_CATEGORIES) <= set(mod.EXPENSE_ACCOUNTS)

    def test_hsbc_eg_002_malformed_bullet_fails_at_import(self) -> None:
        """HSBC-EG-002：prompt 條列行用半形冒號（regex 抓不到）時，載入即 raise。"""
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        anchor = "- 稅：稅款"
        assert source.count(anchor) == 1
        with pytest.raises(RuntimeError, match="PROMPT_CATEGORIES"):
            _load_module(source.replace(anchor, "- 稅: 稅款"))

    def test_hsbc_eg_003_unknown_category_fails_at_import(self) -> None:
        """HSBC-EG-003：prompt 列出 EXPENSE_ACCOUNTS 沒有的科目時，載入即 raise。"""
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        anchor = "- 稅：稅款"
        assert source.count(anchor) == 1
        with pytest.raises(RuntimeError, match="EXPENSE_ACCOUNTS"):
            _load_module(source.replace(anchor, "- 寵物：寵物用品"))


class TestClassifyBatch:
    def test_hsbc_st_004_thinking_block_before_text(self, mod: ModuleType) -> None:
        """HSBC-ST-004：thinking block 排在前面、結果亂序時，仍依 no 正確對應交易。"""
        payload = {
            "results": [{"no": 2, "category": "系統維運"}, {"no": 1, "category": "線上視頻"}]
        }
        client = _client("end_turn", [_block("thinking"), _block("text", json.dumps(payload))])
        assert mod.classify_batch(client, _TXNS) == {"t1": "線上視頻", "t2": "系統維運"}

    def test_hsbc_eg_005_missing_no_raises(self, mod: ModuleType) -> None:
        """HSBC-EG-005：回應缺編號時 raise，不以預設科目補位。"""
        payload = {"results": [{"no": 1, "category": "線上視頻"}]}
        client = _client("end_turn", [_block("text", json.dumps(payload))])
        with pytest.raises(RuntimeError, match="缺少"):
            mod.classify_batch(client, _TXNS)

    def test_hsbc_eg_006_non_end_turn_raises(self, mod: ModuleType) -> None:
        """HSBC-EG-006：stop_reason 不是 end_turn（即使有 text block）時 raise。"""
        payload = {
            "results": [{"no": 1, "category": "線上視頻"}, {"no": 2, "category": "系統維運"}]
        }
        client = _client("max_tokens", [_block("text", json.dumps(payload))])
        with pytest.raises(RuntimeError, match="max_tokens"):
            mod.classify_batch(client, _TXNS)

    def test_hsbc_eg_007_duplicate_no_raises(self, mod: ModuleType) -> None:
        """HSBC-EG-007：重複編號時 raise，不靜默以後者覆蓋前者。"""
        payload = {
            "results": [
                {"no": 1, "category": "線上視頻"},
                {"no": 1, "category": "書籍"},
                {"no": 2, "category": "系統維運"},
            ]
        }
        client = _client("end_turn", [_block("text", json.dumps(payload))])
        with pytest.raises(RuntimeError, match="重複"):
            mod.classify_batch(client, _TXNS)

    def test_hsbc_eg_008_out_of_range_no_raises(self, mod: ModuleType) -> None:
        """HSBC-EG-008：編號超出交易範圍時 raise。"""
        payload = {
            "results": [
                {"no": 1, "category": "線上視頻"},
                {"no": 2, "category": "系統維運"},
                {"no": 9, "category": "書籍"},
            ]
        }
        client = _client("end_turn", [_block("text", json.dumps(payload))])
        with pytest.raises(RuntimeError, match="超出範圍"):
            mod.classify_batch(client, _TXNS)
