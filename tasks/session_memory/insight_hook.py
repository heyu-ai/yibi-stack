"""Insight Collector — Claude Code Stop hook 入口 + install / uninstall 設定。

Stop hook entry point (`run_hook`)：
  - 讀 stdin 的 hook payload（JSON）
  - 解析 transcript，擷取 `★ Insight` 區塊
  - 寫入 ~/.agents/insight/insights.jsonl

任何錯誤都靜默退出，絕不阻斷 Claude 的 Stop 流程。
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .account import detect_account, detect_device
from .config import INSIGHTS_JSONL_PATH, to_portable_path

# ^ anchor + MULTILINE 確保 closing delimiter 必須在行首
INSIGHT_PATTERN = re.compile(
    r"^`★ Insight ─+`\s*\n(.*?)\n^`─+`",
    re.DOTALL | re.MULTILINE,
)

# settings.json 中用於比對冪等的特徵字串（新路徑）
_HOOK_COMMAND_MARKER = "tasks.session_memory insight collect"


def run_hook(
    stdin_text: str | None = None,
    output_path: Path | None = None,
) -> int:
    """Stop hook entry point。回傳 0（永遠不阻斷）。

    參數用於測試注入；正式執行時 stdin_text=None 會從 sys.stdin 讀取。
    """
    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except OSError as e:
        print(f"[agents-insight] 無法讀取 stdin：{e}", file=sys.stderr)
        return 0
    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[agents-insight] hook payload JSON 解析失敗：{e}", file=sys.stderr)
        return 0

    if hook_input.get("hook_event_name") != "Stop":
        return 0

    reason = hook_input.get("reason", "")
    transcript_path = hook_input.get("transcript_path", "")

    if not transcript_path:
        print("[agents-insight] Stop 事件未包含 transcript_path，跳過。", file=sys.stderr)
        return 0

    if not os.path.isfile(transcript_path):
        print(f"[agents-insight] transcript 檔案不存在：{transcript_path}", file=sys.stderr)
        return 0

    session_id, working_dir, branch, project, text_blocks = _read_transcript(transcript_path)

    if not text_blocks:
        return 0

    full_text = "\n".join(text_blocks)
    matches = INSIGHT_PATTERN.findall(full_text)
    if not matches:
        return 0

    account = detect_account(warn=False)
    device = detect_device()
    out_path = output_path or INSIGHTS_JSONL_PATH

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).astimezone().replace(microsecond=0).isoformat()

        with out_path.open("a", encoding="utf-8") as out:
            for insight_text in matches:
                record: dict[str, Any] = {
                    "id": str(uuid.uuid4()),
                    "timestamp": now,
                    "session_id": session_id,
                    "project": project,
                    "working_dir": to_portable_path(working_dir),
                    "branch": branch,
                    "agent_type": "claude",
                    "account": account,
                    "device": device,
                    "insight_text": insight_text.strip(),
                    "session_reason": reason,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[agents-insight] 無法寫入 insights.jsonl：{e}", file=sys.stderr)
        return 0

    return 0


def _read_transcript(transcript_path: str) -> tuple[str, str, str, str, list[str]]:
    """讀 transcript JSONL，回傳 (session_id, working_dir, branch, project, text_blocks)。"""
    session_id = ""
    working_dir = ""
    branch = ""
    project = ""
    text_blocks: list[str] = []
    total_lines = 0
    decode_failures = 0

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                total_lines += 1
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    decode_failures += 1
                    continue

                if entry.get("type") == "user" and not session_id:
                    session_id = entry.get("sessionId", "")
                    working_dir = entry.get("cwd", "")
                    branch = entry.get("gitBranch", "")
                    if working_dir:
                        project = os.path.basename(working_dir)

                if entry.get("type") == "assistant":
                    message = entry.get("message")
                    if not isinstance(message, dict):
                        continue
                    for block in message.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                text_blocks.append(text)
    except (OSError, UnicodeDecodeError) as e:
        print(f"[agents-insight] 無法讀取 transcript：{transcript_path}: {e}", file=sys.stderr)
        return session_id, working_dir, branch, project, text_blocks

    if total_lines > 0 and decode_failures == total_lines:
        print(
            f"[agents-insight] transcript 全部行解析失敗，可能格式不符：{transcript_path}",
            file=sys.stderr,
        )

    return session_id, working_dir, branch, project, text_blocks


# ─────────────────────────────────────────────────────────────────────────
# Install / uninstall Stop hook
# ─────────────────────────────────────────────────────────────────────────


def install_hook(
    settings_path: Path | None = None,
    hook_command: str | None = None,
) -> tuple[bool, str]:
    """把 Stop hook 註冊到 ~/.claude/settings.json。

    回傳 (is_new, message)。is_new=True 表示新增；False 表示已存在跳過。
    hook_command 留空時用 `uv run python -m tasks.session_memory insight collect`。
    """
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    cmd = hook_command or _default_hook_command()

    settings = _read_settings(path)
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            if _HOOK_COMMAND_MARKER in h.get("command", ""):
                return False, "hook 已註冊，跳過"

    stop_hooks.append(
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": cmd,
                }
            ],
        }
    )
    _write_settings(path, settings)
    return True, f"hook 已註冊：{cmd}"


def uninstall_hook(settings_path: Path | None = None) -> tuple[bool, str]:
    """移除 Stop hook；回傳 (removed, message)。"""
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    if not path.exists():
        return False, f"settings.json 不存在：{path}"

    settings = _read_settings(path)
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    if not stop_hooks:
        return False, "settings.json 無 Stop hook 設定"

    new_entries: list[dict[str, Any]] = []
    removed = False
    for entry in stop_hooks:
        remaining = [
            h for h in entry.get("hooks", []) if _HOOK_COMMAND_MARKER not in h.get("command", "")
        ]
        if len(remaining) != len(entry.get("hooks", [])):
            removed = True
        if remaining:
            new_entry = dict(entry)
            new_entry["hooks"] = remaining
            new_entries.append(new_entry)

    if not removed:
        return False, "找不到對應的 agents insight hook"

    settings["hooks"]["Stop"] = new_entries
    _write_settings(path, settings)
    return True, "已移除 agents insight hook"


def _default_hook_command() -> str:
    """回傳預設 hook command（tasks.session_memory insight collect）。

    使用 `--project` 指定 repo 根，讓 hook 不受執行當下 cwd 影響。
    """
    # repo 根：由 tasks/agents/insight_hook.py 往上兩層
    repo_root = Path(__file__).resolve().parents[2]
    return f"uv run --project {repo_root} python -m tasks.session_memory insight collect"


def _read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"settings.json 格式錯誤：{path}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"settings.json 根層必須為 JSON object：{path}")
    return data


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
