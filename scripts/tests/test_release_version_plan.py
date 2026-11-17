"""release_version_plan.py 與 release-full.sh 沿用 plugin 版號的行為測試。

單元測試直接對暫存目錄裡的 pyproject.toml 與 plugin 版號檔呼叫 plan()／main()。
端到端測試在暫存 git repo（附 bare origin）執行真正的 release-full.sh，SKILL_DIR 指向
stub：bump.sh 只記錄自己被呼叫，release.sh 記錄收到的 TAG_VERSION 而不打 tag。
情境取自 2026-11-13 的分析：兩個 PR 各升一次後 plugin 為 1.24.5、pyproject 為 1.24.3，
舊流程會算出 1.24.4 並把 plugin 降回 1.24.4。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import release_version_plan as rvp  # noqa: E402

PLUGINS = ("alpha", "beta")


def _write_plugins(root: Path, version: str, only: str | None = None) -> None:
    for name in PLUGINS:
        if only is not None and name != only:
            continue
        for rel in (".claude-plugin/plugin.json", "package.json"):
            path = root / "plugins" / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8")


def _write_pyproject(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8"
    )


def _pyproject(root: Path) -> str:
    return (root / "pyproject.toml").read_text(encoding="utf-8")


class TestPlan:
    def test_plugin_ahead_adopts_plugin_version(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.5")
        assert rvp.plan(tmp_path) == ("adopt", (1, 24, 5))

    def test_equal_versions_bump(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.3")
        assert rvp.plan(tmp_path) == ("bump", (1, 24, 3))

    def test_numeric_not_lexical_comparison(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.9")
        _write_plugins(tmp_path, "1.24.10")
        assert rvp.plan(tmp_path) == ("adopt", (1, 24, 10))

    def test_plugin_behind_pyproject_fails(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.5")
        _write_plugins(tmp_path, "1.24.3")
        with pytest.raises(rvp.PlanError, match="小於 pyproject.toml"):
            rvp.plan(tmp_path)

    def test_non_lockstep_plugins_fail(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.4", only="alpha")
        with pytest.raises(rvp.PlanError, match="plugin 版號不一致"):
            rvp.plan(tmp_path)

    def test_missing_pyproject_version_is_data_error(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        _write_plugins(tmp_path, "1.24.3")
        with pytest.raises(rvp.DataError):
            rvp.plan(tmp_path)


class TestMain:
    def test_apply_in_adopt_mode_updates_pyproject(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.5")
        assert rvp.main(["--root", str(tmp_path), "--apply"]) == 0
        assert capsys.readouterr().out == "MODE=adopt\nVERSION=1.24.5\n"
        assert 'version = "1.24.5"' in _pyproject(tmp_path)

    def test_apply_in_bump_mode_changes_nothing(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.3")
        before = _pyproject(tmp_path)
        assert rvp.main(["--root", str(tmp_path), "--apply"]) == 0
        assert _pyproject(tmp_path) == before

    def test_without_apply_adopt_changes_nothing(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.3")
        _write_plugins(tmp_path, "1.24.5")
        assert rvp.main(["--root", str(tmp_path)]) == 0
        assert 'version = "1.24.3"' in _pyproject(tmp_path)

    def test_exit_codes(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "1.24.5")
        _write_plugins(tmp_path, "1.24.3")
        assert rvp.main(["--root", str(tmp_path)]) == 1
        (tmp_path / "pyproject.toml").unlink()
        assert rvp.main(["--root", str(tmp_path)]) == 2


# --- 端到端：真正的 release-full.sh，bump/gates/release 為 stub ---

_STUBS = {
    "bump.sh": """#!/usr/bin/env bash
set -euo pipefail
echo "bump $1" >> "$STUB_LOG"
cur=$(sed -n 's/^version = "\\(.*\\)"$/\\1/p' pyproject.toml)
IFS=. read -r a b c <<< "$cur"
new="$a.$b.$((c + 1))"
sed -i.bak "s/^version = \\".*\\"$/version = \\"$new\\"/" pyproject.toml && rm -f pyproject.toml.bak
printf 'BUMP_VERSION=%s\\nTAG_VERSION=%s\\nVERSION_FILE=pyproject.toml\\nPROJECT_TYPE=python\\nREPO_ROOT=%s\\n' \\
  "$new" "$new" "$(git rev-parse --show-toplevel)" > /tmp/bump_version_result.env
""",
    "changelog.sh": """#!/usr/bin/env bash
set -euo pipefail
echo "## $1" >> CHANGELOG.md
""",
    "gates.sh": """#!/usr/bin/env bash
set -euo pipefail
printf 'GATES_PASSED=true\\n' >> /tmp/bump_version_result.env
""",
    "release.sh": """#!/usr/bin/env bash
set -euo pipefail
source /tmp/bump_version_result.env
echo "release $TAG_VERSION" >> "$STUB_LOG"
""",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # nosec


@pytest.fixture
def release_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)  # nosec
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "remote", "add", "origin", str(origin))
    (repo / "scripts").mkdir()
    for name in (
        "release-full.sh",
        "release_version_plan.py",
        "sync-plugin-versions.sh",
        "sync_plugin_versions.py",
    ):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)
    (repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    # 真實 repo 一定有 uv.lock；release-full.sh 的 Step 5 以 git diff 檢查它
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in _STUBS.items():
        path = stubs / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "stub.log"
    return repo, stubs, log


def _commit_and_push(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    _git(repo, "push", "-q", "origin", "main")


def _run_release(repo: Path, stubs: Path, log: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SKILL_DIR": str(stubs), "STUB_LOG": str(log), "FORCE": "1"}
    env.pop("CDPATH", None)
    return subprocess.run(  # nosec B603 B607
        ["bash", str(repo / "scripts" / "release-full.sh"), "patch"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _plugin_versions(repo: Path) -> set[str]:
    return {
        json.loads(p.read_text(encoding="utf-8"))["version"]
        for p in list(repo.glob("plugins/*/.claude-plugin/plugin.json"))
        + list(repo.glob("plugins/*/package.json"))
    }


class TestReleaseFullEndToEnd:
    def test_two_pr_bumps_are_adopted_without_downgrade(
        self, release_repo: tuple[Path, Path, Path]
    ) -> None:
        repo, stubs, log = release_repo
        _write_pyproject(repo, "1.24.3")
        _write_plugins(repo, "1.24.5")
        _commit_and_push(repo, "two PRs already bumped plugins")
        proc = _run_release(repo, stubs, log)
        assert proc.returncode == 0, proc.stderr
        assert log.read_text(encoding="utf-8").splitlines() == ["release 1.24.5"]
        assert _plugin_versions(repo) == {"1.24.5"}
        assert 'version = "1.24.5"' in _pyproject(repo)

    def test_equal_versions_still_bump(self, release_repo: tuple[Path, Path, Path]) -> None:
        repo, stubs, log = release_repo
        _write_pyproject(repo, "1.24.3")
        _write_plugins(repo, "1.24.3")
        _commit_and_push(repo, "no PR bump since last release")
        proc = _run_release(repo, stubs, log)
        assert proc.returncode == 0, proc.stderr
        assert log.read_text(encoding="utf-8").splitlines() == ["bump patch", "release 1.24.4"]
        assert _plugin_versions(repo) == {"1.24.4"}

    def test_plugin_behind_pyproject_stops_before_bump(
        self, release_repo: tuple[Path, Path, Path]
    ) -> None:
        repo, stubs, log = release_repo
        _write_pyproject(repo, "1.24.5")
        _write_plugins(repo, "1.24.3")
        _commit_and_push(repo, "inconsistent")
        proc = _run_release(repo, stubs, log)
        assert proc.returncode == 1
        assert "小於 pyproject.toml" in proc.stderr
        assert not log.exists()
        assert 'version = "1.24.5"' in _pyproject(repo)
