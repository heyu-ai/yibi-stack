"""Stop hook install/uninstall 共用工具（供 insight_hook 與 recap_hook 共用）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def install_hook(
    hook_type: str,
    marker: str,
    hook_label: str,
    hook_command: str,
    settings_path: Path | None = None,
    matcher: str = "",
) -> tuple[bool, str]:
    """把指定類型的 hook 註冊到 ~/.claude/settings.json。

    Args:
        hook_type: hook 類型，例如 "Stop"、"PreToolUse"、"PostToolUse"。
        marker: 用於去重判斷的字串（在 command 中搜尋）。
        hook_label: 顯示用名稱（用於回傳訊息）。
        hook_command: 實際 shell 指令。
        settings_path: 覆寫預設 settings.json 路徑（測試用）。
        matcher: hook 的 matcher pattern，預設空字串（匹配全部）。

    Returns:
        (is_new, message)。is_new=True 表示新增；False 表示已存在跳過。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    settings = read_settings(path)
    hooks = settings.setdefault("hooks", {})
    type_hooks = hooks.setdefault(hook_type, [])

    for entry in type_hooks:
        for h in entry.get("hooks", []):
            if marker in h.get("command", ""):
                return False, f"{hook_label} hook 已註冊，跳過"

    type_hooks.append(
        {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": hook_command}],
        }
    )
    write_settings(path, settings)
    return True, f"{hook_label} hook 已註冊：{hook_command}"


def uninstall_hook(
    hook_type: str,
    marker: str,
    hook_label: str,
    settings_path: Path | None = None,
) -> tuple[bool, str]:
    """移除指定類型的 hook；回傳 (removed, message)。

    Args:
        hook_type: hook 類型，例如 "Stop"、"PreToolUse"。
        marker: 識別目標 hook 的字串（在 command 中搜尋）。
        hook_label: 顯示用名稱（用於回傳訊息）。
        settings_path: 覆寫預設 settings.json 路徑（測試用）。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    if not path.exists():
        return False, f"settings.json 不存在：{path}"

    settings = read_settings(path)
    type_hooks = settings.get("hooks", {}).get(hook_type, [])
    if not type_hooks:
        return False, f"settings.json 無 {hook_type} hook 設定"

    new_entries: list[dict[str, Any]] = []
    removed = False
    for entry in type_hooks:
        remaining = [h for h in entry.get("hooks", []) if marker not in h.get("command", "")]
        if len(remaining) != len(entry.get("hooks", [])):
            removed = True
        if remaining:
            new_entry = dict(entry)
            new_entry["hooks"] = remaining
            new_entries.append(new_entry)

    if not removed:
        return False, f"找不到對應的 {hook_label} hook"

    settings["hooks"][hook_type] = new_entries
    write_settings(path, settings)
    return True, f"已移除 {hook_label} hook"


def list_hooks(
    hook_type: str,
    settings_path: Path | None = None,
) -> list[dict[str, Any]]:
    """列出指定類型的所有 hook 條目。

    Args:
        hook_type: hook 類型，例如 "Stop"、"PreToolUse"。
        settings_path: 覆寫預設 settings.json 路徑（測試用）。

    Returns:
        hook 條目清單（每筆為 {"matcher": ..., "hooks": [...]}）。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    settings = read_settings(path)
    return settings.get("hooks", {}).get(hook_type, [])


def install_stop_hook(
    marker: str,
    hook_label: str,
    settings_path: Path | None = None,
    hook_command: str = "",
) -> tuple[bool, str]:
    """把 Stop hook 註冊到 ~/.claude/settings.json。

    回傳 (is_new, message)。is_new=True 表示新增；False 表示已存在跳過。
    """
    return install_hook(
        hook_type="Stop",
        marker=marker,
        hook_label=hook_label,
        hook_command=hook_command,
        settings_path=settings_path,
    )


def uninstall_stop_hook(
    marker: str,
    hook_label: str,
    settings_path: Path | None = None,
) -> tuple[bool, str]:
    """移除 Stop hook；回傳 (removed, message)。"""
    return uninstall_hook(
        hook_type="Stop",
        marker=marker,
        hook_label=hook_label,
        settings_path=settings_path,
    )


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
