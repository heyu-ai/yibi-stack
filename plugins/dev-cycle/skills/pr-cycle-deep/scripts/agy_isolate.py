#!/usr/bin/env python3
"""Run agy against committed HEAD inside a fail-closed OS write sandbox.

Only the private scratch/home is writable. The snapshot, original checkout, all
linked-worktree metadata, and every other host path stay read-only. Network and
credential reads remain available; no source permissions are changed.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from agy_print_timeout import resolve_budget
from agy_validate import rescue_brain_artifact


class ReviewInterrupted(Exception):
    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(f"interrupted by signal {signum}")


def git(repo: Path, *args: str) -> bytes:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args], capture_output=True, check=True, env=env
    )
    return result.stdout


def clean_head(repo: Path) -> str:
    if git(repo, "status", "--porcelain", "-z", "--untracked-files=no", "--ignore-submodules=none"):
        raise ValueError("tracked tree is dirty or unmerged; commit/stash changes before review")
    return git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()


def snapshot_head(repo: Path, snapshot: Path, head: str) -> None:
    """Read Git objects, not archive attributes, checkout filters or shared indexes."""
    entries = git(repo, "ls-tree", "-rz", "--full-tree", head).split(b"\0")
    regular_blobs = []
    symlinks = []
    with subprocess.Popen(  # nosec B603 B607
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as objects:
        assert objects.stdin is not None and objects.stdout is not None
        for entry in entries:
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            path = Path(os.fsdecode(name))
            if path.is_absolute() or any(part in {"..", ".git"} for part in path.parts):
                raise ValueError(f"unsafe tracked path: {path}")
            if kind != b"blob" or mode not in {b"100644", b"100755", b"120000"}:
                raise ValueError(
                    f"unsupported tracked entry {path} ({mode.decode()}); "
                    "submodules require a separate review"
                )
            objects.stdin.write(oid + b"\n")
            objects.stdin.flush()
            header = objects.stdout.readline().split()
            if len(header) != 3 or header[0] != oid or header[1] != b"blob":
                raise ValueError(f"cannot read committed blob for {path}")
            size = int(header[2])
            data = objects.stdout.read(size)
            if len(data) != size or objects.stdout.read(1) != b"\n":
                raise ValueError(f"incomplete committed blob for {path}")
            if mode == b"120000":
                symlinks.append((path, os.fsdecode(data)))
            else:
                regular_blobs.append((path, mode, data))
        objects.stdin.close()
        if objects.wait() != 0:
            raise ValueError("git cat-file failed while creating the review snapshot")

    def ensure_dir(target_dir: Path) -> None:
        current = snapshot
        for part in target_dir.relative_to(snapshot).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"snapshot directory traverses a symlink: {current}")
            if not current.exists():
                current.mkdir()
            elif not current.is_dir():
                raise ValueError(f"snapshot path collision for directory: {current}")

    for path, mode, data in regular_blobs:
        dest = snapshot / path
        ensure_dir(dest.parent)
        if dest.is_symlink() or dest.exists():
            raise ValueError(f"snapshot path collision: {dest}")
        fd = os.open(
            dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755 if mode == b"100755" else 0o644
        )
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    for path, target in symlinks:
        dest = snapshot / path
        ensure_dir(dest.parent)
        if dest.is_symlink() or dest.exists():
            raise ValueError(f"snapshot path collision for symlink: {dest}")
        dest.symlink_to(target)

    if clean_head(repo) != head:
        raise ValueError("HEAD moved while creating the review snapshot; restart review")


def private_home(scratch: Path) -> Path:
    """Copy only small auth/config files, never old conversations or cache trees."""
    source = Path.home()
    home = scratch / "home"
    home.mkdir()
    # Other credentials (e.g. ADC, Keychain support files) remain readable, not writable.
    for entry in source.iterdir():
        if entry.name != ".gemini":
            (home / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    gemini = home / ".gemini"
    state = gemini / "antigravity-cli"
    (state / "cache").mkdir(parents=True)
    for relative in (
        "oauth_creds.json",
        "google_accounts.json",
        "settings.json",
        "state.json",
        "integrity.key",
        "mcp-oauth-tokens-v2.json",
        "installation_id",
        "antigravity-cli/settings.json",
        "antigravity-cli/jetski_state.pbtxt",
        "antigravity-cli/installation_id",
        "antigravity-cli/cache/onboarding.json",
        "antigravity-cli/cache/default_project_id.txt",
    ):
        original = source / ".gemini" / relative
        if original.is_file():
            shutil.copyfile(original, gemini / relative)
    for relative in (
        "config",
        "skills",
        "extensions",
        "antigravity-cli/bin",
        "antigravity-cli/builtin",
        "antigravity-cli/plugins",
    ):
        original = source / ".gemini" / relative
        if original.exists():
            (gemini / relative).symlink_to(original, target_is_directory=original.is_dir())
    return home


def sandbox_prefix(root: Path, scratch: Path) -> list[str]:
    if sys.platform == "darwin":
        executable = shutil.which("sandbox-exec")
        if executable is None:
            raise ValueError(
                "sandbox-exec is required on macOS; restore /usr/bin/sandbox-exec "
                "or use a supported host"
            )
        profile = root / "review.sb"
        profile.write_text(
            "(version 1)\n(allow default)\n(deny file-write* file-link)\n"
            '(allow file-write* (subpath (param "SCRATCH")) (literal "/dev/null"))\n',
            encoding="utf-8",
        )
        return [executable, "-D", f"SCRATCH={scratch}", "-f", str(profile)]
    if sys.platform == "linux":
        executable = shutil.which("bwrap")
        if executable is None:
            raise ValueError(
                "bwrap is required on Linux; install bubblewrap "
                "and enable unprivileged user namespaces"
            )
        return [
            executable,
            "--die-with-parent",
            "--unshare-pid",
            "--unshare-user",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--bind",
            str(scratch),
            str(scratch),
            "--",
        ]
    raise ValueError(
        "review isolation requires macOS sandbox-exec or Linux bubblewrap; no unrestricted fallback"
    )


def stop_group(process: subprocess.Popen[bytes]) -> None:
    # Even a successful reviewer may have left commands running in its process group.
    # SIGKILL avoids racing scratch deletion against a descendant's SIGTERM handler.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


def run_child(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: int
) -> tuple[int, bytes, bytes]:
    # Do not let a signal arrive between creation of a child and ownership of its PID.
    signals = {signal.SIGTERM, signal.SIGINT}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    process = None
    try:
        process = subprocess.Popen(  # nosec B603
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    finally:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        except ReviewInterrupted:
            if process is not None:
                stop_group(process)
                process.communicate()
            raise
    output = None
    diagnostic = b""
    try:
        output = process.communicate(timeout=timeout)
        code = process.returncode
    except subprocess.TimeoutExpired:
        diagnostic = (
            f"\n[FAIL] print timeout after {timeout}s (OS-isolated reviewer terminated)\n"
        ).encode()
        code = 124
    except ReviewInterrupted as exc:
        diagnostic = f"\n[FAIL] isolated reviewer interrupted by signal {exc.signum}\n".encode()
        code = 128 + exc.signum
    finally:
        # Terminate exactly once, before reaping a timed-out/interrupted leader.
        # A second killpg after reaping can race macOS group teardown and fail
        # with EPERM, losing the review's timeout result and diagnostic artifacts.
        stop_group(process)
        if output is None:
            output = process.communicate()
    stdout, stderr = output
    return code if code >= 0 else 128 - code, stdout, stderr + diagnostic


_PROBE = """
import errno, pathlib, sys
scratch, protected = map(pathlib.Path, sys.argv[1:])
(scratch / 'probe-ok').write_text('ok')
try:
    (protected / 'probe-denied').write_text('unsafe')
except OSError as exc:
    if exc.errno not in (errno.EPERM, errno.EACCES, errno.EROFS):
        raise
else:
    raise RuntimeError('OS backend allowed a protected write')
"""


def check_backend(prefix: list[str], root: Path, scratch: Path, env: dict[str, str]) -> None:
    code, _, stderr = run_child(
        [*prefix, sys.executable, "-c", _PROBE, str(scratch), str(root)],
        cwd=root,
        env=env,
        timeout=15,
    )
    if code in (128 + signal.SIGTERM, 128 + signal.SIGINT):
        raise ReviewInterrupted(code - 128)
    if code:
        raise ValueError(
            "OS write sandbox is unavailable/unusable; agy was not started. "
            "Use a host permitting sandbox-exec or bubblewrap user namespaces. "
            + stderr.decode(errors="replace").strip()
        )


def interrupt(signum: int, _frame: object) -> None:
    # A terminal signal and the shell's forwarded signal can arrive together.
    # Cleanup must not itself be interrupted before the process group is reaped.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise ReviewInterrupted(signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-backend", action="store_true")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--agy-log", type=Path)
    parser.add_argument("--timeout-secs", default=os.environ.get("AGY_PRINT_TIMEOUT_SECS"))
    parser.add_argument("--model", default="Gemini 3.8 Flash (High)")
    parser.add_argument("-p", "--prompt")
    args = parser.parse_args()
    if not args.check_backend and any(
        value is None for value in (args.repo_root, args.agy_log, args.prompt)
    ):
        parser.error("--repo-root, --agy-log and --prompt are required")
    root = None
    old_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        budget = resolve_budget(args.timeout_secs)
        repo = args.repo_root.resolve() if args.repo_root else None
        head = clean_head(repo) if repo else None
        protected = [repo] if repo else []
        if repo:
            common = os.fsdecode(git(repo, "rev-parse", "--git-common-dir")).strip()
            protected.append((repo / common).resolve())
        # Never place writable scratch under the checkout/common-dir, even with a
        # caller-controlled TMPDIR. A source rooted at /tmp must use another host.
        temp_parent = Path(tempfile.gettempdir()).resolve()
        if any(temp_parent == path or path in temp_parent.parents for path in protected):
            temp_parent = Path("/tmp").resolve()  # nosec B108 -- mkdtemp creates a private 0700 directory
        if any(temp_parent == path or path in temp_parent.parents for path in protected):
            raise ValueError(
                "temporary directory is inside protected repository metadata; set TMPDIR outside it"
            )
        root = Path(tempfile.mkdtemp(prefix="agy-review-", dir=temp_parent)).resolve()
        scratch = root / "scratch"
        scratch.mkdir()
        prefix = sandbox_prefix(root, scratch)
        env = dict(os.environ)
        check_backend(prefix, root, scratch, env)
        if args.check_backend:
            return 0
        snapshot = root / "snapshot"
        snapshot.mkdir()
        snapshot_head(repo, snapshot, head)
        home = private_home(scratch)
        env.update(
            HOME=str(home),
            TMPDIR=str(scratch),
            TMP=str(scratch),
            TEMP=str(scratch),
            XDG_CACHE_HOME=str(scratch / "cache"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        executable = shutil.which("agy")
        if executable is None:
            raise ValueError("agy not found on PATH")
        log = scratch / "agy.log"
        code, stdout, stderr = run_child(
            [
                *prefix,
                executable,
                "-p",
                args.prompt,
                "--model",
                args.model,
                "--add-dir",
                str(snapshot),
                "--dangerously-skip-permissions",
                "--print-timeout",
                f"{budget}s",
                "--log-file",
                str(log),
            ],
            cwd=snapshot,
            env=env,
            timeout=budget,
        )
        # Copy only the explicitly requested log. Never follow a reviewer-created
        # symlink out of scratch when recovering artifacts.
        if log.is_symlink():
            raise ValueError("agy log was replaced by a symlink; refusing artifact recovery")
        args.agy_log.write_bytes(log.read_bytes() if log.is_file() else b"")
        text = stdout.decode("utf-8", errors="replace")
        if code == 0:
            text, rescued = rescue_brain_artifact(text, home)
            if rescued:
                stderr += b"[WARN] rescued review from isolated brain artifact\n"
        # Validators consume repo-relative references, not deleted temporary paths.
        text = text.replace(str(snapshot) + "/", "")
        sys.stdout.write(text)
        sys.stdout.flush()
        sys.stderr.buffer.write(stderr)
        sys.stderr.flush()
        return code
    except ReviewInterrupted as exc:
        print(f"[FAIL] isolated reviewer interrupted by signal {exc.signum}", file=sys.stderr)
        return 128 + exc.signum
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[FAIL] reviewer isolation: {exc}", file=sys.stderr)
        return 1
    finally:
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)

        def make_writable_tree(p: Path) -> None:
            if p.is_symlink():
                return
            with contextlib.suppress(OSError):
                os.chmod(p, 0o700)
            if p.is_dir():
                with contextlib.suppress(OSError), os.scandir(p) as it:
                    for entry in it:
                        make_writable_tree(Path(entry.path))

        try:
            if root is not None:
                make_writable_tree(root)
                shutil.rmtree(root, ignore_errors=True)
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
