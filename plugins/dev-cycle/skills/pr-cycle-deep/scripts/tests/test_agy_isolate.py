"""Consumer-visible isolation tests. No real/paid agy calls are made."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest
from agy_isolate import cleanup_workspace, sandbox_prefix, snapshot_head
from test_agy_scripts import require_isolation

SCRIPTS = Path(__file__).resolve().parent.parent
HELPER = SCRIPTS / "agy_isolate.py"
STAGES = {
    "r1": (SCRIPTS / "agy-r1-stage1.sh", "gemini-r1-raw.md", "gemini-r1.stage1.agy.log"),
    "r2": (SCRIPTS / "agy-r2.sh", "gemini-r2.md", "gemini-r2.agy.log"),
}


STAND_IN = r"""
import errno
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

args = sys.argv[1:]
def flag(name):
    return args[args.index(name) + 1]

workspace = pathlib.Path(flag('--add-dir'))
assert workspace.is_absolute() and workspace == pathlib.Path.cwd()
assert flag('--model') == 'Gemini 3.8 Flash (High)'
assert '--dangerously-skip-permissions' in args and '--sandbox' not in args
assert 'PROMPT MARKER' in flag('-p') and not flag('-p').startswith('@')
assert workspace != pathlib.Path(os.environ['SOURCE'])
assert not (workspace / '.git').exists()
assert not (workspace / 'secret.txt').exists()
assert (workspace / 'seed.txt').read_text() == 'committed seed\n'
assert (workspace / 'export-ignored.txt').read_text() == 'tracked despite attributes\n'
assert (workspace / 'space 雪.txt').read_text() == 'unicode\n'
assert (workspace / 'escape').is_symlink()
assert (workspace / 'escape').read_text() == 'committed seed\n'
assert (workspace / 'seed.txt').stat().st_nlink == 1
assert not (workspace / 'seed.txt').samefile(pathlib.Path(os.environ['SOURCE']) / 'seed.txt')
assert subprocess.check_output(['./explore.sh'], text=True).strip() == 'exploration works'
# Auth is usable without copying old conversations or bulk cache.
home = pathlib.Path.home()
assert (home / '.gemini/oauth_creds.json').read_text() == 'fake-auth'
assert (home / '.gemini/antigravity-cli/cache/onboarding.json').is_file()
assert not (home / '.gemini/antigravity-cli/conversations/old.db').exists()
assert not (home / '.gemini/antigravity-cli/cache/old-cache.bin').exists()
(home / '.gemini/oauth_creds.json').write_text('refreshed-private-auth')

blocked = []
targets = [
    pathlib.Path('seed.txt'), pathlib.Path('new-file.txt'), pathlib.Path('escape'),
    pathlib.Path(os.environ['SOURCE']) / 'seed.txt',
    pathlib.Path(os.environ['SOURCE']) / '.git',
    pathlib.Path(os.environ['COMMON']) / 'config',
    pathlib.Path(os.environ['COMMON']) / 'index',
    pathlib.Path(os.environ['WORKTREE_INDEX']),
]
for target in targets:
    try:
        target.write_text('CORRUPTED')
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES, errno.EROFS), exc
        blocked.append(str(target))
    else:
        raise AssertionError('write escaped OS sandbox: ' + str(target))
# A writable scratch alias must not turn a protected inode into a writable file.
source = pathlib.Path(os.environ['SOURCE']) / 'seed.txt'
alias = pathlib.Path(os.environ['TMPDIR']) / 'hardlink-escape'
try:
    os.link(source, alias)
    alias.write_text('CORRUPTED')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES, errno.EROFS, errno.EXDEV), exc
else:
    raise AssertionError('hardlink escaped OS sandbox')
assert source.read_text() == 'committed seed\n'
# A command child inherits the same protection, rather than just an agy policy.
child = subprocess.run([sys.executable, '-c',
    "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('CORRUPTED')",
    str(pathlib.Path(os.environ['SOURCE']) / 'seed.txt')], capture_output=True)
assert child.returncode != 0
report = {'workspace': str(workspace), 'scratch': os.environ['TMPDIR'], 'blocked': blocked}
pathlib.Path(flag('--log-file')).write_text(json.dumps(report))
mode = os.environ.get('MODE', 'success')
port = os.environ.get('READY_PORT')
if port:
    connection = socket.create_connection(('127.0.0.1', int(port)))
    # Descendant deliberately outlives the reviewer. On successful return as well
    # as signals/timeouts the helper must kill it before deleting its workspace.
    subprocess.Popen([sys.executable, '-c',
        "import socket,sys,time; s=socket.socket(fileno=int(sys.argv[1])); "
        "time.sleep(float(sys.argv[2]) + 2); s.sendall(b'SURVIVED'); s.close()",
        str(connection.fileno()), flag('--print-timeout').rstrip('s')],
        pass_fds=(connection.fileno(),), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    connection.sendall((json.dumps(report) + '\n').encode())
    connection.close()
print('## Verdict\nLGTM\nReviewed `' + str(workspace / 'seed.txt') + '`.', flush=True)
if mode == 'brain':
    brain = home / '.gemini/antigravity-cli/brain/abcdef12/review.md'
    brain.parent.mkdir(parents=True)
    brain.write_text('## Verdict\nLGTM\nReviewed `' + str(workspace / 'seed.txt') + '`.\n')
    print('I have written my analysis to ' + str(brain), flush=True)
if mode in ('wait', 'timeout'):
    time.sleep(60)
if mode == 'marker':
    print('[agy] print timeout after 20s with turn in progress', file=sys.stderr)
if mode == 'failure':
    sys.exit(7)
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(  # nosec B603 B607
        ["git", "-C", str(repo), *args],
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    ).strip()


@pytest.fixture
def isolated_repo(tmp_path: Path) -> dict:
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q")
    git(main, "config", "user.email", "test@example.invalid")
    git(main, "config", "user.name", "test")
    linked = tmp_path / "linked"
    (main / "seed.txt").write_text("committed seed\n")
    (main / "export-ignored.txt").write_text("tracked despite attributes\n")
    (main / ".gitattributes").write_text("export-ignored.txt export-ignore\n")
    (main / "space 雪.txt").write_text("unicode\n")
    (main / "escape").symlink_to(linked / "seed.txt")
    (main / "explore.sh").write_text("#!/bin/sh\nprintf 'exploration works\\n'\n")
    (main / "explore.sh").chmod(0o755)
    git(main, "add", ".")
    git(main, "commit", "-qm", "seed")
    git(main, "worktree", "add", "-qb", "review", str(linked))
    (linked / "secret.txt").write_text("untracked secret")
    review = linked / ".pr-review"
    review.mkdir()
    for name in ("prompt-r1.md", "prompt-r2.md"):
        (review / name).write_text("PROMPT MARKER\n")
    (review / "changed-files.txt").write_text("seed.txt\n")
    (review / "diff.patch").write_text("diff --git a/seed.txt b/seed.txt\n")
    (review / "r1-aggregate.md").write_text("## Other reviews\nseed.txt\n")
    home = tmp_path / "home"
    state = home / ".gemini/antigravity-cli"
    (state / "cache").mkdir(parents=True)
    (state / "cache/onboarding.json").write_text('{"onboardingComplete": true}')
    (state / "cache/old-cache.bin").write_text("do not copy")
    (state / "conversations").mkdir()
    (state / "conversations/old.db").write_text("do not copy")
    (home / ".gemini/oauth_creds.json").write_text("fake-auth")
    (state / "scratch").mkdir()
    shared_input = state / "scratch/gemini-other-session-input.md"
    shared_input.write_text("another review owns this input\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "agy"
    stand_in.write_text(f"#!{sys.executable}\n" + STAND_IN)
    stand_in.chmod(0o755)
    common = main / ".git"
    index = Path(git(linked, "rev-parse", "--absolute-git-dir")) / "index"
    seed_file = linked / "seed.txt"
    os.utime(seed_file, (seed_file.stat().st_atime + 30, seed_file.stat().st_mtime + 30))
    protected = [linked / "seed.txt", linked / ".git", common / "config", common / "index", index]
    protected.append(shared_input)
    original = {path: (path.read_bytes(), path.stat().st_mode) for path in protected}
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "SOURCE": str(linked),
        "COMMON": str(common),
        "WORKTREE_INDEX": str(index),
        "AGY_PRINT_TIMEOUT_SECS": "20",
        "TMPDIR": str(tmp_path),
    }
    return {
        "repo": linked,
        "review": review,
        "env": env,
        "original": original,
        "tmp": tmp_path,
        "home": home,
        "bin": bin_dir,
    }


def run_stage(fixture: dict, stage: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607
        ["bash", str(STAGES[stage][0])],
        cwd=fixture["repo"],
        env={**fixture["env"], **extra},
        capture_output=True,
        text=True,
        timeout=40,
    )


def assert_preserved(fixture: dict) -> None:
    for path, (data, mode) in fixture["original"].items():
        assert path.read_bytes() == data, path
        assert path.stat().st_mode == mode, path
    assert (fixture["home"] / ".gemini/oauth_creds.json").read_text() == "fake-auth"
    assert not list(fixture["tmp"].glob("agy-review-*"))


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("mode", ["success", "failure", "marker", "brain"])
def test_real_os_contains_review_and_keeps_artifacts(
    isolated_repo: dict, stage: str, mode: str
) -> None:
    require_isolation()
    result = run_stage(isolated_repo, stage, MODE=mode)
    assert result.returncode == {"success": 0, "failure": 7, "marker": 124, "brain": 0}[mode], (
        result.stderr
    )
    _, raw_name, log_name = STAGES[stage]
    report = json.loads((isolated_repo["review"] / log_name).read_text())
    assert len(report["blocked"]) == 8
    assert not Path(report["workspace"]).exists()
    assert not Path(report["scratch"]).exists()
    raw = isolated_repo["review"] / raw_name
    if mode == "marker":
        assert not raw.exists()
        raw = raw.with_name(raw.stem + ".timeout-partial.md")
        assert raw.stat().st_mode & 0o777 == 0o600
    text = raw.read_text()
    assert "seed.txt" in text
    assert report["workspace"] not in text
    assert_preserved(isolated_repo)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("ending", ["success", "failure", "timeout", "sigterm", "sigint"])
def test_descendants_signals_and_timeout_cleanup(
    isolated_repo: dict, stage: str, ending: str
) -> None:
    require_isolation()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(20)
        env = {
            **isolated_repo["env"],
            "READY_PORT": str(listener.getsockname()[1]),
            "MODE": "wait" if ending.startswith("sig") else ending,
        }
        if ending == "timeout":
            env["AGY_PRINT_TIMEOUT_SECS"] = "5"
        process = subprocess.Popen(  # nosec B603 B607
            ["bash", str(STAGES[stage][0])],
            cwd=isolated_repo["repo"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(10)
                with connection.makefile("rb") as stream:
                    report = json.loads(stream.readline())
                    if ending.startswith("sig"):
                        process.send_signal(
                            signal.SIGTERM if ending == "sigterm" else signal.SIGINT
                        )
                    _, stderr = process.communicate(timeout=20)
                    assert (
                        process.returncode
                        == {
                            "success": 0,
                            "failure": 7,
                            "timeout": 124,
                            "sigterm": 143,
                            "sigint": 130,
                        }[ending]
                    ), stderr
                    assert stream.read() == b"", "a descendant survived reviewer cleanup"
            assert not Path(report["workspace"]).exists()
            assert not Path(report["scratch"]).exists()
            _, raw_name, log_name = STAGES[stage]
            assert json.loads((isolated_repo["review"] / log_name).read_text())["blocked"]
            if ending == "timeout":
                raw = isolated_repo["review"] / raw_name
                assert not raw.exists()
                partial = raw.with_name(raw.stem + ".timeout-partial.md")
                assert "seed.txt" in partial.read_text()
                assert partial.stat().st_mode & 0o777 == 0o600
            assert_preserved(isolated_repo)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=20)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("dirty", ["unstaged", "staged", "unmerged"])
def test_dirty_or_unmerged_tree_fails_before_reviewer(
    isolated_repo: dict, stage: str, dirty: str
) -> None:
    repo = isolated_repo["repo"]
    if dirty == "unmerged":
        oid = git(repo, "rev-parse", "HEAD:seed.txt")
        subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo), "update-index", "--index-info"],
            input=f"0 {'0' * 40}\tseed.txt\n100644 {oid} 1\tseed.txt\n100644 {oid} 2\tseed.txt\n",
            text=True,
            check=True,
        )
    else:
        (repo / "seed.txt").write_text("pending changes\n")
        if dirty == "staged":
            git(repo, "add", "seed.txt")
    result = run_stage(isolated_repo, stage)
    assert result.returncode != 0
    stderr_name = "gemini-r1.stage1.log" if stage == "r1" else "gemini-r2.log"
    assert "dirty or unmerged" in (isolated_repo["review"] / stderr_name).read_text()
    assert not (isolated_repo["review"] / STAGES[stage][2]).exists()
    assert not list(isolated_repo["tmp"].glob("agy-review-*"))


@pytest.mark.parametrize(
    "platform,executable", [("darwin", "sandbox-exec"), ("linux", "bwrap"), ("other", None)]
)
def test_missing_backend_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, executable: str | None
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match=executable or "requires macOS"):
        sandbox_prefix(tmp_path, tmp_path / "scratch")


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("exit_mode", ["exit77", "passthrough"])
def test_unusable_backend_never_starts_agy(isolated_repo: dict, stage: str, exit_mode: str) -> None:
    if sys.platform not in ("darwin", "linux"):
        pytest.skip("no supported backend on this OS")
    backend = isolated_repo["bin"] / ("sandbox-exec" if sys.platform == "darwin" else "bwrap")
    if exit_mode == "exit77":
        backend.write_text("#!/bin/sh\necho 'sandbox unavailable' >&2\nexit 77\n")
    else:
        # Passthrough stub that allows protected writes: startup probe must catch it
        if sys.platform == "darwin":
            backend.write_text('#!/bin/sh\nshift 4\nexec "$@"\n')
        else:
            backend.write_text(
                '#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift\nexec "$@"\n'
            )
    backend.chmod(0o755)
    agy = isolated_repo["bin"] / "agy"
    agy.write_text('#!/bin/sh\nprintf CORRUPTED > "$SOURCE/seed.txt"\n')
    agy.chmod(0o755)
    result = run_stage(isolated_repo, stage)
    assert result.returncode != 0
    stderr_name = "gemini-r1.stage1.log" if stage == "r1" else "gemini-r2.log"
    assert "agy was not started" in (isolated_repo["review"] / stderr_name).read_text()
    assert_preserved(isolated_repo)


def test_submodule_gitlink_fails_loudly_before_review(isolated_repo: dict) -> None:
    repo = isolated_repo["repo"]
    oid = git(repo, "rev-parse", "HEAD")
    subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), "update-index", "--add", "--cacheinfo", f"160000,{oid},sub"],
        check=True,
    )
    git(repo, "commit", "-qm", "add gitlink")
    snapshot = isolated_repo["tmp"] / "snapshot"
    snapshot.mkdir()
    # Git-tree validation must run even on hosts without an OS sandbox backend.
    with pytest.raises(ValueError, match="submodules require a separate review"):
        snapshot_head(repo, snapshot, git(repo, "rev-parse", "HEAD"))
    assert not (snapshot / "sub").exists()


@pytest.mark.parametrize("stage", STAGES)
def test_original_tree_comparison_runs_on_failed_reviewer(isolated_repo: dict, stage: str) -> None:
    require_isolation()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(20)
        env = {**isolated_repo["env"], "READY_PORT": str(listener.getsockname()[1]), "MODE": "wait"}
        process = subprocess.Popen(  # nosec B603 B607
            ["bash", str(STAGES[stage][0])],
            cwd=isolated_repo["repo"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(10)
                with connection.makefile("rb") as stream:
                    stream.readline()
                    # A concurrent user edit, not an agy escape, changes PRE/POST.
                    (isolated_repo["repo"] / "seed.txt").write_text("concurrent user edit\n")
                    process.send_signal(signal.SIGTERM)
                    _, stderr = process.communicate(timeout=20)
                    assert process.returncode == 143, stderr
                    assert "[WARN]" in stderr and "seed.txt" in stderr
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=20)


def test_cleanup_never_chmods_symlink_targets_outside_scratch(isolated_repo: dict) -> None:
    require_isolation()
    # Create a protected target with strict permissions (0600)
    target = isolated_repo["tmp"] / "protected_target.txt"
    target.write_text("protected content\n")
    target.chmod(0o600)
    initial_mode = target.stat().st_mode

    # Make stand-in create a 0500 directory inside scratch containing a symlink to target
    stand_in = isolated_repo["bin"] / "agy"
    stand_in.write_text(f"""#!{sys.executable}
import os, pathlib
scratch = pathlib.Path(os.environ['TMPDIR'])
ro_dir = scratch / 'ro_dir'
ro_dir.mkdir()
(ro_dir / 'symlink_to_target').symlink_to('{target}')
ro_dir.chmod(0o000)
print("## Verdict\\nLGTM\\n")
""")
    stand_in.chmod(0o755)

    result = run_stage(isolated_repo, "r1")
    assert result.returncode == 0, result.stderr
    # Target file permissions must NOT have been changed to 0700 by cleanup
    assert target.stat().st_mode == initial_mode
    assert not list(isolated_repo["tmp"].glob("agy-review-*"))


def test_cleanup_restores_owned_directories_without_changing_link_targets(tmp_path: Path) -> None:
    protected = tmp_path / "protected"
    protected.write_text("outside data\n")
    protected.chmod(0o600)
    original_mode = protected.stat().st_mode
    workspace = tmp_path / "workspace"
    locked = workspace / "scratch" / "locked"
    locked.mkdir(parents=True)
    (locked / "cache").write_text("private cache\n")
    (locked / "link").symlink_to(protected)
    locked.chmod(0o000)

    cleanup_workspace(workspace)

    assert not workspace.exists()
    assert protected.read_text() == "outside data\n"
    assert protected.stat().st_mode == original_mode


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.skipif(sys.platform != "darwin", reason="immutable-file regression uses macOS flags")
def test_incomplete_cleanup_fails_loudly_with_leftover_path(
    isolated_repo: dict, stage: str
) -> None:
    require_isolation()
    stand_in = isolated_repo["bin"] / "agy"
    stand_in.write_text(f"""#!{sys.executable}
import os, pathlib, stat
credential = pathlib.Path.home() / '.gemini/oauth_creds.json'
assert credential.read_text() == 'fake-auth'
os.chflags(credential, stat.UF_IMMUTABLE)
print('## Verdict')
print('LGTM')
print('Reviewed seed.txt', flush=True)
""")
    stand_in.chmod(0o755)
    try:
        result = run_stage(isolated_repo, stage)
        assert result.returncode == 1
        stderr_name = "gemini-r1.stage1.log" if stage == "r1" else "gemini-r2.log"
        diagnostic = (isolated_repo["review"] / stderr_name).read_text()
        leftovers = list(isolated_repo["tmp"].glob("agy-review-*"))
        assert len(leftovers) == 1
        assert "[FAIL] 無法清除隔離工作目錄" in diagnostic
        assert str(leftovers[0]) in diagnostic
        assert "Traceback" not in diagnostic
        assert (leftovers[0] / "scratch/home/.gemini/oauth_creds.json").read_text() == "fake-auth"
    finally:
        for leftover in isolated_repo["tmp"].glob("agy-review-*"):
            credential = leftover / "scratch/home/.gemini/oauth_creds.json"
            if credential.exists():
                os.chflags(credential, 0, follow_symlinks=False)
            cleanup_workspace(leftover)
    assert_preserved(isolated_repo)
