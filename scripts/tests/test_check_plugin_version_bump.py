"""check_plugin_version_bump.py 的行為測試。

每個測試在 tmp_path 建一個小 git repo（兩個 plugin，lockstep 1.0.0），在 feature branch 上
做改動，再以 main 為 base、feature 為 head 執行檢查。最後一組測試對 main() 斷言 exit code，
確認 CI 實際走的入口也照判定結果結束。
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_plugin_version_bump as cpvb  # noqa: E402

PLUGINS = ("alpha", "beta")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _write_versions(repo: Path, version: str, only: str | None = None) -> None:
    for name in PLUGINS:
        if only is not None and name != only:
            continue
        for rel in (".claude-plugin/plugin.json", "package.json"):
            path = repo / "plugins" / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    _write_versions(r, "1.0.0")
    for name in PLUGINS:
        skill = r / "plugins" / name / "skills" / "s" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("v1\n", encoding="utf-8")
        test = r / "plugins" / name / "skills" / "s" / "scripts" / "tests" / "test_x.py"
        test.parent.mkdir(parents=True)
        test.write_text("def test_x(): pass\n", encoding="utf-8")
    (r / "README.md").write_text("root\n", encoding="utf-8")
    _commit(r, "init")
    _git(r, "switch", "-q", "-c", "feature")
    return r


def _edit_skill(repo: Path, name: str = "alpha") -> None:
    (repo / "plugins" / name / "skills" / "s" / "SKILL.md").write_text("v2\n", encoding="utf-8")


def _run(repo: Path) -> tuple[int, list[str]]:
    return cpvb.check(str(repo), "main", "feature")


class TestTrigger:
    def test_skill_change_without_bump_fails(self, repo: Path) -> None:
        _edit_skill(repo)
        _commit(repo, "edit skill")
        code, lines = _run(repo)
        assert code == 1
        assert "版號沒有升" in lines[0]
        assert "    plugins/alpha/skills/s/SKILL.md" in lines

    def test_skill_change_with_lockstep_bump_passes(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "1.0.1")
        _commit(repo, "edit skill and bump")
        code, lines = _run(repo)
        assert code == 0
        assert lines == ["[OK] plugin 版號 1.0.0 -> 1.0.1（1 個出貨檔案改動）"]

    def test_non_plugin_change_skips(self, repo: Path) -> None:
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        _commit(repo, "edit readme")
        assert _run(repo) == (0, ["[SKIP] 沒有改到 plugin 出貨內容，不需要升版"])

    def test_tests_only_change_skips(self, repo: Path) -> None:
        test = repo / "plugins" / "alpha" / "skills" / "s" / "scripts" / "tests" / "test_x.py"
        test.write_text("def test_y(): pass\n", encoding="utf-8")
        _commit(repo, "edit test")
        assert _run(repo)[0] == 0

    def test_version_files_only_change_skips(self, repo: Path) -> None:
        _write_versions(repo, "1.0.1")
        _commit(repo, "bump only")
        assert _run(repo)[0] == 0

    def test_file_named_tests_is_still_shipped(self, repo: Path) -> None:
        # 只有「tests 目錄」才豁免；檔名剛好叫 tests 的出貨檔仍要升版
        (repo / "plugins" / "alpha" / "tests").write_text("x\n", encoding="utf-8")
        _commit(repo, "add file named tests")
        assert _run(repo)[0] == 1


class TestVersionRules:
    def test_partial_bump_breaks_lockstep(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "1.0.1", only="alpha")
        _commit(repo, "bump alpha only")
        code, lines = _run(repo)
        assert code == 1
        assert lines[0].startswith("[FAIL] head 上的 plugin 版號不一致")
        assert "  plugins/beta/package.json: 1.0.0" in lines

    def test_downgrade_without_shipped_change_fails(self, repo: Path) -> None:
        # 舊版 make release 的降版 commit 只改版號檔，也必須被擋下
        _write_versions(repo, "0.9.9")
        _commit(repo, "release downgrade")
        code, lines = _run(repo)
        assert code == 1
        assert lines[0] == "[FAIL] plugin 版號從 1.0.0 降為 0.9.9。"

    def test_broken_lockstep_without_shipped_change_fails(self, repo: Path) -> None:
        _write_versions(repo, "1.0.1", only="alpha")
        _commit(repo, "bump alpha only, no content")
        assert _run(repo)[0] == 1

    def test_downgrade_fails(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "0.9.9")
        _commit(repo, "downgrade")
        assert _run(repo)[0] == 1

    def test_compares_numerically_not_lexically(self, repo: Path) -> None:
        # 字串比較會把 1.0.10 判成小於 1.0.9
        _write_versions(repo, "1.0.9")
        _commit(repo, "to 1.0.9")
        _git(repo, "switch", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "feature")
        _git(repo, "switch", "-q", "feature")
        _edit_skill(repo)
        _write_versions(repo, "1.0.10")
        _commit(repo, "to 1.0.10")
        assert _run(repo)[0] == 0

    def test_uses_merge_base_not_base_tip(self, repo: Path) -> None:
        # main 在 PR 開出之後另外前進（改了 README），PR 仍以分岔點的版號比較
        _edit_skill(repo)
        _write_versions(repo, "1.0.1")
        _commit(repo, "feature bump")
        _git(repo, "switch", "-q", "main")
        (repo / "README.md").write_text("main moved\n", encoding="utf-8")
        _commit(repo, "main moves")
        _git(repo, "switch", "-q", "feature")
        assert _run(repo)[0] == 0


class TestDataErrors:
    def test_prerelease_version_is_data_error(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "1.0.1-rc1")
        _commit(repo, "prerelease")
        with pytest.raises(cpvb.DataError, match="不是 X.Y.Z"):
            _run(repo)

    def test_missing_package_json_is_data_error(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "1.0.1")
        (repo / "plugins" / "beta" / "package.json").unlink()
        _commit(repo, "drop package.json")
        with pytest.raises(cpvb.DataError):
            _run(repo)

    def test_unknown_ref_is_data_error(self, repo: Path) -> None:
        with pytest.raises(cpvb.DataError):
            cpvb.check(str(repo), "main", "no-such-ref")


class TestMainExitCodes:
    def test_main_returns_1_on_missing_bump(self, repo: Path) -> None:
        _edit_skill(repo)
        _commit(repo, "edit skill")
        assert cpvb.main(["--repo", str(repo), "--base", "main", "--head", "feature"]) == 1

    def test_main_returns_0_on_bump(self, repo: Path) -> None:
        _edit_skill(repo)
        _write_versions(repo, "1.1.0")
        _commit(repo, "bump minor")
        assert cpvb.main(["--repo", str(repo), "--base", "main", "--head", "feature"]) == 0

    def test_main_returns_2_on_data_error(self, repo: Path) -> None:
        assert cpvb.main(["--repo", str(repo), "--base", "main", "--head", "no-such-ref"]) == 2
