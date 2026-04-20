"""Auto-Handover Hooks — PreCompact + SessionStart hook 安裝 / 移除。

PreCompact hook：
  - 攔截第一次 auto-compact，提醒 Claude 先執行 /handover
  - 狀態檔機制確保第二次 compact 直接放行

SessionStart hook：
  - compact 或 clear 後，提示 Claude 執行 /handover-back

使用 install_hooks() 將兩個 hook 寫入 ~/.claude/settings.json。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .insight_hook import _read_settings, _write_settings

# 冪等比對字串
_PRECOMPACT_MARKER = "pre-compact-handover.sh"
_SESSION_START_MARKER = "post-compact-handover-back.sh"


def install_hooks(settings_path: Path | None = None) -> tuple[bool, bool, str]:
    """把 PreCompact + SessionStart hook 寫入 ~/.claude/settings.json。

    回傳 (precompact_is_new, session_start_is_new, message)。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    hooks_dir = _hooks_dir()
    precompact_cmd = str(hooks_dir / "pre-compact-handover.sh")
    session_start_cmd = str(hooks_dir / "post-compact-handover-back.sh")

    settings = _read_settings(path)
    hooks = settings.setdefault("hooks", {})

    # ── PreCompact ──
    precompact_entries: list[dict[str, Any]] = hooks.setdefault("PreCompact", [])
    precompact_is_new = True
    for entry in precompact_entries:
        for h in entry.get("hooks", []):
            if _PRECOMPACT_MARKER in h.get("command", ""):
                precompact_is_new = False
                break
        if not precompact_is_new:
            break

    if precompact_is_new:
        precompact_entries.append(
            {
                "matcher": "auto",
                "hooks": [
                    {
                        "type": "command",
                        "command": precompact_cmd,
                        "timeout": 10,
                    }
                ],
            }
        )

    # ── SessionStart ──
    session_start_entries: list[dict[str, Any]] = hooks.setdefault("SessionStart", [])
    session_start_is_new = True
    for entry in session_start_entries:
        for h in entry.get("hooks", []):
            if _SESSION_START_MARKER in h.get("command", ""):
                session_start_is_new = False
                break
        if not session_start_is_new:
            break

    if session_start_is_new:
        session_start_entries.append(
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": session_start_cmd,
                        "timeout": 10,
                    }
                ],
            }
        )

    _write_settings(path, settings)

    parts = []
    if precompact_is_new:
        parts.append("PreCompact hook 已註冊")
    else:
        parts.append("PreCompact hook 已存在，跳過")
    if session_start_is_new:
        parts.append("SessionStart hook 已註冊")
    else:
        parts.append("SessionStart hook 已存在，跳過")

    return precompact_is_new, session_start_is_new, "；".join(parts)


def uninstall_hooks(settings_path: Path | None = None) -> tuple[bool, str]:
    """從 ~/.claude/settings.json 移除兩個 hook。

    回傳 (removed_any, message)。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    if not path.exists():
        return False, f"settings.json 不存在：{path}"

    settings = _read_settings(path)
    hooks = settings.get("hooks", {})
    removed_any = False

    for event_key, marker in [
        ("PreCompact", _PRECOMPACT_MARKER),
        ("SessionStart", _SESSION_START_MARKER),
    ]:
        entries = hooks.get(event_key, [])
        new_entries: list[dict[str, Any]] = []
        event_removed = False
        for entry in entries:
            remaining = [h for h in entry.get("hooks", []) if marker not in h.get("command", "")]
            if len(remaining) != len(entry.get("hooks", [])):
                event_removed = True
            if remaining:
                new_entry = dict(entry)
                new_entry["hooks"] = remaining
                new_entries.append(new_entry)
        if event_removed:
            removed_any = True
            hooks[event_key] = new_entries

    if not removed_any:
        return False, "找不到 auto-handover hooks，略過"

    _write_settings(path, settings)
    return True, "已移除 PreCompact 與 SessionStart auto-handover hooks"


def _hooks_dir() -> Path:
    """回傳 .claude/hooks/ 的絕對路徑（此模組所在 repo 的根目錄）。"""
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / ".claude" / "hooks"
