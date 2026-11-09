"""執行出貨的 bootstrap 命令，驗證載入目錄、獨立 shell 與必要 CLI。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "plugins/growth/skills/pr-retrospective"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
        capture_output=True,
        check=True,
        timeout=20,
    )


@pytest.fixture
def caller_worktree(tmp_path: Path) -> Path:
    main = tmp_path / "caller repository"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(
        main,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
    )
    worktree = tmp_path / "caller worktree"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))
    nested = worktree / "nested"
    nested.mkdir()
    return nested


def _environment(tmp_path: Path, *, mycelium: bool = True) -> dict[str, str]:
    home = tmp_path / "home"
    registry = home / ".claude/plugins/installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"plugins": {"growth@yibi-stack": [{"installPath": "/stale/cache"}]}})
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # 只提供前置條件的存在性；bootstrap 不應實際執行這些工具。
    for name in ("jq", "gh", *(("mycelium",) if mycelium else ())):
        path = binaries / name
        path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        path.chmod(0o755)
    for name in ("bash", "git", "basename", "dirname", "grep"):
        executable = shutil.which(name)
        assert executable is not None
        (binaries / name).symlink_to(executable)
    env = {**os.environ, "HOME": str(home), "PATH": str(binaries)}
    for name in (
        "RETRO_ROOT",
        "PR_FLOW_CACHED",
        "CLAUDE_SKILL_DIR",
        "CLAUDE_PLUGIN_ROOT",
        "GH_REPO",
    ):
        env.pop(name, None)
    return env


@pytest.mark.parametrize("layout", ["plugin-cache", "directory-symlink", "checkout"])
def test_loaded_skill_bootstraps_from_independent_shells(
    tmp_path: Path, caller_worktree: Path, layout: str
) -> None:
    root = SKILL
    if layout != "checkout":
        copied = tmp_path / "active plugin cache/skills/pr-retrospective"
        shutil.copytree(SKILL, copied)
        root = copied
        if layout == "directory-symlink":
            root = tmp_path / "loaded skill link"
            root.symlink_to(copied, target_is_directory=True)
    env = _environment(tmp_path)
    bootstrap = subprocess.run(  # nosec B603
        ["/bin/bash", str(root / "scripts/bootstrap.sh")],
        cwd=caller_worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    values = dict(line.split("=", 1) for line in bootstrap.stdout.splitlines())
    assert values == {
        "ORIG_PROJECT": "caller repository",
        "REAL_WORKDIR": str(caller_worktree.resolve()),
        "BRANCH": "feature",
    }
    detected = subprocess.run(  # nosec B603
        ["/bin/bash", str(root / "scripts/detect-pr.sh"), "--pr", "73"],
        cwd=caller_worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert detected.returncode == 0, detected.stderr
    assert detected.stdout.strip() == "PR_NUMBER=73"


def test_bootstrap_itself_rejects_missing_mycelium(tmp_path: Path, caller_worktree: Path) -> None:
    result = subprocess.run(  # nosec B603
        ["/bin/bash", str(SKILL / "scripts/bootstrap.sh")],
        cwd=caller_worktree,
        env=_environment(tmp_path, mycelium=False),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert "[FAIL]" in result.stderr and "mycelium" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("repo_arg", "gh_repo", "target", "confirmation"),
    [
        (None, None, "heyu-ai/local-project", "false"),
        ("heyu-ai/yibi-tts-service", None, "heyu-ai/yibi-tts-service", "true"),
        (None, "heyu-ai/yibi-tts-service", "heyu-ai/yibi-tts-service", "true"),
        ("heyu-ai/yibi-tts-service", "heyu-ai/wrong", "heyu-ai/yibi-tts-service", "true"),
    ],
)
def test_bootstrap_pr_identity_does_not_relabel_session_workdir(
    tmp_path: Path,
    caller_worktree: Path,
    repo_arg: str | None,
    gh_repo: str | None,
    target: str,
    confirmation: str,
) -> None:
    """RETRO-ST-001: PR repo 決定 project；跨 repo 時保留 transcript cwd 並要求確認。"""
    env = _environment(tmp_path)
    if gh_repo:
        env["GH_REPO"] = gh_repo
    gh = tmp_path / "bin/gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['repo', 'view']:\n"
        "    print(os.environ.get('GH_REPO') or 'heyu-ai/local-project')\n"
        "elif args[:2] == ['pr', 'view']:\n"
        "    repo = (args[args.index('--repo') + 1] if '--repo' in args "
        "else os.environ.get('GH_REPO') or 'heyu-ai/local-project')\n"
        "    print(f'https://github.com/{repo}/pull/{args[2]}')\n"
        "else:\n"
        "    sys.exit(99)\n",
        encoding="utf-8",
    )
    args = ["/bin/bash", str(SKILL / "scripts/bootstrap.sh"), "--pr", "116"]
    if repo_arg:
        args.extend(["--repo", repo_arg])
    result = subprocess.run(
        args, cwd=caller_worktree, env=env, capture_output=True, text=True, timeout=20, check=False
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert values["ORIG_PROJECT"] == target.split("/")[1]
    assert values["PR_REPO"] == target
    assert values["REAL_WORKDIR"] == str(caller_worktree.resolve())
    assert values["BRANCH"] == "feature"
    assert values["PROJECT_CONFIRMATION_REQUIRED"] == confirmation
    if confirmation == "true":
        assert "[WARN]" in result.stderr
        assert "heyu-ai/local-project" in result.stderr and target in result.stderr


@pytest.mark.parametrize("response", ["exit 7", "echo null", "echo https://github.com/a/b/pull/99"])
def test_bootstrap_pr_lookup_failure_never_publishes_project(
    tmp_path: Path, caller_worktree: Path, response: str
) -> None:
    """RETRO-EG-001: API 失敗、無效 URL 或不同 PR 不得退回 cwd 專案。"""
    env = _environment(tmp_path)
    (tmp_path / "bin/gh").write_text(f"#!/bin/sh\n{response}\n", encoding="utf-8")
    result = subprocess.run(
        ["/bin/bash", str(SKILL / "scripts/bootstrap.sh"), "--pr", "116"],
        cwd=caller_worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "[FAIL]" in result.stderr
