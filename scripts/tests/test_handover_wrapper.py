"""scripts/handover wrapper 的 DB CLI forwarding 行為測試。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _clean_git_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _GIT_ENV_KEYS}


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
    uv_shim.write_text(
        "#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    uv_shim.chmod(0o755)
    return {
        **_clean_git_env(),
        "HOME": str(fake_home),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _argv(result: subprocess.CompletedProcess[str]) -> list[str]:
    return list(json.loads(result.stdout))


def _make_install_fixture(tmp_path: Path) -> Path:
    """建立非 worktree 的最小 checkout，讓 public make install 只寫隔離 HOME。"""
    root = tmp_path / "main checkout"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "Makefile", root / "Makefile")
    scripts = root / "scripts"
    scripts.mkdir()
    for name in (
        "assert_not_worktree.sh",
        "safe_symlink.sh",
        "register_skill_repo.py",
        "lessons",
        "handover",
        "resolve-skill-repo",
    ):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    for name in ("tasks", "skills", "commands"):
        (root / name).symlink_to(REPO_ROOT / name, target_is_directory=True)
    subprocess.run(  # nosec B603
        ["git", "init", "-q", str(root)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=_clean_git_env(),
    )
    return root


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
    assert _argv(result) == [
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


def test_how_dt_002_write_preserves_full_argv_and_caller_workdir(tmp_path: Path) -> None:
    """HOW-DT-002：spaced payload 原樣轉發，並只在尾端注入 caller cwd。"""
    caller = tmp_path / "caller repo" / "nested"
    caller.mkdir(parents=True)
    result = subprocess.run(  # nosec B603
        [
            "bash",
            str(WRAPPER),
            "write",
            "--topic",
            "topic with spaces",
            "--summary",
            "summary with spaces",
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert _argv(result) == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        "--topic",
        "topic with spaces",
        "--summary",
        "summary with spaces",
        "--workdir",
        str(caller),
    ]


@pytest.mark.parametrize(
    "workdir_args",
    [
        ["--workdir", "/explicit path/with spaces"],
        ["--workdir=/explicit path/with spaces"],
    ],
    ids=["separate-token", "equals"],
)
def test_how_dt_003_explicit_workdir_survives_once(tmp_path: Path, workdir_args: list[str]) -> None:
    """HOW-DT-003：兩種 explicit workdir 形式皆原樣保留，且不附加 caller cwd。"""
    caller = tmp_path / "caller repo"
    caller.mkdir()
    result = subprocess.run(  # nosec B603
        [
            "bash",
            str(WRAPPER),
            "write",
            "--topic",
            "topic with spaces",
            "--summary",
            "summary with spaces",
            *workdir_args,
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    argv = _argv(result)
    assert argv == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        "--topic",
        "topic with spaces",
        "--summary",
        "summary with spaces",
        *workdir_args,
    ]
    assert sum(arg == "--workdir" or arg.startswith("--workdir=") for arg in argv) == 1
    assert str(caller) not in argv


@pytest.mark.parametrize("form", ["separate-token", "equals"])
def test_how_dt_004_relative_workdir_resolves_from_caller(tmp_path: Path, form: str) -> None:
    """HOW-DT-004：relative workdir 在 uv 改 cwd 前依 caller 實體路徑解析。"""
    caller = tmp_path / "caller repo"
    target = caller / "relative dir"
    target.mkdir(parents=True)
    relative = "relative dir"
    workdir_args = (
        ["--workdir", relative] if form == "separate-token" else [f"--workdir={relative}"]
    )
    expected_workdir = str(target.resolve())
    expected_args = (
        ["--workdir", expected_workdir]
        if form == "separate-token"
        else [f"--workdir={expected_workdir}"]
    )

    result = subprocess.run(  # nosec B603
        [
            "bash",
            str(WRAPPER),
            "write",
            "--topic",
            "topic with spaces",
            "--summary",
            "summary with spaces",
            *workdir_args,
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert _argv(result) == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        "--topic",
        "topic with spaces",
        "--summary",
        "summary with spaces",
        *expected_args,
    ]


_VALUE_OPTIONS = [
    "--session-type",
    "-t",
    "--topic",
    "--summary",
    "--operator",
    "--completed",
    "--decisions",
    "--blocked",
    "--next",
    "--lessons",
    "--approaches",
    "--tags",
    "--files",
    "--test-status",
    "--tokens",
    "--device",
    "--agent",
    "--account",
    "--branch",
    "--project",
]


@pytest.mark.parametrize("option", _VALUE_OPTIONS)
def test_how_dt_005_payload_token_named_workdir_is_not_an_option(
    tmp_path: Path, option: str
) -> None:
    """HOW-DT-005：option value 即使等於 --workdir，也仍須追加真正的 implicit option。"""
    caller = tmp_path / "caller repo"
    caller.mkdir()
    result = subprocess.run(  # nosec B603
        [
            "bash",
            str(WRAPPER),
            "write",
            option,
            "--workdir",
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert _argv(result) == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        option,
        "--workdir",
        "--workdir",
        str(caller),
    ]


def test_how_dt_006_implicit_workdir_precedes_end_of_options(tmp_path: Path) -> None:
    """HOW-DT-006：trailing -- 保留在尾端，implicit workdir 必須插在 delimiter 前。"""
    caller = tmp_path / "caller repo"
    caller.mkdir()
    result = subprocess.run(  # nosec B603
        [
            "bash",
            str(WRAPPER),
            "write",
            "--topic",
            "topic",
            "--summary",
            "summary",
            "--",
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert _argv(result) == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        "--topic",
        "topic",
        "--summary",
        "summary",
        "--workdir",
        str(caller),
        "--",
    ]


@pytest.mark.parametrize(
    ("file_args", "expected_args"),
    [
        (
            ["--from-file", "notes dir/h.json"],
            ["--from-file", "{caller}/notes dir/h.json", "--workdir", "{caller}"],
        ),
        (
            ["--from-file=notes dir/h.json"],
            ["--from-file={caller}/notes dir/h.json", "--workdir", "{caller}"],
        ),
        (
            ["--from-file", "/abs path/h.json"],
            ["--from-file", "/abs path/h.json", "--workdir", "{caller}"],
        ),
        (
            ["--from-file=/abs path/h.json"],
            ["--from-file=/abs path/h.json", "--workdir", "{caller}"],
        ),
        # 缺值時不補 --workdir，否則 click 會把 --workdir 當成 --from-file 的值吞掉
        (["--from-file"], ["--from-file"]),
    ],
    ids=[
        "relative-separate",
        "relative-equals",
        "absolute-separate",
        "absolute-equals",
        "missing-value",
    ],
)
def test_how_dt_007_from_file_resolves_from_caller(
    tmp_path: Path, file_args: list[str], expected_args: list[str]
) -> None:
    """HOW-DT-007：relative --from-file 依 caller 實體路徑解析、絕對路徑原樣保留，缺值時不補 --workdir。"""
    caller = tmp_path / "caller repo"
    caller.mkdir()
    caller_real = str(caller.resolve())
    result = subprocess.run(  # nosec B603
        ["bash", str(WRAPPER), "write", *file_args],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_make_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert _argv(result) == [
        "run",
        "--directory",
        str(tmp_path / "skill repo"),
        "python",
        "-m",
        "tasks.mycelium",
        "handover",
        "write",
        *[arg.format(caller=caller_real) for arg in expected_args],
    ]


def test_how_st_001_public_install_makes_all_wrappers_reachable(tmp_path: Path) -> None:
    """HOW-ST-001：隔離 HOME 的 public make install 可執行三支 wrapper 的 dispatch。"""
    fixture = _make_install_fixture(tmp_path)
    env = _make_env(tmp_path)
    (Path(env["HOME"]) / ".agents" / "bin" / "resolve-skill-repo").unlink()

    installed = subprocess.run(  # nosec B603
        ["make", "install"],
        cwd=fixture,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert installed.returncode == 0, installed.stderr

    bin_dir = Path(env["HOME"]) / ".agents" / "bin"
    resolved = subprocess.run(  # nosec B603
        [str(bin_dir / "resolve-skill-repo")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    handover = subprocess.run(  # nosec B603
        [str(bin_dir / "handover"), "read", "--last", "1", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    lessons = subprocess.run(  # nosec B603
        [str(bin_dir / "lessons"), "show", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )

    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout.strip() == str(fixture)
    assert handover.returncode == 0, handover.stderr
    assert _argv(handover)[-5:] == ["handover", "read", "--last", "1", "--json"]
    assert lessons.returncode == 0, lessons.stderr
    assert _argv(lessons)[-3:] == ["lessons", "show", "--json"]


def test_how_st_002_installed_wrapper_executes_real_db_cli(tmp_path: Path) -> None:
    """HOW-ST-002：隔離 HOME 中以 uv-protocol shim 執行真 mycelium CLI 與 SQLite。"""
    home = tmp_path / "runtime-home"
    bin_dir = home / ".agents" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "handover").symlink_to(WRAPPER)
    resolver = bin_dir / "resolve-skill-repo"
    resolver.write_text(f"#!/usr/bin/env bash\necho {str(REPO_ROOT)!r}\n", encoding="utf-8")
    resolver.chmod(0o755)

    shim_dir = tmp_path / "runtime-shim"
    shim_dir.mkdir()
    uv_shim = shim_dir / "uv"
    uv_shim.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] != ['run', '--directory']:\n"
        "    raise SystemExit(64)\n"
        "os.chdir(args[2])\n"
        "os.execv(sys.executable, [sys.executable, *args[4:]])\n",
        encoding="utf-8",
    )
    uv_shim.chmod(0o755)

    caller = tmp_path / "runtime-caller"
    caller.mkdir()
    subprocess.run(  # nosec B603
        ["git", "init", "-q", str(caller)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=_clean_git_env(),
    )
    subprocess.run(  # nosec B603
        ["git", "-C", str(caller), "symbolic-ref", "HEAD", "refs/heads/runtime-branch"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=_clean_git_env(),
    )
    (caller / "README.md").write_text("runtime\n", encoding="utf-8")
    for args in (
        ["git", "-C", str(caller), "config", "user.email", "test@example.com"],
        ["git", "-C", str(caller), "config", "user.name", "test"],
        ["git", "-C", str(caller), "add", "README.md"],
        ["git", "-C", str(caller), "commit", "-qm", "initial"],
    ):
        subprocess.run(  # nosec B603
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            env=_clean_git_env(),
        )
    hostile = tmp_path / "hostile-repo"
    hostile.mkdir()
    hostile_commands = [
        ["git", "init", "-q", str(hostile)],
        ["git", "-C", str(hostile), "symbolic-ref", "HEAD", "refs/heads/hostile-branch"],
        ["git", "-C", str(hostile), "config", "user.email", "hostile@example.com"],
        ["git", "-C", str(hostile), "config", "user.name", "hostile"],
    ]
    (hostile / "README.md").write_text("hostile\n", encoding="utf-8")
    hostile_commands.extend(
        [
            ["git", "-C", str(hostile), "add", "README.md"],
            ["git", "-C", str(hostile), "commit", "-qm", "hostile"],
        ]
    )
    for args in hostile_commands:
        subprocess.run(  # nosec B603
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            env=_clean_git_env(),
        )
    env = {
        **_clean_git_env(),
        "HOME": str(home),
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "GIT_DIR": str(hostile / ".git"),
        "GIT_WORK_TREE": str(hostile),
        "GIT_COMMON_DIR": str(hostile / ".git"),
        "GIT_INDEX_FILE": str(hostile / ".git" / "index"),
    }
    written = subprocess.run(  # nosec B603
        [
            str(bin_dir / "handover"),
            "write",
            "--session-type",
            "debug",
            "--topic",
            "runtime smoke",
            "--summary",
            "real DB payload",
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    read_back = subprocess.run(  # nosec B603
        [str(bin_dir / "handover"), "read", "--last", "1", "--json"],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    (caller / "handover input.json").write_text(
        json.dumps(
            {
                "session_type": "sdd",
                "topic": "from-file 'quote' \"dq\"",
                "summary": "人跑 alembic upgrade 與 rm -rf build/",
                "next": ["ssh 進去看 log"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    file_written = subprocess.run(  # nosec B603
        [str(bin_dir / "handover"), "write", "--from-file", "handover input.json"],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    file_read_back = subprocess.run(  # nosec B603
        [str(bin_dir / "handover"), "read", "--last", "10", "--json"],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    mirror = home / ".agents" / "handover" / "handover.jsonl"
    mirror.unlink()
    mirror.mkdir()
    failed_write = subprocess.run(  # nosec B603
        [
            str(bin_dir / "handover"),
            "write",
            "--session-type",
            "debug",
            "--topic",
            "mirror failure",
            "--summary",
            "committed despite failure",
        ],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    failed_read_back = subprocess.run(  # nosec B603
        [str(bin_dir / "handover"), "read", "--last", "10", "--json"],
        cwd=caller,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )

    assert written.returncode == 0, written.stderr
    assert read_back.returncode == 0, read_back.stderr
    rows = json.loads(read_back.stdout)
    assert rows[0]["conversation_summary"] == "real DB payload"
    assert rows[0]["project"] == "runtime-caller"
    assert rows[0]["branch"] == "runtime-branch"
    assert file_written.returncode == 0, file_written.stderr
    assert file_read_back.returncode == 0, file_read_back.stderr
    file_rows = [
        row
        for row in json.loads(file_read_back.stdout)
        if row["topic"] == "from-file 'quote' \"dq\""
    ]
    assert len(file_rows) == 1
    file_row = file_rows[0]
    assert file_row["conversation_summary"] == "人跑 alembic upgrade 與 rm -rf build/"
    assert file_row["next_priorities"] == ["ssh 進去看 log"]
    assert file_row["session_type"] == "sdd"
    assert file_row["project"] == "runtime-caller"
    assert file_row["branch"] == "runtime-branch"
    assert failed_write.returncode == 1
    assert failed_write.stdout == ""
    assert failed_write.stderr == "Error: DB 資料已保存，但 JSONL 備份寫入失敗\n"
    assert str(mirror) not in failed_write.stderr
    assert "Errno" not in failed_write.stderr
    assert "Traceback" not in failed_write.stderr
    assert failed_read_back.returncode == 0, failed_read_back.stderr
    failed_rows = json.loads(failed_read_back.stdout)
    assert "committed despite failure" in {row["conversation_summary"] for row in failed_rows}
    assert (home / ".agents" / "handover" / "handover.db").is_file()


def test_hww_sync_001_wrapper_option_list_matches_click_cli() -> None:
    """HWW-SYNC-001：wrapper 的 case 選項必須與 Click CLI 的 value-bearing options 同步。"""
    import re

    import click as _click

    from tasks.mycelium.cli import cli as _cli

    write_cmd = _cli.commands["handover"].commands["write"]
    cli_opts: set[str] = set()
    for param in write_cmd.params:
        if not isinstance(param, _click.Option):
            continue
        for opt in param.opts + param.secondary_opts:
            if opt.startswith("-"):
                cli_opts.add(opt)
    # --workdir / --from-file 的值是路徑，wrapper 各有獨立分支把相對路徑轉成絕對路徑
    cli_opts.discard("--workdir")
    cli_opts.discard("--from-file")

    wrapper_src = WRAPPER.read_text(encoding="utf-8")
    assert re.search(r"^\s*--from-file\)", wrapper_src, re.M), (
        "wrapper 缺少 --from-file 的路徑解析分支"
    )
    long_case = re.search(r"(--session-type[^)]+)\)", wrapper_src)
    assert long_case, "cannot find value-bearing option case pattern in wrapper"
    raw = long_case.group(1)
    wrapper_opts = {o.strip() for o in raw.split("|") if o.strip().startswith("-")}

    missing_in_wrapper = cli_opts - wrapper_opts
    extra_in_wrapper = wrapper_opts - cli_opts
    assert not missing_in_wrapper, f"CLI options not in wrapper: {missing_in_wrapper}"
    assert not extra_in_wrapper, f"wrapper options not in CLI: {extra_in_wrapper}"
