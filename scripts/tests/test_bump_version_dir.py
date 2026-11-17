"""bump.sh `--dir` 的黑盒測試。

monorepo 的版號檔不在 repo 根目錄（例：yibi-mvp 的 `backend/pyproject.toml`、
`story-lab/package.json`）。`--dir <path>` 讓 bump.sh 只升那個目錄的版號檔；
不帶 `--dir` 時行為與原本相同（`scripts/release-full.sh` 依賴這一點）。

每個測試以 `BUMP_RESULT_ENV` 指定自己的結果檔，避免共用 `/tmp/bump_version_result.env`。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import json
import os
import shlex
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


def _run(
    repo: Path,
    result_env: Path | str | None,
    *args: str,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_KEYS}
    env.pop("BUMP_RESULT_ENV", None)
    if result_env is not None:
        env["BUMP_RESULT_ENV"] = str(result_env)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # nosec B603
        ["bash", str(SCRIPT), *args],
        cwd=cwd or repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_env(path: Path) -> dict[str, str]:
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        # 結果檔用 printf %q 輸出（供 source），含空格的值會被跳脫
        parts = shlex.split(value)
        pairs[key] = parts[0] if parts else ""
    return pairs


class TestBumpDir:
    def test_bump_dt_001_dir_bumps_python_in_subdir(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-DT-001: --dir backend minor 只升 backend/pyproject.toml，結果檔記錄元件目錄"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "backend", "minor")
        assert proc.returncode == 0, proc.stderr
        assert 'version = "0.12.0"' in (monorepo / "backend" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        assert (
            json.loads((monorepo / "story-lab" / "package.json").read_text(encoding="utf-8"))[
                "version"
            ]
            == "0.98.0"
        )
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
        assert (
            json.loads((monorepo / "story-lab" / "package.json").read_text(encoding="utf-8"))[
                "version"
            ]
            == "0.98.1"
        )
        assert 'version = "0.11.0"' in (monorepo / "backend" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        assert _read_env(result_env)["VERSION_FILE"] == "story-lab/package.json"

    def test_bump_vl_003_missing_dir_fails_without_change(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-VL-003: --dir 指向不存在的目錄時以 [FAIL] 結束，不改任何檔案"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "admin", "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "admin" in proc.stderr
        assert not result_env.exists()
        assert 'version = "0.11.0"' in (monorepo / "backend" / "pyproject.toml").read_text(
            encoding="utf-8"
        )

    def test_bump_vl_004_dir_without_value_fails(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-VL-004: --dir 後面沒有值時以 [FAIL] 結束，不是 unbound variable"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "--dir 需要一個目錄參數" in proc.stderr
        assert "unbound" not in proc.stderr
        assert not result_env.exists()

    def test_bump_vl_005_dir_outside_repo_fails(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-VL-005: --dir 指向 repo 之外時拒絕，避免升到別的專案的版號"""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "package.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", str(outside), "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "不在 repo 內" in proc.stderr
        assert not result_env.exists()
        assert (
            json.loads((outside / "package.json").read_text(encoding="utf-8"))["version"] == "1.0.0"
        )

    def test_bump_dt_006_no_dir_keeps_root_behavior(self, tmp_path: Path) -> None:
        """BUMP-DT-006: 不帶 --dir 時照舊升根目錄的版號檔（release-full.sh 依賴此行為）"""
        repo = tmp_path / "root-repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.24.3"\n', encoding="utf-8"
        )
        _git(repo, "init", "-q")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "patch")
        assert proc.returncode == 0, proc.stderr
        assert 'version = "1.24.4"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "pyproject.toml"
        assert env["COMPONENT_DIR"] == "."


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    return repo


def _pyproject(path: Path, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")


def _version_in(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestBumpDirRegression:
    def test_bump_rg_001_subdir_cwd_without_dir_keeps_cwd_relative(self, tmp_path: Path) -> None:
        """BUMP-RG-001: 不帶 --dir、cwd 在 repo 子目錄時，VERSION_FILE 不加前綴、COMPONENT_DIR 為 ."""
        repo = _make_repo(tmp_path)
        _pyproject(repo / "sub" / "pyproject.toml", "2.0.0")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "patch", cwd=repo / "sub")
        assert proc.returncode == 0, proc.stderr
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "pyproject.toml"
        assert env["COMPONENT_DIR"] == "."
        assert 'version = "2.0.1"' in _version_in(repo / "sub" / "pyproject.toml")

    def test_bump_rg_002_no_bump_type_defaults_to_patch_in_node_root(self, tmp_path: Path) -> None:
        """BUMP-RG-002: 沒給 bump type 時預設 patch；Node 根目錄、不帶 --dir"""
        repo = _make_repo(tmp_path)
        (repo / "package.json").write_text('{"name": "n", "version": "3.1.4"}\n', encoding="utf-8")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env)
        assert proc.returncode == 0, proc.stderr
        env = _read_env(result_env)
        assert env["BUMP_VERSION"] == "3.1.5"
        assert env["VERSION_FILE"] == "package.json"
        assert env["PROJECT_TYPE"] == "nodejs"

    def test_bump_rg_003_cdpath_does_not_break_relative_dir(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-RG-003: CDPATH 設成 .:.. 時相對 --dir 仍成功（腳本清掉 CDPATH）"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "backend", "patch", extra_env={"CDPATH": ".:.."})
        assert proc.returncode == 0, proc.stderr
        assert _read_env(result_env)["VERSION_FILE"] == "backend/pyproject.toml"


class TestBumpDirShapes:
    def test_bump_dt_010_nested_dir_and_resolved_paths(self, tmp_path: Path) -> None:
        """BUMP-DT-010: 巢狀 --dir services/api；REPO_ROOT 與 BUMP_VERSION 都要斷言"""
        repo = _make_repo(tmp_path)
        _pyproject(repo / "services" / "api" / "pyproject.toml", "0.5.0")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "--dir", "services/api", "minor")
        assert proc.returncode == 0, proc.stderr
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "services/api/pyproject.toml"
        assert env["COMPONENT_DIR"] == "services/api"
        assert env["BUMP_VERSION"] == "0.6.0"
        assert Path(env["REPO_ROOT"]).resolve() == repo.resolve()

    def test_bump_dt_011_dir_after_bump_type(self, monorepo: Path, tmp_path: Path) -> None:
        """BUMP-DT-011: --dir 放在 bump type 之後也成立"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "minor", "--dir", "backend")
        assert proc.returncode == 0, proc.stderr
        assert _read_env(result_env)["BUMP_VERSION"] == "0.12.0"

    def test_bump_dt_012_absolute_in_repo_dir_accepted(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-DT-012: repo 內的絕對路徑 --dir 可接受，結果檔仍是相對路徑"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", str(monorepo / "backend"), "patch")
        assert proc.returncode == 0, proc.stderr
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "backend/pyproject.toml"
        assert env["COMPONENT_DIR"] == "backend"

    def test_bump_vl_013_sibling_prefix_dir_rejected(self, tmp_path: Path) -> None:
        """BUMP-VL-013: 與 repo 同前綴的兄弟目錄（../repo-other）被拒絕，檔案不變"""
        repo = _make_repo(tmp_path)
        _pyproject(repo / "pyproject.toml", "1.0.0")
        other = tmp_path / "repo-other"
        _pyproject(other / "pyproject.toml", "9.0.0")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "--dir", "../repo-other", "patch")
        assert proc.returncode != 0
        assert "不在 repo 內" in proc.stderr
        assert 'version = "9.0.0"' in _version_in(other / "pyproject.toml")
        assert not result_env.exists()

    def test_bump_vl_014_symlink_escaping_repo_rejected(self, tmp_path: Path) -> None:
        """BUMP-VL-014: repo 內指向 repo 外的 symlink 被拒絕，外部檔案不變"""
        repo = _make_repo(tmp_path)
        _pyproject(repo / "pyproject.toml", "1.0.0")
        outside = tmp_path / "outside"
        _pyproject(outside / "pyproject.toml", "7.0.0")
        (repo / "link").symlink_to(outside, target_is_directory=True)
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "--dir", "link", "patch")
        assert proc.returncode != 0
        assert "不在 repo 內" in proc.stderr
        assert 'version = "7.0.0"' in _version_in(outside / "pyproject.toml")
        assert not result_env.exists()

    def test_bump_vl_015_repeated_dir_and_type_rejected(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-VL-015: 重複的 --dir 或 bump type 以 [FAIL] 結束，--dir=<path> 有明確訊息"""
        result_env = tmp_path / "result.env"
        proc = _run(monorepo, result_env, "--dir", "backend", "--dir", "story-lab", "patch")
        assert proc.returncode != 0
        assert "--dir 只能指定一次" in proc.stderr
        proc = _run(monorepo, result_env, "--dir", "backend", "patch", "minor")
        assert proc.returncode != 0
        assert "bump type 只能指定一次" in proc.stderr
        proc = _run(monorepo, result_env, "--dir=backend", "patch")
        assert proc.returncode != 0
        assert "等號" in proc.stderr
        assert 'version = "0.11.0"' in _version_in(monorepo / "backend" / "pyproject.toml")
        assert not result_env.exists()


class TestBumpPlatforms:
    def test_bump_dt_020_flutter_dir_uses_repo_relative_composite(self, tmp_path: Path) -> None:
        """BUMP-DT-020: Flutter 搭配 --dir 時，複合 VERSION_FILE 的每個路徑都是 repo 根目錄相對"""
        repo = _make_repo(tmp_path)
        (repo / "mobile").mkdir()
        (repo / "mobile" / "pubspec.yaml").write_text(
            "name: app\nversion: 1.2.3+4\n", encoding="utf-8"
        )
        (repo / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "--dir", "mobile", "patch")
        assert proc.returncode == 0, proc.stderr
        env = _read_env(result_env)
        assert env["VERSION_FILE"] == "mobile/pubspec.yaml + VERSION"
        assert env["COMPONENT_DIR"] == "mobile"
        assert env["BUMP_VERSION"] == "1.2.4+5"
        assert (repo / "VERSION").read_text(encoding="utf-8").strip() == "1.2.4"

    def test_bump_vl_021_go_with_component_dir_fails_without_result(self, tmp_path: Path) -> None:
        """BUMP-VL-021: Go 專案搭配非 . 的 --dir 以 [FAIL] 結束，不寫結果檔"""
        repo = _make_repo(tmp_path)
        (repo / "svc").mkdir()
        (repo / "svc" / "go.mod").write_text("module example.com/svc\n", encoding="utf-8")
        result_env = tmp_path / "result.env"
        proc = _run(repo, result_env, "--dir", "svc", "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "git tag" in proc.stderr
        assert not result_env.exists()


class TestBumpResultFile:
    def test_bump_dt_030_relative_result_env_lands_in_invocation_cwd(self, monorepo: Path) -> None:
        """BUMP-DT-030: 相對 BUMP_RESULT_ENV 相對於執行時的目錄，不是元件目錄"""
        proc = _run(monorepo, "rel-result.env", "--dir", "backend", "patch")
        assert proc.returncode == 0, proc.stderr
        assert (monorepo / "rel-result.env").is_file()
        assert not (monorepo / "backend" / "rel-result.env").exists()

    def test_bump_vl_031_unwritable_result_fails_before_any_change(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-VL-031: 結果檔路徑不可寫時在改版號檔之前 [FAIL]"""
        bad = tmp_path / "no-such-dir" / "result.env"
        proc = _run(monorepo, bad, "--dir", "backend", "patch")
        assert proc.returncode != 0
        assert "[FAIL]" in proc.stderr
        assert "結果檔" in proc.stderr
        assert 'version = "0.11.0"' in _version_in(monorepo / "backend" / "pyproject.toml")

    def test_bump_vl_032_failed_run_removes_stale_result(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-VL-032: 失敗的執行不留結果檔（過期結果檔會被清掉）"""
        result_env = tmp_path / "result.env"
        result_env.write_text("BUMP_VERSION=stale\n", encoding="utf-8")
        proc = _run(monorepo, result_env, "--dir", "admin", "patch")
        assert proc.returncode != 0
        assert not result_env.exists()

    def test_bump_dt_033_default_tmp_fallback_not_written_when_env_set(
        self, monorepo: Path, tmp_path: Path
    ) -> None:
        """BUMP-DT-033: 設了 BUMP_RESULT_ENV 就不寫預設的 /tmp/bump_version_result.env"""
        default = Path("/tmp/bump_version_result.env")  # nosec B108
        before = default.stat().st_mtime_ns if default.exists() else None
        proc = _run(monorepo, tmp_path / "result.env", "--dir", "backend", "patch")
        assert proc.returncode == 0, proc.stderr
        after = default.stat().st_mtime_ns if default.exists() else None
        assert before == after
