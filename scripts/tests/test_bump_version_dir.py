"""bump.sh `--dir` 的黑盒測試。

monorepo 的版號檔不在 repo 根目錄（例：yibi-mvp 的 `backend/pyproject.toml`、
`story-lab/package.json`）。`--dir <path>` 讓 bump.sh 只升那個目錄的版號檔；
不帶 `--dir` 時行為與原本相同（`scripts/release-full.sh` 依賴這一點）。

每個測試以 `BUMP_RESULT_ENV` 指定自己的結果檔，避免共用 `/tmp/bump_version_result.env`。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import json
import os
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "plugins" / "dev-cycle" / "skills" / "bump-version" / "scripts" / "bump.sh"

_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture()
def monorepo(tmp_path: Path) -> Path:
    """根目錄沒有版號檔、子目錄各有一個版號檔的 git repo。"""
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "story-lab").mkdir()
    (repo / "backend" / "pyproject.toml").write_text(
        '[project]\nname = "demo-backend"\nversion = "0.11.0"\n', encoding="utf-8"
    )
    (repo / "story-lab" / "package.json").write_text(
        json.dumps({"name": "story-lab", "version": "0.98.0"}, indent=2) + "\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run(repo: Path, result_env: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_KEYS}
    env["BUMP_RESULT_ENV"] = str(result_env)
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_env(path: Path) -> dict[str, str]:
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        pairs[key] = value
    return pairs


class TestBumpDir:
    def test_bump_dt_001_dir_bumps_python_in_subdir(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-DT-001: --dir backend minor 只升 backend/pyproject.toml，結果檔記錄元件目錄"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "backend", "minor")
        assert proc.returncode == 0, proc.stderr
        assert 'version = "0.12.0"' in (monorepo / "backend" / "pyproject.toml").read_text(encoding="utf-8")
        assert json.loads((monorepo / "story-lab" / "package.json").read_text(encoding="utf-8"))["version"] == "0.98.0"
        env = _read_env(result_env)
        assert env["TAG_VERSION"] == "0.12.0"
        assert env["VERSION_FILE"] == "backend/pyproject.toml"
        assert env["COMPONENT_DIR"] == "backend"
        assert env["PROJECT_TYPE"] == "python"

    def test_bump_dt_002_dir_bumps_nodejs_in_subdir(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-DT-002: --dir story-lab patch 升 story-lab/package.json"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "story-lab", "patch")
        assert proc.returncode == 0, proc.stderr
        assert json.loads((monorepo / "story-lab" / "package.json").read_text(encoding="utf-8"))["version"] == "0.98.1"
        assert 'version = "0.11.0"' in (monorepo / "backend" / "pyproject.toml").read_text(encoding="utf-8")
        assert _read_env(result_env)["VERSION_FILE"] == "story-lab/package.json"

    def test_bump_vl_003_missing_dir_fails_without_change(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-VL-003: --dir 指向不存在的目錄時以 [FAIL] 結束，不改任何檔案"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "admin", "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "admin" in proc.stderr
        assert not result_env.exists()
        assert 'version = "0.11.0"' in (monorepo / "backend" / "pyproject.toml").read_text(encoding="utf-8")

    def test_bump_vl_004_dir_without_value_fails(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-VL-004: --dir 後面沒有值時以 [FAIL] 結束，不是 unbound variable"""
        proc = _run(monorepo, tmp_path / "result.env", "--dir")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "unbound" not in proc.stderr

    def test_bump_vl_005_dir_outside_repo_fails(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-VL-005: --dir 指向 repo 之外時拒絕，避免升到別的專案的版號"""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "package.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
        proc = _run(monorepo, tmp_path / "result.env", "--dir", str(outside), "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert json.loads((outside / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"

    def test_bump_dt_006_no_dir_keeps_root_behavior(self, tmp_path: Path) -> None:
        """BUMP-DT-006: 不帶 --dir 時照舊升根目錄的版號檔（release-full.sh 依賴此行為）"""
        repo = tmp_path / "root-repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.24.3"\n', encoding="utf-8")
        _git(repo, "init", "-q")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "patch")
        assert proc.returncode == 0, proc.stderr
        assert 'version = "1.24.4"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "pyproject.toml"
        assert env["COMPONENT_DIR"] == "."
