"""pr-control-log 與 pr-cycle-fast 的 Step 0 必須以載入的 skill 目錄定位，不用命令替換。

背景：舊範本以 `PR_FLOW_CACHED=$(python3 -c ...)` 讀 installed_plugins.json，會被下游 repo 的
PreToolUse hook 以「禁止命令替換」擋下，skill 一開始就跑不起來；pr-retrospective 已於 #569
改用 `${CLAUDE_SKILL_DIR}`，本檔把同一做法套到其餘兩個同形範本並鎖住。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_LOG = REPO_ROOT / "plugins/growth/skills/pr-control-log"
CYCLE_FAST = REPO_ROOT / "plugins/dev-cycle/skills/pr-cycle-fast"

_FENCE = re.compile(r"^```bash\s*\n(.*?)\n```", re.MULTILINE | re.DOTALL)
# AC-1：Step 0 不得有任何命令替換（`$(`、反引號），也不得探測 installed_plugins.json。
_OLD_TEMPLATE_SIGNS = ("$(", "`", "installed_plugins.json")

# 偵測器的正向對照輸入。第一筆是 #571 之前 pr-control-log Step 0 的精簡形式（只保留兩個特徵，
# 不是原文）；其餘是 AC-1 要求也必須擋下的其他命令替換寫法。
_KNOWN_BAD = (
    'PR_FLOW_CACHED=$(python3 -c "import json,pathlib; '
    "pathlib.Path.home()/'.claude'/'plugins'/'installed_plugins.json'\")\n",
    'R=$(dirname "$0")\n',
    "R=$(pwd)\n",
    "R=`pwd`\n",
)


def _step0_fences(skill: Path) -> list[str]:
    """Step 0 區段內的 bash fence（到 Step 1 為止）。"""
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("### Step 0")
    end = text.index("### Step 1", start)
    return _FENCE.findall(text[start:end])


def _uses_old_template(block: str) -> bool:
    return any(sign in block for sign in _OLD_TEMPLATE_SIGNS)


@pytest.mark.parametrize("bad", _KNOWN_BAD)
def test_detector_flags_known_bad_template(bad: str) -> None:
    """對照組：偵測器必須能抓到舊範本與其他命令替換，否則下面的 PASS 沒有資訊量。"""
    assert _uses_old_template(bad)


@pytest.mark.parametrize("skill", [CONTROL_LOG, CYCLE_FAST], ids=lambda p: p.name)
def test_step0_has_no_command_substitution_or_registry_probe(skill: Path) -> None:
    blocks = _step0_fences(skill)
    assert blocks, f"{skill.name}: Step 0 找不到任何 bash fence——區段錨點可能已失效"
    for block in blocks:
        assert not _uses_old_template(block), f"{skill.name} Step 0 仍含舊範本：\n{block}"
    assert any("${CLAUDE_SKILL_DIR}/scripts/" in block for block in blocks), (
        f"{skill.name} Step 0 沒有任何 fence 以載入的 skill 目錄呼叫 scripts"
    )
    for block in blocks:
        # 裸 $CLAUDE_SKILL_DIR 不會被載入期替換，shell 會展開成空字串。
        assert not re.search(r"\$CLAUDE_SKILL_DIR\b", block), f"{skill.name} 含裸變數：\n{block}"


@pytest.mark.parametrize("skill", [CONTROL_LOG, CYCLE_FAST], ids=lambda p: p.name)
def test_every_step0_script_reference_resolves_to_a_file(skill: Path) -> None:
    """Step 0 每個以載入目錄引用的 script（含 detect-pr.sh）都必須是實際存在的檔案。"""
    refs = [
        name
        for block in _step0_fences(skill)
        for name in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/scripts/([\w.-]+)", block)
    ]
    assert refs, f"{skill.name} Step 0 沒有 script 引用"
    for name in refs:
        assert (skill / "scripts" / name).is_file(), f"{skill.name} Step 0 引用不存在的 {name}"


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
def caller_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "caller repository"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feature")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
    )
    return repo


def _env(tmp_path: Path, *, mycelium: bool = True) -> dict[str, str]:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # 只提供存在性；bootstrap 不應實際執行這些工具。
    for name in ("gh", *(("mycelium",) if mycelium else ())):
        stub = binaries / name
        stub.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        stub.chmod(0o755)
    for name in ("bash", "git", "basename", "dirname", "grep"):
        executable = shutil.which(name)
        assert executable is not None
        (binaries / name).symlink_to(executable)
    env = {**os.environ, "HOME": str(tmp_path / "empty home"), "PATH": str(binaries)}
    for name in ("PR_FLOW_CACHED", "CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT"):
        env.pop(name, None)
    return env


def _command(skill: Path, script: str, root: Path) -> str:
    block = next(b for b in _step0_fences(skill) if f"/scripts/{script}" in b)
    # 模擬載入期替換；shell 裡刻意不提供這個變數。
    return block.replace("${CLAUDE_SKILL_DIR}", str(root))


def test_control_log_bootstraps_from_loaded_directory(tmp_path: Path, caller_repo: Path) -> None:
    root = tmp_path / "active plugin cache/skills/pr-control-log"
    shutil.copytree(CONTROL_LOG, root)
    env = _env(tmp_path)
    boot = subprocess.run(  # nosec B603
        ["/bin/bash", "-c", _command(CONTROL_LOG, "bootstrap.sh", root)],
        cwd=caller_repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert boot.returncode == 0, boot.stderr
    values = dict(line.split("=", 1) for line in boot.stdout.splitlines())
    assert values["ORIG_PROJECT"] == "caller repository"
    assert values["BRANCH"] == "feature"


def test_control_log_detect_pr_runs_from_loaded_directory(
    tmp_path: Path, caller_repo: Path
) -> None:
    """AC-2 的另一半：detect-pr.sh 以載入目錄呼叫時，在獨立 shell 回傳 PR_NUMBER。

    載入目錄刻意含空白，確認 SKILL.md 要求的引用方式有效；gh 只是 exit 99 的 stub，
    所以本測試也證明帶 --pr 時不需要呼叫 gh。
    """
    root = tmp_path / "active plugin cache/skills/pr-control-log"
    shutil.copytree(CONTROL_LOG, root)
    result = subprocess.run(  # nosec B603
        ["/bin/bash", "-c", _command(CONTROL_LOG, "detect-pr.sh", root) + " --pr 73"],
        cwd=caller_repo,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PR_NUMBER=73"


def test_control_log_bootstrap_rejects_missing_mycelium(tmp_path: Path, caller_repo: Path) -> None:
    result = subprocess.run(  # nosec B603
        ["/bin/bash", str(CONTROL_LOG / "scripts/bootstrap.sh")],
        cwd=caller_repo,
        env=_env(tmp_path, mycelium=False),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert "[FAIL]" in result.stderr and "mycelium" in result.stderr
    assert result.stdout == ""


def test_cycle_fast_step0_command_points_at_existing_script() -> None:
    """代入載入目錄後，命令指向的 script 必須真的存在。"""
    command = _command(CYCLE_FAST, "check-cli-capability.sh", CYCLE_FAST)
    match = re.search(r'bash "([^"]+check-cli-capability\.sh)"', command)
    assert match, command
    assert Path(match.group(1)).is_file()
