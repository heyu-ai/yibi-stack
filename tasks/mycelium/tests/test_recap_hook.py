"""tests/test_recap_hook.py — recap_hook 單元測試。"""

from __future__ import annotations

import json
from pathlib import Path

from tasks.mycelium.config import to_portable_path
from tasks.mycelium.recap_hook import (
    _build_record,
    _extract_away_summaries,
    _load_seen_uuids,
    install_hook,
    run_hook,
    uninstall_hook,
)

# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────


def make_away_entry(
    uuid: str = "uuid-001",
    session_id: str = "sess-abc",
    content: str = "正在實作 recap hook",
    cwd: str = "/Users/howie/Workspace/github/ainization-skill",
    branch: str = "main",
    version: str = "2.1.112",
    timestamp: str = "2026-04-25T10:00:00+08:00",
) -> dict[str, object]:
    return {
        "type": "system",
        "subtype": "away_summary",
        "uuid": uuid,
        "sessionId": session_id,
        "content": content,
        "cwd": cwd,
        "gitBranch": branch,
        "version": version,
        "timestamp": timestamp,
    }


def write_transcript(path: Path, entries: list[dict[str, object]]) -> None:
    """把多個 entry 寫成 JSONL transcript。"""
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def make_payload(transcript_path: str, reason: str = "") -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "transcript_path": transcript_path,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def make_settings_with_insight(path: Path) -> None:
    """寫入含 insight collect hook 的 settings.json。"""
    data = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "uv run python -m tasks.mycelium insight collect",
                        }
                    ],
                }
            ]
        }
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────
# Service Tests
# ──────────────────────────────────────────


class TestRunHook:
    def test_recap_st_040_single_away_summary_writes_one_record(self, tmp_path: Path) -> None:
        """RECAP-ST-040: transcript 含 1 筆 away_summary → 寫入 1 行。"""
        transcript = tmp_path / "t.jsonl"
        write_transcript(transcript, [make_away_entry(uuid="u-001")])

        out = tmp_path / "session-recap.jsonl"
        result = run_hook(make_payload(str(transcript)), output_path=out)

        assert result == 0
        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["id"] == "u-001"
        assert rec["recap_text"] == "正在實作 recap hook"

    def test_recap_st_041_three_away_summaries_all_written(self, tmp_path: Path) -> None:
        """RECAP-ST-041: transcript 含 3 筆 away_summary → 全寫入（append-only）。"""
        transcript = tmp_path / "t.jsonl"
        entries = [
            make_away_entry(
                uuid=f"u-{i:03d}", content=f"recap {i}", timestamp=f"2026-04-25T1{i}:00:00+08:00"
            )
            for i in range(3)
        ]
        noise: list[dict[str, object]] = [
            {"type": "user", "message": "hello"},
            {"type": "assistant", "message": "hi"},
        ]
        write_transcript(transcript, noise + entries + noise)

        out = tmp_path / "session-recap.jsonl"
        result = run_hook(make_payload(str(transcript)), output_path=out)

        assert result == 0
        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_recap_st_042_idempotent_second_run_no_new_records(self, tmp_path: Path) -> None:
        """RECAP-ST-042: 第二次 collect 同 transcript → 0 新記錄（uuid 冪等）。"""
        transcript = tmp_path / "t.jsonl"
        write_transcript(transcript, [make_away_entry(uuid="u-idem")])

        out = tmp_path / "session-recap.jsonl"
        run_hook(make_payload(str(transcript)), output_path=out)
        first_size = out.stat().st_size

        run_hook(make_payload(str(transcript)), output_path=out)
        assert out.stat().st_size == first_size

    def test_recap_st_043_append_does_not_affect_old_session(self, tmp_path: Path) -> None:
        """RECAP-ST-043: jsonl 已有舊 session 記錄 → 新 session 純 append 不影響舊資料。"""
        out = tmp_path / "session-recap.jsonl"

        t1 = tmp_path / "t1.jsonl"
        write_transcript(t1, [make_away_entry(uuid="old-001", session_id="sess-old")])
        run_hook(make_payload(str(t1)), output_path=out)

        t2 = tmp_path / "t2.jsonl"
        write_transcript(t2, [make_away_entry(uuid="new-001", session_id="sess-new")])
        run_hook(make_payload(str(t2)), output_path=out)

        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2
        ids = {json.loads(ln)["id"] for ln in lines}
        assert ids == {"old-001", "new-001"}

    def test_recap_st_044_uses_entry_timestamp_and_uuid(self, tmp_path: Path) -> None:
        """RECAP-ST-044: record 用 entry timestamp + entry uuid（非 now/uuid4）。"""
        transcript = tmp_path / "t.jsonl"
        entry = make_away_entry(uuid="ts-uuid", timestamp="2026-01-01T00:00:00+08:00")
        write_transcript(transcript, [entry])

        out = tmp_path / "session-recap.jsonl"
        run_hook(make_payload(str(transcript)), output_path=out)

        rec = json.loads(out.read_text(encoding="utf-8").strip())
        assert rec["id"] == "ts-uuid"
        assert rec["timestamp"] == "2026-01-01T00:00:00+08:00"

    def test_recap_st_045_working_dir_tilde_encoded(self, tmp_path: Path) -> None:
        """RECAP-ST-045: working_dir 用 to_portable_path() tilde-encode。"""
        home = str(Path.home())
        transcript = tmp_path / "t.jsonl"
        cwd = home + "/Workspace/project"
        write_transcript(transcript, [make_away_entry(uuid="tilde-001", cwd=cwd)])

        out = tmp_path / "session-recap.jsonl"
        run_hook(make_payload(str(transcript)), output_path=out)

        rec = json.loads(out.read_text(encoding="utf-8").strip())
        assert rec["working_dir"].startswith("~/"), f"期望 ~/ 前綴，實際：{rec['working_dir']}"
        assert not rec["working_dir"].startswith(home)


# ──────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────


class TestRunHookEdgeCases:
    def test_recap_eg_031_no_away_summary_jsonl_unchanged(self, tmp_path: Path) -> None:
        """RECAP-EG-031: transcript 無 away_summary → jsonl 不變。"""
        transcript = tmp_path / "t.jsonl"
        write_transcript(
            transcript,
            [{"type": "user", "message": "hello"}, {"type": "assistant", "message": "hi"}],
        )

        out = tmp_path / "session-recap.jsonl"
        run_hook(make_payload(str(transcript)), output_path=out)
        assert not out.exists()

    def test_recap_eg_032_invalid_payload_json_returns_zero(self, tmp_path: Path) -> None:
        """RECAP-EG-032: hook payload 本身為無效 JSON → 吞 exception 回傳 0。"""
        out = tmp_path / "session-recap.jsonl"
        result = run_hook("NOT VALID JSON", output_path=out)
        assert result == 0
        assert not out.exists()

    def test_recap_eg_032b_transcript_is_directory_returns_zero(self, tmp_path: Path) -> None:
        """RECAP-EG-032b: _extract_away_summaries 拋出 IsADirectoryError → 吞 exception 回傳 0。"""
        out = tmp_path / "session-recap.jsonl"
        # 傳入目錄路徑會讓 open() 拋出 IsADirectoryError（由外層 except Exception 捕捉）
        payload = json.dumps(
            {"hook_event_name": "Stop", "transcript_path": str(tmp_path), "reason": ""}
        )
        result = run_hook(payload, output_path=out)
        assert result == 0
        assert not out.exists()

    def test_recap_eg_033_non_stop_event_ignored(self, tmp_path: Path) -> None:
        """RECAP-EG-033: hook_event_name != 'Stop' → 不處理。"""
        transcript = tmp_path / "t.jsonl"
        write_transcript(transcript, [make_away_entry()])

        out = tmp_path / "session-recap.jsonl"
        payload = json.dumps({"hook_event_name": "PreCompact", "transcript_path": str(transcript)})
        result = run_hook(payload, output_path=out)
        assert result == 0
        assert not out.exists()

    def test_recap_eg_034_install_hook_idempotent(self, tmp_path: Path) -> None:
        """RECAP-EG-034: install-hook 兩次（idempotency）。"""
        settings = tmp_path / "settings.json"
        cmd = "uv run python -m tasks.mycelium recap collect"

        is_new1, _ = install_hook(settings_path=settings, hook_command=cmd)
        is_new2, _ = install_hook(settings_path=settings, hook_command=cmd)

        assert is_new1 is True
        assert is_new2 is False

        data = json.loads(settings.read_text(encoding="utf-8"))
        stop = data["hooks"]["Stop"]
        all_commands = [h["command"] for e in stop for h in e.get("hooks", [])]
        assert all_commands.count(cmd) == 1

    def test_recap_eg_035_install_hook_does_not_affect_insight_entry(self, tmp_path: Path) -> None:
        """RECAP-EG-035: install-hook 不影響既有 insight collect 條目。"""
        settings = tmp_path / "settings.json"
        make_settings_with_insight(settings)

        install_hook(
            settings_path=settings,
            hook_command="uv run python -m tasks.mycelium recap collect",
        )

        data = json.loads(settings.read_text(encoding="utf-8"))
        all_commands = [h["command"] for e in data["hooks"]["Stop"] for h in e.get("hooks", [])]
        assert any("insight collect" in c for c in all_commands), "insight hook 不應被移除"
        assert any("recap collect" in c for c in all_commands), "recap hook 應已加入"


# ──────────────────────────────────────────
# Uninstall Hook Tests
# ──────────────────────────────────────────


class TestUninstallHook:
    def test_recap_eg_036_uninstall_removes_hook_and_writes_back(self, tmp_path: Path) -> None:
        """RECAP-EG-036: uninstall_hook 成功移除並回寫 settings.json。"""
        settings = tmp_path / "settings.json"
        cmd = "uv run python -m tasks.mycelium recap collect"
        install_hook(settings_path=settings, hook_command=cmd)

        removed, _ = uninstall_hook(settings_path=settings)

        assert removed is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        all_commands = [
            h["command"] for e in data.get("hooks", {}).get("Stop", []) for h in e.get("hooks", [])
        ]
        assert cmd not in all_commands

    def test_recap_eg_037_uninstall_settings_missing_returns_false(self, tmp_path: Path) -> None:
        """RECAP-EG-037: settings.json 不存在時回傳 (False, ...)。"""
        settings = tmp_path / "nonexistent.json"
        removed, msg = uninstall_hook(settings_path=settings)
        assert removed is False
        assert "不存在" in msg

    def test_recap_eg_038_uninstall_hook_not_found_returns_false(self, tmp_path: Path) -> None:
        """RECAP-EG-038: recap hook 不在 settings.json 中時回傳 (False, ...)。"""
        settings = tmp_path / "settings.json"
        make_settings_with_insight(settings)

        removed, msg = uninstall_hook(settings_path=settings)

        assert removed is False
        assert "找不到" in msg

    def test_recap_eg_039_uninstall_preserves_sibling_hooks(self, tmp_path: Path) -> None:
        """RECAP-EG-039: 移除 recap hook 後，同一 entry 的 sibling hook 保留。"""
        settings = tmp_path / "settings.json"
        make_settings_with_insight(settings)
        install_hook(
            settings_path=settings,
            hook_command="uv run python -m tasks.mycelium recap collect",
        )

        # 確認兩個 hook 都在
        data = json.loads(settings.read_text(encoding="utf-8"))
        before = [h["command"] for e in data["hooks"]["Stop"] for h in e.get("hooks", [])]
        assert any("insight collect" in c for c in before)
        assert any("recap collect" in c for c in before)

        uninstall_hook(settings_path=settings)

        data = json.loads(settings.read_text(encoding="utf-8"))
        after = [h["command"] for e in data["hooks"]["Stop"] for h in e.get("hooks", [])]
        assert any("insight collect" in c for c in after), "insight hook 不應被移除"
        assert not any("recap collect" in c for c in after), "recap hook 應已移除"

    def test_recap_eg_040_uninstall_no_stop_hooks_returns_false(self, tmp_path: Path) -> None:
        """RECAP-EG-040: settings.json 無 Stop hooks 時回傳 (False, ...)。"""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

        removed, _ = uninstall_hook(settings_path=settings)
        assert removed is False

    def test_recap_eg_041_install_upgrades_legacy_marker(self, tmp_path: Path) -> None:
        """RECAP-EG-041: settings.json 已有舊版 session_memory marker 時，install 就地升級為新版。"""
        settings = tmp_path / "settings.json"
        new_cmd = "x tasks.mycelium recap collect"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run python -m tasks.session_memory recap collect",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        is_new, msg = install_hook(settings_path=settings, hook_command=new_cmd)

        assert is_new is True
        assert "升級" in msg
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["Stop"]) == 1
        stored_cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert stored_cmd == new_cmd

    def test_recap_eg_042_uninstall_removes_legacy_marker(self, tmp_path: Path) -> None:
        """RECAP-EG-042: uninstall 移除舊版 session_memory hook entry。"""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run python -m tasks.session_memory recap collect",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        removed, _ = uninstall_hook(settings_path=settings)

        assert removed is True
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["hooks"]["Stop"] == []


# ──────────────────────────────────────────
# Helper function unit tests
# ──────────────────────────────────────────


class TestExtractAwaySummaries:
    def test_filters_only_away_summary_entries(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        entries: list[dict[str, object]] = [
            {"type": "user", "content": "hello"},
            make_away_entry(uuid="a1"),
            {"type": "assistant", "message": "ok"},
            make_away_entry(uuid="a2"),
        ]
        write_transcript(transcript, entries)

        results = _extract_away_summaries(str(transcript))
        assert len(results) == 2
        assert {r["uuid"] for r in results} == {"a1", "a2"}

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        with transcript.open("w", encoding="utf-8") as f:
            f.write("NOT JSON\n")
            f.write(json.dumps(make_away_entry(uuid="ok")) + "\n")

        results = _extract_away_summaries(str(transcript))
        assert len(results) == 1


class TestLoadSeenUuids:
    def test_returns_empty_set_when_file_missing(self, tmp_path: Path) -> None:
        result = _load_seen_uuids(tmp_path / "nonexistent.jsonl")
        assert result == set()

    def test_returns_existing_ids(self, tmp_path: Path) -> None:
        out = tmp_path / "recap.jsonl"
        out.write_text(
            json.dumps({"id": "id-1"}) + "\n" + json.dumps({"id": "id-2"}) + "\n",
            encoding="utf-8",
        )
        result = _load_seen_uuids(out)
        assert result == {"id-1", "id-2"}


class TestBuildRecord:
    def test_fields_mapped_correctly(self) -> None:
        entry = make_away_entry(
            uuid="e-uuid",
            session_id="s-001",
            cwd="/Users/testuser/proj",
            branch="feat/test",
            content="working on tests",
            version="2.1.112",
            timestamp="2026-04-25T12:00:00+08:00",
        )
        rec = _build_record(
            entry,
            reason="idle",
            account="test-account",
            device="test-device",
            to_portable_path=to_portable_path,
        )

        assert rec.id == "e-uuid"
        assert rec.session_id == "s-001"
        assert rec.branch == "feat/test"
        assert rec.recap_text == "working on tests"
        assert rec.cc_version == "2.1.112"
        assert rec.timestamp == "2026-04-25T12:00:00+08:00"
        assert rec.session_reason == "idle"
        assert rec.agent_type == "claude"
        assert rec.project == "proj"
        assert rec.account == "test-account"
        assert rec.device == "test-device"
