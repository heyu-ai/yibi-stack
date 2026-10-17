"""以離線真實依賴驗證 pre-review 到 locked verifier／trace checker 的完整消費端。"""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

_CHECKER = Path(__file__).resolve().parents[6] / "plugins/sdd/scripts/check_testplan_trace.py"
_PLAN = """trace: enforced

| TC-ID | Kind | Test Purpose |
|-------|------|--------------|
| LAUNCH-001 | auto | custom root trace |
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    """只操作隔離的 fixture repo，所有 subprocess 都有期限。"""
    result = subprocess.run(  # nosec B603 B607
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def _lock(script: Path, repo: Path, env: dict[str, str]) -> None:
    """由真實 uv 依本機 wheel feed 產生鎖檔；不讀 registry 或現有 cache。"""
    result = subprocess.run(  # nosec B603 B607
        ["uv", "lock", "--offline", "--no-config", "--script", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def launcher_consumer(
    tmp_path: Path,
    review_runtime_copy: Path,
    review_dependency_wheels: Path,
    review_uv: Path,
    request: pytest.FixtureRequest,
) -> tuple[Path, Path, dict[str, str]]:
    """僅替換外部 GitHub 回應；launcher、uv、YAML 與 checker 均為真實程式。"""
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").symlink_to(review_uv)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "GIT_"))
        and key not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}
    }
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_CACHE_HOME=str(home / ".cache"),
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        UV_CACHE_DIR=str(tmp_path / "uv-cache"),
        UV_PYTHON=sys.executable,
        UV_PYTHON_DOWNLOADS="never",
        UV_OFFLINE="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    registry = home / ".claude/plugins/installed_plugins.json"
    _write(
        registry,
        json.dumps({"plugins": {"sdd@yibi-stack": [{"installPath": str(_CHECKER.parent.parent)}]}}),
    )
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, env, "init", "--initial-branch=main")
    _write(repo / "README.txt", "consumer\n")
    _git(repo, env, "add", ".")
    _git(repo, env, "commit", "-m", "initial")
    change = repo / "docs/specs/changes/demo"
    _write(repo / ".spectra.yaml", '{spec_dir: "docs/specs"} # custom root\n')
    _write(change / "testplan.md", _PLAN)
    _write(change / "proposal.md", "---\ntype: feat\n---\n")
    _write(change / "tasks.md", "- [x] launcher contract\n")
    if getattr(request, "param", True):
        _write(
            repo / "tests/test_consumer.py",
            'def test_consumer():\n    """tc: LAUNCH-001"""\n    assert True\n',
        )
    _git(repo, env, "add", ".")
    _git(repo, env, "commit", "-m", "custom root change")
    files = [
        {"status": "added", "filename": path}
        for path in _git(repo, env, "diff", "--name-only", "HEAD^", "HEAD").splitlines()
    ]
    metadata = {
        "baseRefOid": _git(repo, env, "rev-parse", "HEAD^"),
        "headRefOid": _git(repo, env, "rev-parse", "HEAD"),
        "changedFiles": len(files),
        "additions": 10,
        "deletions": 0,
    }
    diff = _git(repo, env, "diff", "HEAD^", "HEAD")
    gh = bin_dir / "gh"
    _write(
        gh,
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"metadata = {metadata!r}\nfiles = {files!r}\ndiff = {diff!r}\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['pr', os.environ.get('LAUNCHER_GH_FAILURE')]:\n"
        "    print('HTTP 401: Bad credentials', file=sys.stderr)\n    sys.exit(1)\n"
        "elif args[:2] == ['repo', 'view']:\n    print('owner/consumer')\n"
        "elif args[:2] == ['pr', 'view']:\n    print(json.dumps(metadata))\n"
        "elif args[:2] == ['pr', 'checks']:\n"
        "    print(json.dumps([{'name': 'ci', 'bucket': 'pass'}]))\n"
        "elif args[:1] == ['api']:\n    print(json.dumps([files]))\n"
        "elif args[:2] == ['pr', 'diff']:\n    print(diff)\n"
        "else:\n    sys.exit(97)\n",
    )
    gh.chmod(0o755)
    script = review_runtime_copy / "amplifier-verify.py"
    shipped_lock = subprocess.run(  # nosec B603 B607
        ["uv", "lock", "--check", "--offline", "--no-config", "--script", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert shipped_lock.returncode == 0, shipped_lock.stdout + shipped_lock.stderr
    original = script.read_text(encoding="utf-8")
    settings = (
        "\n# [tool.uv]\n# no-index = true\n"
        f"# find-links = [{json.dumps(str(review_dependency_wheels))}]\n# ///\n"
    )
    local = original.replace("\n# ///\n", settings, 1)
    assert local != original, "無法建立離線 standalone runtime fixture"
    script.write_text(local, encoding="utf-8")
    # fixture 的本機 feed 必須重新解析來源，不能沿用發布鎖檔內的 registry URL。
    script.with_suffix(".py.lock").unlink()
    _lock(script, repo, env)
    return repo, review_runtime_copy, env


def _launch(
    consumer: tuple[Path, Path, dict[str, str]],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo, runtime, env = consumer
    result = subprocess.run(  # nosec B603
        [sys.executable, str(runtime / "pre_review_check.py"), "--pr", "42"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result, repo / ".pr-review/pre-review-check.md"


@pytest.mark.parametrize(
    "launcher_consumer", [True, False], indirect=True, ids=["bound", "unbound"]
)
def test_launcher_custom_plan_reports_real_trace_result(launcher_consumer):
    """已綁定計畫成功，完成 tasks 卻未綁定的 enforced TC 必須成為阻擋 finding。"""
    repo, _, env = launcher_consumer
    bound = (repo / "tests/test_consumer.py").exists()
    result, report = _launch(launcher_consumer)
    assert result.returncode == (0 if bound else 1), result.stdout + result.stderr
    assert f"REPORT={report}" in result.stdout
    content = report.read_text(encoding="utf-8")
    assert "spectra change detected: demo" in content
    assert "- CI: pass 1" in content
    if bound:
        assert "[MUST]" not in content
        assert "[SHOULD]" not in content
    else:
        assert "[MUST]" in content and "missing:" in content
        assert "LAUNCH-001" in content
    assert _git(repo, env, "check-ignore", ".pr-review/pre-review-check.md")


def test_launcher_ignores_host_project_and_uv_configuration(launcher_consumer):
    """不相容 host Python 與損壞的 repo／使用者 uv 設定不得污染 standalone runtime。"""
    repo, runtime, env = launcher_consumer
    project = '[project]\nname="unrelated-host"\nversion="0.0.0"\nrequires-python=">=99"\n'
    _write(repo / "pyproject.toml", project)
    _write(repo / "uv.toml", "[invalid TOML\n")
    _write(Path(env["XDG_CONFIG_HOME"]) / "uv/uv.toml", "[invalid user TOML\n")
    lock = runtime / "amplifier-verify.py.lock"
    before = lock.read_bytes()
    result, report = _launch(launcher_consumer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "spectra change detected: demo" in report.read_text(encoding="utf-8")
    assert lock.read_bytes() == before
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == project
    assert not (repo / "uv.lock").exists()
    assert not (repo / ".venv").exists()


def test_launcher_rejects_stale_lock_and_recovers_after_explicit_relock(launcher_consumer):
    """metadata drift 必須可見地停止，不能自改鎖檔；明確離線 relock 後可恢復驗證。"""
    repo, runtime, env = launcher_consumer
    control, report = _launch(launcher_consumer)
    assert control.returncode == 0, control.stdout + control.stderr
    assert "spectra change detected: demo" in report.read_text(encoding="utf-8")
    script = runtime / "amplifier-verify.py"
    lock = script.with_suffix(".py.lock")
    before = lock.read_bytes()
    original = script.read_text(encoding="utf-8")
    version = importlib.metadata.version("markdown-it-py")
    changed = original.replace(
        "# dependencies = [", f'# dependencies = ["markdown-it-py=={version}", ', 1
    )
    assert changed != original, "無法建立 stale-lock fixture"
    script.write_text(changed, encoding="utf-8")
    rejected, report = _launch(launcher_consumer)
    assert rejected.returncode == 2, rejected.stdout + rejected.stderr
    content = report.read_text(encoding="utf-8")
    assert "[FAIL]" in content
    assert "lock" in content.lower()
    assert "spectra change detected: demo" not in content
    assert lock.read_bytes() == before
    _lock(script, repo, env)
    recovered, report = _launch(launcher_consumer)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert "spectra change detected: demo" in report.read_text(encoding="utf-8")
    assert not (repo / "uv.lock").exists()
    assert not (repo / ".venv").exists()


def test_launcher_preserves_verifier_configuration_error_in_report(launcher_consumer):
    """真實 YAML 解析失敗必須停止，且把 verifier 的具體原因留在報告中。"""
    repo, _, _ = launcher_consumer
    _write(repo / ".spectra.yaml", "spec_dir: [invalid\n")
    result, report = _launch(launcher_consumer)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL]" in result.stdout
    assert "Spectra 設定錯誤" in report.read_text(encoding="utf-8")


@pytest.mark.parametrize("broken", ["view", "checks"])
def test_launcher_github_error_is_not_reported_as_ci_success(launcher_consumer, broken):
    """外部 GitHub 失敗不可被其他成功結果掩蓋，詳細原因必須保留。"""
    _, _, env = launcher_consumer
    env["LAUNCHER_GH_FAILURE"] = broken
    result, report = _launch(launcher_consumer)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "HTTP 401: Bad credentials" in result.stderr
    assert "HTTP 401: Bad credentials" in report.read_text(encoding="utf-8")


def test_launcher_report_write_failure_keeps_failure_visible(launcher_consumer):
    """報告路徑無法建立時仍須可見地停止，不只留下沒有內容的 REPORT 提示。"""
    repo, _, env = launcher_consumer
    _write(repo / ".pr-review", "not a directory\n")
    env["LAUNCHER_GH_FAILURE"] = "checks"
    result, _ = _launch(launcher_consumer)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[FAIL] 無法寫入" in result.stderr
    assert "HTTP 401: Bad credentials" in result.stderr
    assert "REPORT=" not in result.stdout
