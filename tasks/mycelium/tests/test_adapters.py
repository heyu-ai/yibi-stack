"""測試各 Agent 帳號偵測 adapter。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from tasks.mycelium.adapters.claude import ClaudeAccountAdapter
from tasks.mycelium.adapters.codex import CodexAccountAdapter
from tasks.mycelium.adapters.gemini import GeminiAccountAdapter
from tasks.mycelium.registry import AccountRegistry


def _write_google_accounts(path: Path, active: str | None) -> None:
    """寫測試用 google_accounts.json。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"active": active, "old": []}
    path.write_text(json.dumps(data), encoding="utf-8")


class TestGeminiAccountAdapter:
    def test_aadp_dt_001_returns_active_email(self, tmp_path: Path) -> None:
        """AADP-DT-001：active 欄位有值時回傳 email。"""
        accounts_path = tmp_path / ".gemini" / "google_accounts.json"
        _write_google_accounts(accounts_path, active="howie@gmail.com")
        adapter = GeminiAccountAdapter(accounts_path=accounts_path)
        assert adapter.detect() == "howie@gmail.com"

    def test_aadp_dt_002_empty_active_returns_none(self, tmp_path: Path) -> None:
        """AADP-DT-002：active 為空字串時回傳 None。"""
        accounts_path = tmp_path / ".gemini" / "google_accounts.json"
        _write_google_accounts(accounts_path, active="")
        adapter = GeminiAccountAdapter(accounts_path=accounts_path)
        assert adapter.detect() is None

    def test_aadp_eg_001_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-001：檔案不存在回傳 None，不拋例外。"""
        adapter = GeminiAccountAdapter(accounts_path=tmp_path / "nonexistent.json")
        assert adapter.detect() is None

    def test_aadp_eg_002_invalid_json_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-002：JSON 格式錯誤回傳 None，不拋例外。"""
        accounts_path = tmp_path / "bad.json"
        accounts_path.write_text("not json", encoding="utf-8")
        adapter = GeminiAccountAdapter(accounts_path=accounts_path)
        assert adapter.detect() is None

    def test_aadp_eg_003_missing_active_key_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-003：active 欄位缺失回傳 None。"""
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text(json.dumps({"old": []}), encoding="utf-8")
        adapter = GeminiAccountAdapter(accounts_path=accounts_path)
        assert adapter.detect() is None


def _make_jwt_payload(payload: dict[str, object]) -> str:
    """製造假的 JWT（header.payload.signature 格式）。"""
    raw = json.dumps(payload).encode()
    # base64url encode，去掉 padding
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


def _write_auth_json(path: Path, id_token: str | None, has_tokens: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if has_tokens:
        data["tokens"] = {"id_token": id_token}
    path.write_text(json.dumps(data), encoding="utf-8")


class TestCodexAccountAdapter:
    def test_aadp_dt_003_decodes_email_from_jwt(self, tmp_path: Path) -> None:
        """AADP-DT-003：id_token 為有效 JWT 時回傳 email。"""
        token = _make_jwt_payload({"email": "howie@gmail.com", "sub": "abc"})
        auth_path = tmp_path / "auth.json"
        _write_auth_json(auth_path, id_token=token)
        adapter = CodexAccountAdapter(auth_path=auth_path)
        assert adapter.detect() == "howie@gmail.com"

    def test_aadp_eg_004_invalid_jwt_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-004：JWT 格式錯誤（不含 dot）回傳 None。"""
        auth_path = tmp_path / "auth.json"
        _write_auth_json(auth_path, id_token="notajwt")
        adapter = CodexAccountAdapter(auth_path=auth_path)
        assert adapter.detect() is None

    def test_aadp_eg_005_no_email_field_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-005：JWT payload 無 email 欄位回傳 None。"""
        token = _make_jwt_payload({"sub": "abc"})  # 沒有 email
        auth_path = tmp_path / "auth.json"
        _write_auth_json(auth_path, id_token=token)
        adapter = CodexAccountAdapter(auth_path=auth_path)
        assert adapter.detect() is None

    def test_aadp_eg_006_no_tokens_key_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-006：auth.json 沒有 tokens 欄位（API key 模式）回傳 None。"""
        auth_path = tmp_path / "auth.json"
        _write_auth_json(auth_path, id_token=None, has_tokens=False)
        adapter = CodexAccountAdapter(auth_path=auth_path)
        assert adapter.detect() is None

    def test_aadp_eg_007_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-007：檔案不存在回傳 None。"""
        adapter = CodexAccountAdapter(auth_path=tmp_path / "nonexistent.json")
        assert adapter.detect() is None


class TestClaudeAccountAdapter:
    def test_aadp_dt_005_hash_lookup_hit(self, tmp_path: Path) -> None:
        """AADP-DT-005：accounts.json 有此 hash 對應時回傳 email。"""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"userID": "abc123"}), encoding="utf-8")
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        reg = AccountRegistry(accounts_path=accounts_path)
        reg.auto_register("howie@gmail.com", "claude", extra={"hash": "abc123"})
        adapter = ClaudeAccountAdapter(claude_json_path=claude_json, accounts_path=accounts_path)
        assert adapter.detect() == "howie@gmail.com"

    def test_aadp_dt_006_hash_not_in_registry_returns_none(self, tmp_path: Path) -> None:
        """AADP-DT-006：hash 不在 registry 中，回傳 None（不詢問使用者）。"""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"userID": "abc123"}), encoding="utf-8")
        accounts_path = tmp_path / "accounts.json"
        accounts_path.write_text("[]", encoding="utf-8")
        adapter = ClaudeAccountAdapter(claude_json_path=claude_json, accounts_path=accounts_path)
        assert adapter.detect() is None

    def test_aadp_eg_008_claude_json_not_found_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-008：.claude.json 不存在回傳 None。"""
        adapter = ClaudeAccountAdapter(
            claude_json_path=tmp_path / "nonexistent.json",
            accounts_path=tmp_path / "accounts.json",
        )
        assert adapter.detect() is None

    def test_aadp_eg_009_no_userid_key_returns_none(self, tmp_path: Path) -> None:
        """AADP-EG-009：.claude.json 無 userID 欄位回傳 None。"""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"other": "value"}), encoding="utf-8")
        adapter = ClaudeAccountAdapter(claude_json_path=claude_json)
        assert adapter.detect() is None
