"""執行出貨的 bootstrap 命令，驗證載入目錄、獨立 shell 與必要 CLI。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
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
    for name in ("RETRO_ROOT", "PR_FLOW_CACHED", "CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT"):
        env.pop(name, None)
    return env


def _command(script_name: str, root: Path) -> str:
    blocks = re.findall(
        r"^```bash\s*\n(.*?)\n```",
        (SKILL / "SKILL.md").read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    command = next(
        block for block in blocks if f"/scripts/{script_name}" in block and "--pr" not in block
    )
    # 模擬已文件化的 skill 載入期替換；shell 裡刻意不提供這個變數。
    return command.replace("${CLAUDE_SKILL_DIR}", str(root))


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
        ["/bin/bash", "-c", _command("bootstrap.sh", root)],
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
        ["/bin/bash", "-c", _command("detect-pr.sh", root) + " --pr 73"],
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
