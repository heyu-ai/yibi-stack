"""Transcript 讀取器：掃描 ~/.claude/projects/ JSONL 取得最近 N 小時的對話。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptEntry:
    """JSONL 單行（user 或 assistant）。"""

    entry_type: str  # "user" | "assistant"
    session_id: str
    timestamp: str
    cwd: str
    git_branch: str
    text_content: str  # all text blocks concatenated
    raw: dict[str, object]


@dataclass
class TranscriptSession:
    """單一 session 的所有 entries。"""

    session_id: str
    project_slug: str  # ~/.claude/projects/<slug>/
    file_path: str
    entries: list[TranscriptEntry] = field(default_factory=list)

    @property
    def project_name(self) -> str:
        """從 cwd 推算專案名稱。"""
        cwd_list = [e.cwd for e in self.entries if e.cwd]
        if cwd_list:
            return Path(cwd_list[0]).name
        return self.project_slug.split("-")[-1]


def _extract_text(content: object) -> str:
    """從 message.content 萃取純文字。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    # tool result may have nested content
                    inner = block.get("content", [])
                    parts.append(_extract_text(inner))
        return "\n".join(p for p in parts if p)
    return ""


def _parse_entry(obj: dict[str, object]) -> TranscriptEntry | None:
    """把一個 JSONL 物件轉成 TranscriptEntry；不符合格式回傳 None。"""
    entry_type = obj.get("type")
    if entry_type not in ("user", "assistant"):
        return None
    msg = obj.get("message", {})
    if not isinstance(msg, dict):
        return None
    content = msg.get("content", [])
    text = _extract_text(content)
    if not text.strip():
        return None
    return TranscriptEntry(
        entry_type=str(entry_type),
        session_id=str(obj.get("sessionId", "")),
        timestamp=str(obj.get("timestamp", "")),
        cwd=str(obj.get("cwd", "")),
        git_branch=str(obj.get("gitBranch", "")),
        text_content=text,
        raw=obj,
    )


def _is_recent(file_path: Path, since_epoch: float) -> bool:
    try:
        return file_path.stat().st_mtime >= since_epoch
    except OSError:
        return False


class TranscriptExtractor:
    """從 ~/.claude/projects/ 讀取最近 lookback_hours 小時內的 sessions。"""

    def __init__(self, lookback_hours: int = 24, projects_dir: Path | None = None) -> None:
        self.lookback_hours = lookback_hours
        self.projects_dir = projects_dir or (Path.home() / ".claude" / "projects")

    def extract(self, extra_paths: list[str] | None = None) -> list[TranscriptSession]:
        """讀取所有近期 sessions。"""
        since = time.time() - self.lookback_hours * 3600
        sessions: list[TranscriptSession] = []

        scan_dirs: list[Path] = []
        if self.projects_dir.is_dir():
            scan_dirs.extend(self.projects_dir.iterdir())
        for p in extra_paths or []:
            ep = Path(p)
            if ep.is_dir():
                scan_dirs.append(ep)

        for project_dir in scan_dirs:
            if not project_dir.is_dir():
                continue
            slug = project_dir.name
            for jsonl_file in project_dir.glob("*.jsonl"):
                if not _is_recent(jsonl_file, since):
                    continue
                session = self._parse_file(jsonl_file, slug)
                if session and session.entries:
                    sessions.append(session)

        return sessions

    def _parse_file(self, path: Path, slug: str) -> TranscriptSession | None:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        entries: list[TranscriptEntry] = []
        session_id = path.stem  # filename without .jsonl
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            # Update session_id from first entry that has it
            if "sessionId" in obj and obj["sessionId"]:
                session_id = obj["sessionId"]
            entry = _parse_entry(obj)
            if entry:
                entries.append(entry)

        if not entries:
            return None
        return TranscriptSession(
            session_id=session_id,
            project_slug=slug,
            file_path=str(path),
            entries=entries,
        )
