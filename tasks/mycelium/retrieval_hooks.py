"""Retrieval hooks：PreCompact 強制摘要寫入 + PreToolUse 危險操作 pitfall 警告。

PreCompact hook entry point (`run_precompact_hook`)：
  - 讀 stdin 的 hook payload（JSON）
  - 確認 hook_event_name == "PreCompact"
  - 從 transcript 提取最後幾條 assistant 訊息作為 session 摘要
  - 呼叫 lessons_service.save_lesson() 寫入 working tier

PreToolUse hook entry point (`run_pretooluse_hook`)：
  - 確認 hook_event_name == "PreToolUse"
  - 當 tool_name == "Bash" 且 command 含危險指令（如 git push）
  - 撈出相關 pitfall lesson 並輸出警告到 stdout

任何錯誤都靜默退出，絕不阻斷 Claude 流程。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_DANGEROUS_PATTERNS = ("git push", "git rebase", "git reset --hard", "git force", "rm -rf")


def run_precompact_hook(
    stdin_text: str | None = None,
) -> int:
    """PreCompact hook entry point。回傳 0（永遠不阻斷）。"""
    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except OSError as e:
        print(f"[mycelium-precompact] 無法讀取 stdin：{e}", file=sys.stderr)
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if payload.get("hook_event_name") != "PreCompact":
        return 0

    transcript_path = payload.get("transcript_path", "")
    agent_type = payload.get("agent_type", "claude")

    summary = _extract_summary(transcript_path)
    if not summary:
        return 0

    try:
        from .lessons_service import save_lesson

        save_lesson(
            content=summary,
            tier="working",
            source_bot=agent_type,
            lesson_type="pattern",
        )
    except Exception as e:
        print(f"[mycelium-precompact] save_lesson 失敗：{e}", file=sys.stderr)

    return 0


def run_pretooluse_hook(
    stdin_text: str | None = None,
    output_stream: Any = None,
) -> int:
    """PreToolUse hook entry point。回傳 0（永遠不阻斷）。"""
    if output_stream is None:
        output_stream = sys.stdout

    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except OSError:
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if payload.get("hook_event_name") != "PreToolUse":
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    if tool_name != "Bash":
        return 0

    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return 0

    if not any(pat in command for pat in _DANGEROUS_PATTERNS):
        return 0

    # Surface relevant pitfall lessons
    try:
        from .lessons_service import get_lessons

        rows = get_lessons(lesson_type="pitfall", limit=3)
        if not rows:
            return 0
        print("★ Pitfall warning:", file=output_stream)
        for r in rows:
            print(f"  - {r.get('insight', '')}", file=output_stream)
    except Exception as e:
        print(f"[mycelium-pretooluse] 查詢失敗：{e}", file=sys.stderr)

    return 0


def _extract_summary(transcript_path: str) -> str:
    """從 transcript 提取最後幾條 assistant 訊息作為摘要（最多 500 字元）。"""
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""

    try:
        lines: list[str] = []
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines.append(line)
    except OSError:
        return ""

    # Read last 50 lines, extract assistant text content
    tail = lines[-50:]
    texts: list[str] = []
    for line in tail:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            texts.append(content[:200])
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", "")[:200])

    if not texts:
        return ""

    summary = " | ".join(texts[-3:])  # last 3 assistant turns
    return summary[:500] if len(summary) > 9 else ""  # min 10 chars for LessonRecord
