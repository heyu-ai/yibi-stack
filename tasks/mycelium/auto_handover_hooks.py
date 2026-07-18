"""Auto-Handover Hooks — PreCompact + SessionStart hook 安裝 / 移除。

PreCompact hook：
  - 攔截第一次 auto-compact，提醒 Claude 先執行 /handover
  - 狀態檔機制確保第二次 compact 直接放行

SessionStart hook：
  - compact 或 clear 後，提示 Claude 執行 /handover-back

使用 install_hooks() 將兩個 installed CLI hook 寫入 ~/.claude/settings.json。
"""

from __future__ import annotations

import contextlib
import json
import shlex
import shutil
import time
import warnings
from pathlib import Path
from typing import Any

from ._hook_utils import read_settings as _read_settings
from ._hook_utils import write_settings as _write_settings

# 冪等比對字串；legacy marker 讓既有 checkout hook 可被原地升級及移除。
_PRECOMPACT_MARKERS = ("hooks pre-compact", "pre-compact-handover.sh")
_SESSION_START_MARKERS = ("hooks session-start", "post-compact-handover-back.sh")
_STATE_DIR = Path("/tmp")  # nosec B108 — 既有 Claude hook 協定使用此目錄
_STATE_TTL_SECONDS = 3600

_PRECOMPACT_SYSTEM_MESSAGE = (
    "Context 即將自動 compact。建議先執行 /handover 保存工作進度，"
    "避免重要資訊在壓縮中遺失。"
    "執行完 handover 後，下次互動時 compact 將自動進行，"
    "然後執行 /handover-back 恢復工作狀態。"
    "是否要先執行 handover？"
)
_SESSION_START_SYSTEM_MESSAGE = (
    "Context 已壓縮/清空。請立即執行 /handover-back 恢復上次工作狀態，"
    "然後告知使用者已恢復並詢問如何繼續。"
)


class MyceliumBinaryNotFoundError(RuntimeError):
    """install-hooks 無法從 PATH 解析 mycelium。"""


def install_hooks(settings_path: Path | None = None) -> tuple[bool, bool, str]:
    """把 PreCompact + SessionStart hook 寫入 ~/.claude/settings.json。

    回傳 (precompact_is_new, session_start_is_new, message)。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    binary_path = _resolve_mycelium_binary()
    quoted_binary = shlex.quote(str(binary_path))
    precompact_cmd = f"{quoted_binary} hooks pre-compact"
    session_start_cmd = f"{quoted_binary} hooks session-start"

    settings = _read_settings(path)
    hooks = settings.setdefault("hooks", {})

    # ── PreCompact ──
    precompact_entries: list[dict[str, Any]] = hooks.setdefault("PreCompact", [])
    precompact_is_new = _upsert_hook(
        precompact_entries,
        markers=_PRECOMPACT_MARKERS,
        matcher="auto",
        command=precompact_cmd,
    )

    # ── SessionStart ──
    session_start_entries: list[dict[str, Any]] = hooks.setdefault("SessionStart", [])
    session_start_is_new = _upsert_hook(
        session_start_entries,
        markers=_SESSION_START_MARKERS,
        matcher="",
        command=session_start_cmd,
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

    for event_key, markers in [
        ("PreCompact", _PRECOMPACT_MARKERS),
        ("SessionStart", _SESSION_START_MARKERS),
    ]:
        entries = hooks.get(event_key, [])
        new_entries: list[dict[str, Any]] = []
        event_removed = False
        for entry in entries:
            remaining = [
                hook
                for hook in entry.get("hooks", [])
                if not _command_has_marker(hook.get("command", ""), markers)
            ]
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


def run_pre_compact_hook(stdin_text: str) -> tuple[int, str | None]:
    """處理 PreCompact payload，回傳 (exit_code, system_message)。"""
    payload = _parse_payload(stdin_text)
    if payload is None or str(payload.get("hook_event_name", "")) != "PreCompact":
        return 0, None

    session_id = str(payload.get("session_id", "") or "")
    matcher = str(payload.get("matcher", "") or "")
    state_suffix = session_id or "default"
    state_file = _STATE_DIR / f"claude-handover-suggested-{state_suffix}"

    if state_file.exists():
        try:
            file_age = time.time() - state_file.stat().st_mtime
        except OSError:
            warnings.warn(
                "pre-compact-handover: 無法讀取狀態檔 mtime，跳過過期檢查",
                stacklevel=2,
            )
        else:
            if file_age > _STATE_TTL_SECONDS:
                state_file.unlink()
                _log_event_best_effort(
                    "layer2_stale_reset",
                    session_id=session_id,
                    matcher=matcher,
                    source_layer="layer2",
                )

    if state_file.exists():
        state_file.unlink()
        _log_event_best_effort(
            "layer2_passthrough", session_id=session_id, matcher=matcher, source_layer="layer2"
        )
        return 0, None

    state_file.touch()
    _log_event_best_effort(
        "layer2_intercept", session_id=session_id, matcher=matcher, source_layer="layer2"
    )
    return 2, _PRECOMPACT_SYSTEM_MESSAGE


def run_session_start_hook(stdin_text: str) -> tuple[int, str | None]:
    """處理 SessionStart payload，回傳 (exit_code, system_message)。"""
    payload = _parse_payload(stdin_text)
    if payload is None:
        return 0, None

    matcher = str(payload.get("matcher", payload.get("matcher_type", "")) or "")
    if matcher not in {"compact", "clear"}:
        return 0, None

    handover_db = Path.home() / ".agents" / "handover" / "handover.db"
    if not handover_db.is_file():
        return 0, None

    session_id = str(payload.get("session_id", "") or "")
    _log_event_best_effort(
        "layer3_session_start", session_id=session_id, matcher=matcher, source_layer="layer3"
    )
    return 0, _SESSION_START_SYSTEM_MESSAGE


def _resolve_mycelium_binary() -> Path:
    """從 PATH 解析並正規化 installed mycelium binary。"""
    resolved = shutil.which("mycelium")
    if resolved is None:
        import click

        message = "[FAIL] 找不到 mycelium；請先安裝 CLI 並確認 PATH 設定"
        click.echo(message, err=True)
        raise MyceliumBinaryNotFoundError(message)
    return Path(resolved).expanduser().resolve()


def _upsert_hook(
    entries: list[dict[str, Any]],
    *,
    markers: tuple[str, ...],
    matcher: str,
    command: str,
) -> bool:
    """新增 owned hook，或把 legacy/existing command 原地更新為目前 binary。"""
    for entry in entries:
        for hook in entry.get("hooks", []):
            if _command_has_marker(hook.get("command", ""), markers):
                entry["matcher"] = matcher
                hook.update({"type": "command", "command": command, "timeout": 10})
                return False

    entries.append(
        {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command, "timeout": 10}],
        }
    )
    return True


def _command_has_marker(command: object, markers: tuple[str, ...]) -> bool:
    return isinstance(command, str) and any(marker in command for marker in markers)


def _parse_payload(stdin_text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdin_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _log_event_best_effort(
    event_type: str,
    *,
    session_id: str,
    matcher: str,
    source_layer: str,
) -> None:
    """記錄 shadow metric；任何 import/write failure 都不得影響 hook。"""
    with contextlib.suppress(Exception):  # nosec B110 — best-effort shadow logging 必須 fail-open
        from .metrics_service import log_event

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            log_event(
                event_type,
                session_id=session_id or None,
                source_layer=source_layer,
                matcher=matcher or None,
            )
