"""測試 AccountRegistry 的讀寫與冪等性。"""

from __future__ import annotations

import json
from pathlib import Path

from tasks.session_memory.registry import AccountRegistry


class TestAccountRegistry:
    def test_areg_dt_001_auto_register_new_account(self, tmp_path: Path) -> None:
        """AREG-DT-001：新帳號首次寫入，回傳 True。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        result = reg.auto_register("howie@gmail.com", "gemini")
        assert result is True
        data = json.loads(accounts_path.read_text())
        assert len(data) == 1
        assert data[0]["email"] == "howie@gmail.com"
        assert data[0]["agent_type"] == "gemini"

    def test_areg_dt_002_idempotent_same_account(self, tmp_path: Path) -> None:
        """AREG-DT-002：相同 email + agent_type 寫入兩次，第二次回傳 False，不重複。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        reg.auto_register("howie@gmail.com", "gemini")
        result = reg.auto_register("howie@gmail.com", "gemini")
        assert result is False
        data = json.loads(accounts_path.read_text())
        assert len(data) == 1

    def test_areg_dt_003_different_agent_type_is_new(self, tmp_path: Path) -> None:
        """AREG-DT-003：相同 email 不同 agent_type 視為不同帳號。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        reg.auto_register("howie@gmail.com", "gemini")
        result = reg.auto_register("howie@gmail.com", "claude")
        assert result is True
        data = json.loads(accounts_path.read_text())
        assert len(data) == 2

    def test_areg_dt_004_find_by_hash(self, tmp_path: Path) -> None:
        """AREG-DT-004：以 Claude userID hash 查詢對應 email。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        reg.auto_register("howie@gmail.com", "claude", extra={"hash": "abc123"})
        assert reg.find_by_hash("abc123") == "howie@gmail.com"

    def test_areg_eg_001_find_by_hash_not_found(self, tmp_path: Path) -> None:
        """AREG-EG-001：hash 不存在時回傳 None。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        assert reg.find_by_hash("nonexistent") is None

    def test_areg_eg_002_extra_fields_stored(self, tmp_path: Path) -> None:
        """AREG-EG-002：extra 欄位（如 hash）被儲存到 JSON。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        reg.auto_register("howie@gmail.com", "claude", extra={"hash": "abc123"})
        data = json.loads(accounts_path.read_text())
        assert data[0]["hash"] == "abc123"
