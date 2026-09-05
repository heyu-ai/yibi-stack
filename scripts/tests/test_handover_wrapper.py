"""scripts/handover wrapper 的 DB CLI forwarding 行為測試。"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "handover"


def _make_env(tmp_path: Path) -> dict[str, str]:
    fake_home = tmp_path / "home"
    bin_dir = fake_home / ".agents" / "bin"
    bin_dir.mkdir(parents=True)

    skill_repo = tmp_path / "skill repo"
    skill_repo.mkdir()
    resolver = bin_dir / "resolve-skill-repo"
    resolver.write_text(f'#!/usr/bin/env bash\necho "{skill_repo}"\n', encoding="utf-8")
    resolver.chmod(0o755)

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    uv_shim.chmod(0o755)
    return {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
    }


def test_how_dt_001_read_forwards_to_db_backed_cli(tmp_path: Path) -> None:
    """HOW-DT-001：read 原樣抵達 mycelium handover CLI，不注入 project。"""
    result = subprocess.run(  # nosec B603
        ["bash", str(WRAPPER), "read", "--last", "25", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "read",
        "--last",
        "25",
        "--json",
    ]


def test_how_dt_002_write_preserves_caller_workdir(tmp_path: Path) -> None:
    """HOW-DT-002：write 注入 caller cwd，避免 uv --directory 把 project 偵測改掉。"""
    caller = tmp_path / "caller repo" / "nested"
    caller.mkdir(parents=True)

    result = subprocess.run(  # nosec B603
        ["bash", str(WRAPPER), "write", "--topic", "t", "--summary", "s"],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    assert args[-2:] == ["--workdir", str(caller)]


def test_how_st_001_install_contract_makes_wrapper_reachable(tmp_path: Path) -> None:
    """HOW-ST-001：隔離 HOME 安裝後可從 ~/.agents/bin/handover 執行 DB CLI。"""
    env = _make_env(tmp_path)
    (Path(env["HOME"]) / ".agents" / "bin" / "resolve-skill-repo").unlink()
    installed = subprocess.run(  # nosec B603
        ["make", "install-agent-wrappers"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    assert installed.returncode == 0, installed.stderr

    wrapper = Path(env["HOME"]) / ".agents" / "bin" / "handover"
    result = subprocess.run(  # nosec B603
        [str(wrapper), "read", "--last", "1", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-5:] == ["handover", "read", "--last", "1", "--json"]
