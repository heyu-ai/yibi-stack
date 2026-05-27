"""Friction 分類器：在 transcript entries 中識別 friction events。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from .extractor import TranscriptEntry, TranscriptSession
from .models import FrictionEvent, FrictionType


# ---------------------------------------------------------------------------
# Pattern definitions — each tuple is (pattern, description_template)
# ---------------------------------------------------------------------------

_AP2_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bash-ap2|AP2.*block|em\s+dash|en\s+dash.*bash", re.I), "AP2 em/en dash in bash"),
    (re.compile(r"unicode.*bash|bash.*unicode", re.I), "AP2 unicode in bash command"),
    (
        re.compile(r"PreToolUse.*hook.*error|hook error.*bash", re.I),
        "PreToolUse hook blocked bash",
    ),
    (re.compile(r"ap1.*inline.*check|bash.*anti.pattern", re.I), "AP1 bash anti-pattern block"),
    (re.compile(r"Unhandled node type.*string|simple_expansion", re.I), "Bash quoting error"),
]

_WORKTREE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"already used by worktree", re.I),
        "Branch already checked out in another worktree",
    ),
    (re.compile(r"fatal.*worktree|worktree.*fatal", re.I), "Fatal git worktree error"),
    (
        re.compile(r"cannot checkout.*main|main.*already.*worktree", re.I),
        "Attempted to checkout main in worktree",
    ),
    (re.compile(r"worktree.*conflict|conflict.*worktree", re.I), "Worktree conflict"),
    (re.compile(r"linked worktree.*main|main.*linked worktree", re.I), "Linked worktree on main"),
]

_WRONG_APPROACH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"let me try\s+a\s+different|let me reconsider|i made a mistake|"
            r"actually,\s+i should|going back to|my approach was wrong",
            re.I,
        ),
        "Agent self-corrected approach",
    ),
    (
        re.compile(r"i was wrong|that was incorrect|let me redo|starting over", re.I),
        "Agent acknowledged wrong approach",
    ),
    (
        re.compile(r"scratch that|ignore my previous|let me start fresh", re.I),
        "Agent discarded previous work",
    ),
]

_BUGGY_CODE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Traceback \(most recent call last\)", re.I), "Python traceback"),
    (re.compile(r"AssertionError|AssertionFailed", re.I), "Assertion failure"),
    (re.compile(r"SyntaxError.*python|python.*SyntaxError", re.I), "Python syntax error"),
    (
        re.compile(r"FAILED.*tests?|tests?.*FAILED|\d+ failed", re.I),
        "Test failure",
    ),
    (re.compile(r"mypy.*error|type.*error.*mypy", re.I), "Mypy type error"),
    (re.compile(r"ruff.*error|ruff.*E\d{3}", re.I), "Ruff lint error"),
]

_LANGUAGE_MISMATCH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # English response to Chinese user message
    (
        re.compile(r"I'll help you|Let me|I can see|Here's|I've|I have", re.I),
        "English response pattern",
    ),
]


@dataclass
class _PatternGroup:
    friction_type: FrictionType
    patterns: list[tuple[re.Pattern[str], str]]


_PATTERN_GROUPS: list[_PatternGroup] = [
    _PatternGroup(FrictionType.AP2_BLOCK, _AP2_PATTERNS),
    _PatternGroup(FrictionType.WORKTREE_CONFLICT, _WORKTREE_PATTERNS),
    _PatternGroup(FrictionType.WRONG_APPROACH, _WRONG_APPROACH_PATTERNS),
    _PatternGroup(FrictionType.BUGGY_CODE, _BUGGY_CODE_PATTERNS),
]

# Language mismatch needs special logic (requires context of user message language)
_CHINESE_RE = re.compile(r"[一-鿿　-〿＀-￯]")
_ENGLISH_SENTENCE_RE = re.compile(r"\b(I|Let|Here|I'll|I've|I can|I will)\b")


def _detect_language_mismatch(entry: TranscriptEntry, prev_user_text: str) -> str | None:
    """若 user 用中文、assistant 用英文回覆，視為 language_mismatch。"""
    if entry.entry_type != "assistant":
        return None
    if not prev_user_text:
        return None
    user_has_chinese = bool(_CHINESE_RE.search(prev_user_text))
    if not user_has_chinese:
        return None
    # Check if assistant reply starts with English sentences
    first_500 = entry.text_content[:500]
    if _ENGLISH_SENTENCE_RE.search(first_500) and not _CHINESE_RE.search(first_500[:200]):
        return "Assistant replied in English when user wrote in Chinese"
    return None


class FrictionClassifier:
    """掃描 TranscriptSession list，回傳 FrictionEvent list。"""

    def classify(self, sessions: list[TranscriptSession]) -> list[FrictionEvent]:
        """從多個 sessions 提取所有 friction events。"""
        events: list[FrictionEvent] = []
        for session in sessions:
            events.extend(self._classify_session(session))
        return events

    def _classify_session(self, session: TranscriptSession) -> list[FrictionEvent]:
        events: list[FrictionEvent] = []
        prev_user_text = ""

        for idx, entry in enumerate(session.entries):
            if entry.entry_type == "user":
                prev_user_text = entry.text_content
                continue

            # assistant entry — run pattern groups
            for group in _PATTERN_GROUPS:
                for pattern, description in group.patterns:
                    m = pattern.search(entry.text_content)
                    if m:
                        # Extract a short snippet around the match
                        start = max(0, m.start() - 60)
                        end = min(len(entry.text_content), m.end() + 120)
                        snippet = entry.text_content[start:end].strip()
                        events.append(
                            FrictionEvent(
                                id=str(uuid.uuid4()),
                                session_id=session.session_id,
                                timestamp=entry.timestamp,
                                project=session.project_name,
                                friction_type=group.friction_type,
                                description=description,
                                raw_text=snippet,
                                source_file=session.file_path,
                                line_number=idx,
                            )
                        )
                        # Only emit one event per entry per group
                        break

            # Language mismatch check
            mismatch = _detect_language_mismatch(entry, prev_user_text)
            if mismatch:
                events.append(
                    FrictionEvent(
                        id=str(uuid.uuid4()),
                        session_id=session.session_id,
                        timestamp=entry.timestamp,
                        project=session.project_name,
                        friction_type=FrictionType.LANGUAGE_MISMATCH,
                        description=mismatch,
                        raw_text=entry.text_content[:300],
                        source_file=session.file_path,
                        line_number=idx,
                    )
                )

        return events


def classify_mycelium_lessons(
    lessons: list[dict[str, object]],
) -> list[FrictionEvent]:
    """把 mycelium pitfall/pattern lessons 轉成 FrictionEvent（作為補充來源）。"""
    events: list[FrictionEvent] = []
    for lesson in lessons:
        lesson_type = lesson.get("type", "")
        if lesson_type not in ("pitfall", "pattern"):
            continue
        insight = str(lesson.get("insight", ""))
        if not insight:
            continue
        # Classify the lesson insight text
        for group in _PATTERN_GROUPS:
            for pattern, description in group.patterns:
                if pattern.search(insight):
                    events.append(
                        FrictionEvent(
                            id=f"lesson-{lesson.get('id', uuid.uuid4())}",
                            session_id=f"mycelium-{lesson.get('handover_id', 'unknown')}",
                            timestamp=str(lesson.get("ts", "")),
                            project=str(lesson.get("project", "")),
                            friction_type=group.friction_type,
                            description=f"Lesson[{lesson_type}]: {description}",
                            raw_text=insight,
                            source_file="mycelium:handover.db",
                            line_number=0,
                        )
                    )
                    break
    return events
