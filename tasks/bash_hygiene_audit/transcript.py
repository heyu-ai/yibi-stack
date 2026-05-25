"""從 Claude Code session transcript 回溯 parse hook block 事件。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import AuditRecord, Verdict

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Claude Code 在 hook exit != 0 時，tool_result.content 的前綴
_HOOK_BLOCK_PREFIX = "PreToolUse:Bash hook error:"


@dataclass
class TranscriptBlockEvent:
    """從 transcript 抽出的單次 hook block 事件。"""

    session_id: str
    ts: str
    command_preview: str
    command_hash: str
    block_reason: str
    wasted_ms: int
    wasted_tokens: int


def _parse_hook_reason(hook_msg: str) -> str:
    """從 hook error 訊息抽出 block_reason slug。"""
    msg = hook_msg.lower()
    if "python-c-multiline" in msg or "newline" in msg:
        return "python-c-multiline"
    if "osascript" in msg:
        return "osascript-heredoc"
    if "grep" in msg and ("bre" in msg or "doublequote" in msg or r"\|" in msg):
        return "grep-bre-doublequote"
    if "nested" in msg or "outer" in msg:
        return "nested-subshell"
    if "jq" in msg and ("singlequote" in msg or "filter" in msg):
        return "jq-singlequote-filter"
    if "rg" in msg and "bre" in msg:
        return "rg-bre-misuse"
    if "unicode" in msg or "em dash" in msg or "emoji" in msg:
        return "ap2-unicode"
    if "simple_expansion" in msg or "expansion" in msg:
        return "rule2-doublequote"
    # 從 hook script 名稱猜測
    if "ap2" in msg:
        return "ap2-unicode"
    if "ap1" in msg:
        return "ap1-block"
    return "unknown"


def _cmd_hash(cmd: str) -> str:
    """與 bash hook 的 shasum 計算相同的 command hash（前 16 chars）。"""
    return hashlib.sha256(cmd.encode()).hexdigest()[:16]


def scan_project_transcripts(
    project_slug: str = "-Users-howie-Workspace-github-yibi-stack",
    since_days: int = 14,
    projects_dir: Path | None = None,
) -> list[TranscriptBlockEvent]:
    """掃描指定 project 過去 N 天的 transcript，抽出所有 hook block 事件。

    使用 `is_error: true` + `PreToolUse:Bash hook error:` 識別真實的 hook block，
    避免把 SKILL.md 內容（含 hook 關鍵字描述）誤判為 block 事件。
    """
    base = projects_dir or CLAUDE_PROJECTS_DIR
    project_dir = base / project_slug
    if not project_dir.is_dir():
        raise RuntimeError(f"找不到 project transcript 目錄：{project_dir}")

    cutoff = datetime.now() - timedelta(days=since_days)
    events: list[TranscriptBlockEvent] = []

    for jsonl_path in sorted(project_dir.glob("*.jsonl")):
        mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)
        if mtime < cutoff:
            continue
        session_id = jsonl_path.stem
        _scan_single_transcript(jsonl_path, session_id, events)

    return events


def _scan_single_transcript(
    path: Path,
    session_id: str,
    events: list[TranscriptBlockEvent],
) -> None:
    """從單一 transcript 抽出 hook block 事件並 append 到 events。"""
    prev_bash_cmd = ""
    prev_bash_ts = ""
    prev_output_tokens = 0
    last_output_tokens = 0

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            ts = obj.get("timestamp", "")

            # 追蹤 assistant 的 output_tokens 和 Bash tool_use
            if role == "assistant":
                usage = msg.get("usage", {})
                prev_output_tokens = last_output_tokens
                last_output_tokens = usage.get("output_tokens", 0)
                for blk in msg.get("content") or []:
                    if (
                        isinstance(blk, dict)
                        and blk.get("type") == "tool_use"
                        and blk.get("name") == "Bash"
                    ):
                        prev_bash_cmd = blk.get("input", {}).get("command", "")
                        prev_bash_ts = ts

            # 找 hook block tool_result
            if role == "user":
                for blk in msg.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") != "tool_result" or not blk.get("is_error"):
                        continue
                    content = blk.get("content", "")
                    if isinstance(content, list):
                        text = " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    else:
                        text = str(content)
                    if not text.startswith(_HOOK_BLOCK_PREFIX):
                        continue

                    # 計算時間浪費（此次 block ts - 前一次 bash call ts）
                    try:
                        dt_block = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        dt_bash = datetime.fromisoformat(
                            prev_bash_ts.replace("Z", "+00:00")
                        )
                        wasted_ms = max(
                            0, int((dt_block - dt_bash).total_seconds() * 1000)
                        )
                    except Exception:
                        wasted_ms = 0

                    # token 浪費 = 下一次 assistant turn 的 output_tokens + 200 overhead
                    # last_output_tokens 是最近一次 assistant 的值（block 前）
                    wasted_tokens = last_output_tokens + 200

                    events.append(
                        TranscriptBlockEvent(
                            session_id=session_id,
                            ts=ts,
                            command_preview=prev_bash_cmd[:120],
                            command_hash=_cmd_hash(prev_bash_cmd),
                            block_reason=_parse_hook_reason(text),
                            wasted_ms=wasted_ms,
                            wasted_tokens=wasted_tokens,
                        )
                    )


def transcripts_to_audit_records(
    events: list[TranscriptBlockEvent],
) -> list[AuditRecord]:
    """把 TranscriptBlockEvent 轉成 AuditRecord 格式，與 compute_repeats 串接。"""
    records: list[AuditRecord] = []
    for e in events:
        records.append(
            AuditRecord(
                ts=e.ts,
                hook="transcript",
                exit_code=2,
                verdict=Verdict.BLOCK,
                block_reason=e.block_reason,
                cmd_snippet=e.command_preview,
                command_hash=e.command_hash,
                session_id=e.session_id,
            )
        )
    return records
