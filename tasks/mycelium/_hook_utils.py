"""Stop hook install/uninstall 共用工具（供 insight_hook 與 recap_hook 共用）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def install_stop_hook(
    marker: str,
    hook_label: str,
    settings_path: Path | None = None,
    hook_command: str = "",
    legacy_markers: list[str] | None = None,
) -> tuple[bool, str]:
    """把 Stop hook 註冊到 ~/.claude/settings.json。

    回傳 (is_new, message)。is_new=True 表示新增；False 表示已存在跳過。
    legacy_markers 用於相容 rename 前的舊 hook command 字串，防止重複安裝。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")

    all_markers = [marker] + (legacy_markers or [])
    settings = read_settings(path)
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            if any(m in cmd for m in all_markers):
                return False, f"{hook_label} hook 已註冊，跳過"

    stop_hooks.append(
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": hook_command}],
        }
    )
    write_settings(path, settings)
    return True, f"{hook_label} hook 已註冊：{hook_command}"


def uninstall_stop_hook(
    marker: str,
    hook_label: str,
    settings_path: Path | None = None,
    legacy_markers: list[str] | None = None,
) -> tuple[bool, str]:
    """移除 Stop hook；回傳 (removed, message)。

    legacy_markers 同時移除 rename 前的舊 hook command 條目。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    if not path.exists():
        return False, f"settings.json 不存在：{path}"

    all_markers = [marker] + (legacy_markers or [])
    settings = read_settings(path)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    if not stop_hooks:
        return False, "settings.json 無 Stop hook 設定"

    new_entries: list[dict[str, Any]] = []
    removed = False
    for entry in stop_hooks:
        remaining = [
            h for h in entry.get("hooks", []) if not any(m in h.get("command", "") for m in all_markers)
        ]
        if len(remaining) != len(entry.get("hooks", [])):
            removed = True
        if remaining:
            new_entry = dict(entry)
            new_entry["hooks"] = remaining
            new_entries.append(new_entry)

    if not removed:
        return False, f"找不到對應的 {hook_label} hook"

    settings["hooks"]["Stop"] = new_entries
    write_settings(path, settings)
    return True, f"已移除 {hook_label} hook"


def read_settings(path: Path) -> dict[str, Any]:
    """讀取 settings.json；不存在時回傳空 dict。"""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"settings.json 格式錯誤：{path}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"settings.json 根層必須為 JSON object：{path}")
    return data


def write_settings(path: Path, settings: dict[str, Any]) -> None:
    """寫入 settings.json（自動建立父目錄）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
