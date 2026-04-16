"""Codex CLI 帳號偵測：解碼 ~/.codex/auth.json 的 JWT id_token。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from .base import AccountAdapter

_DEFAULT_PATH = Path.home() / ".codex" / "auth.json"


def _decode_jwt_payload(token: str) -> dict[str, object] | None:
    """解碼 JWT 的 payload 部分（中間段）。不驗證簽章。"""
    parts = token.split(".")
    if len(parts) != 3:  # noqa: PLR2004
        return None
    payload_b64 = parts[1]
    # base64url padding 補齊
    padding = 4 - len(payload_b64) % 4
    if padding != 4:  # noqa: PLR2004
        payload_b64 += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(payload_b64)
        result = json.loads(decoded)
        if not isinstance(result, dict):
            return None
        return result
    except Exception:  # noqa: BLE001
        return None


class CodexAccountAdapter(AccountAdapter):
    """讀取 Codex CLI 的 auth.json，解碼 JWT 取得帳號 email。"""

    agent_type = "codex"

    def __init__(self, auth_path: Path | None = None) -> None:
        self._path = auth_path or _DEFAULT_PATH

    def detect(self) -> str | None:
        """回傳 JWT payload 中的 email，任何失敗靜默回傳 None。"""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            tokens = data.get("tokens")
            if not tokens:
                return None
            id_token = tokens.get("id_token")
            if not id_token:
                return None
            payload = _decode_jwt_payload(id_token)
            if not payload:
                return None
            email = str(payload.get("email", "")).strip()
            return email or None
        except Exception:  # noqa: BLE001
            return None
