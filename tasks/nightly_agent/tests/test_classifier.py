"""NIGHTLY-classifier tests."""

from __future__ import annotations

from tasks.nightly_agent.classifier import FrictionClassifier, classify_mycelium_lessons
from tasks.nightly_agent.extractor import TranscriptEntry, TranscriptSession
from tasks.nightly_agent.models import FrictionType


def make_session(
    session_id: str = "s1",
    entries: list[tuple[str, str]] | None = None,
) -> TranscriptSession:
    """entries: list of (type, text) tuples."""
    raw_entries = []
    for i, (etype, text) in enumerate(entries or []):
        raw_entries.append(
            TranscriptEntry(
                entry_type=etype,
                session_id=session_id,
                timestamp=f"2026-05-27T03:0{i}:00.000Z",
                cwd="/Users/howie/project",
                git_branch="main",
                text_content=text,
                raw={},
            )
        )
    return TranscriptSession(
        session_id=session_id,
        project_slug="test-project",
        file_path="/fake/path.jsonl",
        entries=raw_entries,
    )


class TestFrictionClassifier:
    def test_ap2_block_detected(self) -> None:
        session = make_session(
            entries=[
                ("user", "run this command"),
                ("assistant", "PreToolUse:Bash hook error: bash-ap2-check.py blocked the command"),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert any(e.friction_type == FrictionType.AP2_BLOCK for e in events)

    def test_worktree_conflict_detected(self) -> None:
        session = make_session(
            entries=[
                ("user", "checkout branch"),
                ("assistant", "fatal: 'main' is already used by worktree at path"),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert any(e.friction_type == FrictionType.WORKTREE_CONFLICT for e in events)

    def test_wrong_approach_detected(self) -> None:
        session = make_session(
            entries=[
                ("user", "fix the bug"),
                ("assistant", "Let me try a different approach — the previous method was wrong"),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert any(e.friction_type == FrictionType.WRONG_APPROACH for e in events)

    def test_buggy_code_detected(self) -> None:
        session = make_session(
            entries=[
                ("user", "run tests"),
                ("assistant", "Traceback (most recent call last):\n  File test.py\nAssertionError"),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert any(e.friction_type == FrictionType.BUGGY_CODE for e in events)

    def test_language_mismatch_detected(self) -> None:
        # User writes in Chinese, assistant replies in English
        session = make_session(
            entries=[
                ("user", "請幫我修這個 bug"),
                ("assistant", "I'll help you fix this bug. Let me look at the code."),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert any(e.friction_type == FrictionType.LANGUAGE_MISMATCH for e in events)

    def test_no_friction_clean_session(self) -> None:
        session = make_session(
            entries=[
                ("user", "what is 2+2?"),
                ("assistant", "The answer is 4."),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        assert events == []

    def test_only_one_event_per_group_per_entry(self) -> None:
        # Multiple AP2 patterns in the same text should only emit one AP2 event
        session = make_session(
            entries=[
                ("user", "bad command"),
                ("assistant", "bash-ap2 block: em dash detected in command (unicode bash)"),
            ]
        )
        classifier = FrictionClassifier()
        events = classifier.classify([session])
        ap2_events = [e for e in events if e.friction_type == FrictionType.AP2_BLOCK]
        assert len(ap2_events) == 1

    def test_multiple_sessions(self) -> None:
        sessions = [
            make_session(
                "s1", [("user", "x"), ("assistant", "Traceback (most recent call last):\nError")]
            ),
            make_session("s2", [("user", "y"), ("assistant", "bash-ap2 block detected")]),
        ]
        classifier = FrictionClassifier()
        events = classifier.classify(sessions)
        types = {e.friction_type for e in events}
        assert FrictionType.BUGGY_CODE in types
        assert FrictionType.AP2_BLOCK in types


class TestClassifyMyceliumLessons:
    def test_pitfall_lesson_classified(self) -> None:
        lessons: list[dict[str, object]] = [
            {
                "id": "lesson-1",
                "type": "pitfall",
                "ts": "2026-05-27T03:00:00",
                "project": "yibi-stack",
                "insight": "Worktree conflict: already used by worktree at path",
                "handover_id": "h1",
            }
        ]
        events = classify_mycelium_lessons(lessons)
        assert len(events) == 1
        assert events[0].friction_type == FrictionType.WORKTREE_CONFLICT
        assert "mycelium" in events[0].session_id

    def test_non_pitfall_lesson_skipped(self) -> None:
        lessons: list[dict[str, object]] = [
            {
                "id": "lesson-2",
                "type": "architecture",
                "ts": "2026-05-27T03:00:00",
                "project": "proj",
                "insight": "Use abstractions wisely",
                "handover_id": None,
            }
        ]
        events = classify_mycelium_lessons(lessons)
        assert events == []
