"""Tests for commands/scripts/newjob_resolve_pull_conflict.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from newjob_resolve_pull_conflict import (
    is_identical_to_origin,
    main,
    parse_conflicting_files,
)

_GIT_STDERR = """\
From github.com:owner/repo
 * branch            main       -> FETCH_HEAD
error: The following untracked working tree files would be overwritten by merge:
\tcommands/scripts/foo.sh
\tcommands/scripts/bar.sh
Please move or remove them before you merge.
Aborting
"""

_ORIGIN = "newjob_resolve_pull_conflict.get_origin_content"
_PULL = "newjob_resolve_pull_conflict.try_pull"


class TestParseConflictingFiles:
    def test_parses_files_from_merge_error(self) -> None:
        """RESOLVE-DT-001: 從標準 git merge error 解析出兩個檔案路徑。"""
        files = parse_conflicting_files(_GIT_STDERR)
        assert files == ["commands/scripts/foo.sh", "commands/scripts/bar.sh"]

    def test_returns_empty_on_unrelated_error(self) -> None:
        """RESOLVE-DT-002: 非衝突錯誤回傳空列表。"""
        assert parse_conflicting_files("error: network timeout\n") == []

    def test_returns_empty_on_empty_string(self) -> None:
        """RESOLVE-EG-001: 空字串回傳空列表。"""
        assert parse_conflicting_files("") == []

    def test_handles_single_file(self) -> None:
        """RESOLVE-DT-003: 只有一個衝突檔案時正確解析。"""
        stderr = (
            "error: The following untracked working tree files would be overwritten by merge:\n"
            "\tonly_one.sh\n"
            "Please move or remove them before you merge.\n"
        )
        assert parse_conflicting_files(stderr) == ["only_one.sh"]


class TestIsIdenticalToOrigin:
    def test_identical_content_returns_true(self, tmp_path: Path) -> None:
        """RESOLVE-DT-004: 本地檔案與 origin/main 相同時回傳 True。"""
        content = b"#!/bin/bash\necho hello\n"
        f = tmp_path / "script.sh"
        f.write_bytes(content)
        with patch(_ORIGIN, return_value=content):
            assert is_identical_to_origin(str(f)) is True

    def test_different_content_returns_false(self, tmp_path: Path) -> None:
        """RESOLVE-DT-005: 本地檔案與 origin/main 不同時回傳 False。"""
        f = tmp_path / "script.sh"
        f.write_bytes(b"local changes\n")
        with patch(_ORIGIN, return_value=b"origin version\n"):
            assert is_identical_to_origin(str(f)) is False

    def test_missing_local_file_returns_false(self, tmp_path: Path) -> None:
        """RESOLVE-EG-002: 本地檔案不存在時回傳 False。"""
        with patch(_ORIGIN, return_value=b"content"):
            assert is_identical_to_origin(str(tmp_path / "nonexistent.sh")) is False

    def test_origin_unavailable_returns_false(self, tmp_path: Path) -> None:
        """RESOLVE-EG-003: origin/main 無法取得時回傳 False（保守策略）。"""
        f = tmp_path / "script.sh"
        f.write_bytes(b"content\n")
        with patch(_ORIGIN, return_value=None):
            assert is_identical_to_origin(str(f)) is False


class TestMain:
    def test_immediate_pull_success_exits_0(self) -> None:
        """RESOLVE-DT-006: 第一次 pull 就成功，直接 exit 0。"""
        with patch(_PULL, return_value=(True, "")):
            assert main() == 0

    def test_unrecognized_pull_error_exits_1(self) -> None:
        """RESOLVE-DT-007: pull 失敗但非 untracked 衝突，exit 1。"""
        with patch(_PULL, return_value=(False, "network error")):
            assert main() == 1

    def test_identical_files_deleted_and_pull_retried(self, tmp_path: Path) -> None:
        """RESOLVE-DT-008: identical untracked 檔案被刪除後 pull 重試成功。"""
        f1 = tmp_path / "a.sh"
        f2 = tmp_path / "b.sh"
        f1.write_bytes(b"content")
        f2.write_bytes(b"content")

        stderr = (
            "error: The following untracked working tree files would be overwritten by merge:\n"
            f"\t{f1}\n"
            f"\t{f2}\n"
            "Please move or remove them before you merge.\n"
        )
        pull_calls = iter([(False, stderr), (True, "")])
        with patch(_PULL, side_effect=pull_calls), patch(_ORIGIN, return_value=b"content"):
            result = main()

        assert result == 0
        assert not f1.exists()
        assert not f2.exists()

    def test_modified_file_exits_1_file_preserved(self, tmp_path: Path) -> None:
        """RESOLVE-DT-009: 本地有修改的檔案不刪除，exit 1 並警告使用者。"""
        f = tmp_path / "modified.sh"
        f.write_bytes(b"local changes")

        stderr = (
            "error: The following untracked working tree files would be overwritten by merge:\n"
            f"\t{f}\n"
            "Please move or remove them before you merge.\n"
        )
        with patch(_PULL, return_value=(False, stderr)), patch(_ORIGIN, return_value=b"origin"):
            result = main()

        assert result == 1
        assert f.exists()

    def test_retry_pull_fails_exits_1(self, tmp_path: Path) -> None:
        """RESOLVE-EG-004: 刪除衝突檔案後重試 pull 仍失敗，exit 1。"""
        f = tmp_path / "a.sh"
        f.write_bytes(b"content")

        stderr = (
            "error: The following untracked working tree files would be overwritten by merge:\n"
            f"\t{f}\n"
            "Please move or remove them before you merge.\n"
        )
        pull_calls = iter([(False, stderr), (False, "network error after delete")])
        with patch(_PULL, side_effect=pull_calls), patch(_ORIGIN, return_value=b"content"):
            result = main()

        assert result == 1
