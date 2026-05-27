"""帳號 registry 讀寫：_registry/accounts.json 的存取介面；以及 project slug 解析。"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import REGISTRY_DIR


def resolve_project_slug(cwd: Path) -> str | None:
    """由工作目錄解析 git project slug（repo name）。

    使用 `git rev-parse --path-format=absolute --git-common-dir` 取得主 repo 的
    .git 目錄，再取其 parent.name 作為 slug。這在 linked worktree 中也能正確回傳
    主 repo 名稱（而非 worktree 目錄名稱）。
    git 失敗（非 git 目錄或無 git binary）時回傳 None。
    """
    try:
        result = subprocess.run(  # nosec B603
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        git_common_dir = result.stdout.strip()
        # git-common-dir points to the .git directory; its parent is the main repo root
        repo_root = Path(git_common_dir).parent
        return repo_root.name or None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

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
