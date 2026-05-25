"""帳號 registry 讀寫：_registry/accounts.json 的存取介面。"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import REGISTRY_DIR

_DEFAULT_ACCOUNTS_PATH = REGISTRY_DIR / "accounts.json"


class AccountRegistry:
    """~/.agents/_registry/accounts.json 的讀寫介面。"""

    def __init__(self, accounts_path: Path | None = None) -> None:
        self._path = accounts_path or _DEFAULT_ACCOUNTS_PATH

    def _load(self) -> list[dict[str, object]]:
        """讀取 accounts.json，若不存在回傳空清單。"""
        try:
            data: list[dict[str, object]] = json.loads(self._path.read_text(encoding="utf-8"))
            return data
        except Exception:  # noqa: BLE001
            return []

    def _save(self, records: list[dict[str, object]]) -> None:
        """寫回 accounts.json，失敗時印 stderr warning，不拋例外。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            print(f"[agents-registry] 無法寫入 accounts.json：{e}", file=sys.stderr)

    def auto_register(
        self,
        email: str,
        agent_type: str,
        extra: dict[str, object] | None = None,
    ) -> bool:
        """首次偵測到新帳號時自動寫入。

        回傳 True 代表新增，False 代表已存在（冪等）。
        """
        records = self._load()
        # 以 (email, agent_type) 為唯一 key
        for record in records:
            if record.get("email") == email and record.get("agent_type") == agent_type:
                return False

        now = datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()
        new_record: dict[str, object] = {
            "email": email,
            "agent_type": agent_type,
            "registered_at": now,
        }
        if extra:
            new_record.update(extra)
        records.append(new_record)
        self._save(records)
        return True

    def find_by_hash(self, hash_value: str) -> str | None:
        """以 Claude userID hash 查詢對應 email。未找到回傳 None。"""
        for record in self._load():
            if record.get("hash") == hash_value and record.get("agent_type") == "claude":
                email = record.get("email")
                return str(email) if email else None
        return None

    def list_all(self, agent_type: str | None = None) -> list[dict[str, object]]:
        """列出所有已登記帳號，可選依 agent_type 過濾。

        Args:
            agent_type: 若指定，只回傳符合的記錄；None 表示全部回傳。

        Returns:
            帳號記錄清單（每筆至少含 email / agent_type / registered_at）。
        """
        records = self._load()
        if agent_type is None:
            return records
        return [r for r in records if r.get("agent_type") == agent_type]

    def deregister(self, email: str, agent_type: str) -> bool:
        """移除指定帳號的登記記錄。

        Args:
            email: 帳號 email。
            agent_type: agent 類型（如 "claude"、"codex"）。

        Returns:
            True 代表成功移除，False 代表記錄不存在。
        """
        records = self._load()
        before = len(records)
        records = [
            r for r in records
            if not (r.get("email") == email and r.get("agent_type") == agent_type)
        ]
        if len(records) == before:
            return False
        self._save(records)
        return True

    def update_last_seen(self, email: str, agent_type: str) -> bool:
        """更新指定帳號的 last_seen_at 時間戳記。

        Args:
            email: 帳號 email。
            agent_type: agent 類型。

        Returns:
            True 代表成功更新，False 代表記錄不存在。
        """
        records = self._load()
        now = datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()
        updated = False
        for record in records:
            if record.get("email") == email and record.get("agent_type") == agent_type:
                record["last_seen_at"] = now
                updated = True
                break
        if updated:
            self._save(records)
        return updated
