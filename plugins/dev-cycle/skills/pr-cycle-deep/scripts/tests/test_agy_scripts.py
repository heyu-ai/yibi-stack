"""Behavioral review/timeout tests plus contracts for unchanged extraction callers.

Review-stage containment is exercised against the real OS backend in
test_agy_isolate.py; source/argv-only assertions are not a safety boundary.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
import sys
from functools import lru_cache
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "agy-r1-stage1.sh"
STAGE2 = SCRIPTS_DIR / "agy-r1-stage2.sh"
R2 = SCRIPTS_DIR / "agy-r2.sh"


@lru_cache(maxsize=1)
def require_isolation() -> None:
    """Skip only when the real host facility, independently of our helper, is unusable."""
    if sys.platform == "darwin":
        backend = shutil.which("sandbox-exec")
        command = [backend, "-p", "(version 1)(allow default)", "/usr/bin/true"]
    elif sys.platform == "linux":
        backend = shutil.which("bwrap")
        command = [
            backend,
            "--unshare-user",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--",
            "/bin/true",
        ]
    else:
        pytest.skip("OS has no supported review sandbox")
    if backend is None:
        pytest.skip("OS review sandbox executable is unavailable")
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)  # nosec B603
    if result.returncode:
        pytest.skip(f"OS review sandbox is unusable: {result.stderr}")


# Path segments of this file, indexed the way `Path.parents` does (0 = nearest):
#
#   <repo>  / plugins / dev-cycle / skills / pr-cycle-deep / scripts / tests / this_file.py
#   ^ [6]     ^ [5]     ^ [4]       ^ [3]    ^ [2]           ^ [1]     ^ [0]
#
# `tests` is parents[0], NOT parents[1] — an earlier revision of this comment mislabelled
# the second caret, which invites the reader to recount and land on the wrong index. The
# anchors below turn a miscount into an immediate, self-naming failure.
REPO_ROOT_DIR = Path(__file__).resolve().parents[6]
PLUGINS_DIR = Path(__file__).resolve().parents[5]
assert PLUGINS_DIR.name == "plugins", PLUGINS_DIR
assert (REPO_ROOT_DIR / "pyproject.toml").is_file(), REPO_ROOT_DIR

# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestInlinePromptContract:
    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_007_inline_size_guard_present(self, script: Path) -> None:
        """AGYS-DT-007: every inlining script guards the 256000-byte argv limit.

        Stage 2 was missing this guard (Codex R2 P2) while stage1/R2 had it — a
        verbose R1 raw could otherwise hit 'argument list too long'.
        """
        src = script.read_text(encoding="utf-8")
        assert "256000" in src
        assert "wc -c <" in src


class TestValidatorFlagContract:
    """The per-stage validator arg contract (pr-test-analyzer finding)."""

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_004_full_review_requires_verdict_and_changed(self, script: Path) -> None:
        """AGYS-DT-004: stage1 / R2 validate with --require-verdict + --changed-files."""
        src = script.read_text(encoding="utf-8")
        assert "agy_validate.py" in src
        assert "--require-verdict" in src
        assert "--changed-files" in src

    def test_agys_dt_005_stage2_changed_files_no_require_verdict(self) -> None:
        """AGYS-DT-005: stage2 validates with --changed-files but NOT --require-verdict.

        Stage 2 emits JSON; requiring a markdown Verdict section would wrongly
        fail valid extractions (the JSON schema check owns verdict validation).
        """
        src = STAGE2.read_text(encoding="utf-8")
        assert "agy_validate.py" in src
        assert "--changed-files" in src
        assert "--require-verdict" not in src

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_006_validator_via_script_dir(self, script: Path) -> None:
        """AGYS-DT-006: the validator is located via $SCRIPT_DIR (portable)."""
        src = script.read_text(encoding="utf-8")
        assert 'SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)' in src
        assert '"$SCRIPT_DIR/agy_validate.py"' in src


# --------------------------------------------------------------------------- #
# Runtime --add-dir contract (authoritative)
# --------------------------------------------------------------------------- #

CONSULT_SH = PLUGINS_DIR / "3rd-tools/skills/agy-consult/scripts/consult.sh"
RUN_SH = PLUGINS_DIR / "3rd-tools/skills/agy-review/scripts/run.sh"
PROBE_SH = REPO_ROOT_DIR / "scripts/probe-agy-sandbox.sh"

# Unchanged, non-isolated callers retain their runtime argument checks.
_RUNTIME_CASES: dict[str, tuple[Path, list[str]]] = {
    "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh": (CONSULT_SH, []),
    "plugins/3rd-tools/skills/agy-review/scripts/run.sh": (RUN_SH, ["review", "main", ""]),
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh": (STAGE2, []),
    "scripts/probe-agy-sandbox.sh": (PROBE_SH, []),
}
_EXPECTED_SKILL_MODELS = {
    "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh": "gemini-3.8-flash-high",
    "plugins/3rd-tools/skills/agy-review/scripts/run.sh": "gemini-3.8-flash-high",
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh": "Gemini 3.8 Flash (High)",
}


_ARGV_RECORD_SEP = "\x01"


def _recorded_invocations(capture: Path) -> list[list[str]]:
    """Decode the stub's capture file into one argv list per agy invocation.

    Each record is `arg\\0arg\\0…arg\\0` and records are separated by `\\1`; the trailing
    empty field from the final `\\0` is dropped. Lossless, unlike a line-based decode —
    see `_FAKE_AGY` for the false PASS that motivated it.
    """
    raw = capture.read_text(encoding="utf-8")
    return [record.split("\0")[:-1] for record in raw.split(_ARGV_RECORD_SEP) if record]


def _extract_flag_values(argv: list[str], flag: str) -> list[str | None]:
    """Return every value passed to ``flag``, preserving missing trailing values."""
    values: list[str | None] = []
    for i, token in enumerate(argv):
        if token == flag:
            values.append(argv[i + 1] if i + 1 < len(argv) else None)
        elif token.startswith(f"{flag}="):
            values.append(token.split("=", 1)[1])
    return values


@pytest.fixture
def agy_runtime_env(tmp_path: Path) -> dict[str, object]:
    """A throwaway repo seeded for **every** agy script, with an argv-recording stub agy.

    Deliberately one fixture for all six: the scripts differ only in which input files
    they demand, and seeding all of them keeps the per-script recipe to "arguments plus
    cwd" instead of six near-identical fixtures that drift apart.
    """
    if shutil.which("git") is None or shutil.which("bash") is None:
        pytest.skip("git/bash not available")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    # A second commit so run.sh's `git diff HEAD~1` fallback yields a non-empty diff.
    (repo / "seed.txt").write_text("seed\nmore\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "second")

    review = repo / ".pr-review"
    review.mkdir()
    (review / "prompt-r1.md").write_text("REVIEW PROMPT MARKER\n", encoding="utf-8")
    (review / "diff.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")
    (review / "changed-files.txt").write_text("seed.txt\n", encoding="utf-8")
    (review / "gemini-r1-raw.md").write_text("## Verdict\nLGTM seed.txt\n", encoding="utf-8")
    (review / "prompt-r2.md").write_text("R2 PROMPT\n", encoding="utf-8")
    (review / "r1-aggregate.md").write_text("## Claude\nnothing\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_agy = bin_dir / "agy"
    fake_agy.write_text(_FAKE_AGY, encoding="utf-8")
    fake_agy.chmod(0o755)

    # stage2 resolves its extract prompt through `~`, which follows HOME.
    home = tmp_path / "home"
    prompts = home / ".agents/skills/pr-cycle-deep/prompts"
    prompts.mkdir(parents=True)
    (prompts / "extract-r1.md").write_text("EXTRACT PROMPT\n", encoding="utf-8")

    # probe-agy-sandbox.sh checks onboardingComplete before calling agy.
    onboarding_dir = home / ".gemini/antigravity-cli/cache"
    onboarding_dir.mkdir(parents=True)
    (onboarding_dir / "onboarding.json").write_text(
        '{"onboardingComplete": true}', encoding="utf-8"
    )

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "agy-consult-question.txt").write_text("測試問題\n", encoding="utf-8")

    argv_capture = tmp_path / "agy_argv.txt"
    out_file = tmp_path / "agy_out.md"
    out_file.write_text(GOOD_REVIEW, encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "CLAUDE_JOB_DIR": str(job_dir),
        "AGY_FAKE_ARGV": str(argv_capture),
        "AGY_FAKE_OUTPUT": str(out_file),
    }
    env.pop("AGY_MODEL", None)
    return {"repo": repo, "env": env, "argv_capture": argv_capture}


class TestAgyRuntimeContract:
    """Authoritative checks for the arguments bash actually passes to agy."""

    @pytest.mark.parametrize("rel_path", sorted(_RUNTIME_CASES))
    def test_agys_dt_012_invocation_contract_at_runtime(
        self, rel_path: str, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-DT-012: every call uses an absolute workspace and expected skill model.

        The script's own exit code is deliberately NOT asserted: several stages run
        `agy_validate.py` on the stub's canned output afterwards and may legitimately fail.
        What matters is the argv agy received, recorded before any validation.
        """
        script, args = _RUNTIME_CASES[rel_path]
        argv_capture = Path(str(agy_runtime_env["argv_capture"]))
        if argv_capture.exists():
            argv_capture.unlink()

        result = subprocess.run(  # nosec B603
            ["bash", str(script), *args],
            cwd=str(agy_runtime_env["repo"]),
            env=agy_runtime_env["env"],  # type: ignore[arg-type]
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert argv_capture.exists(), (
            f"{script.name} never invoked agy (stdout={result.stdout!r} "
            f"stderr={result.stderr!r}). The runtime contract cannot be checked; fix the "
            "fixture's preconditions rather than deleting this assertion."
        )
        invocations = _recorded_invocations(argv_capture)
        assert invocations, f"{script.name}: capture file exists but decoded to no records"
        # Every invocation, not just the last: a script that calls agy twice must not be
        # able to hide a bad call behind a good one.
        # Skip version-query invocations (e.g. `agy --version`): they legitimately
        # have no --add-dir and no file context is needed.
        content_invocations = [argv for argv in invocations if argv != ["--version"]]
        assert content_invocations, (
            f"{script.name}: all {len(invocations)} agy invocations were version "
            "queries — no content invocation to check"
        )
        for n, argv in enumerate(content_invocations, start=1):
            where = f"{script.name} (agy invocation {n} of {len(content_invocations)})"
            add_dirs = _extract_flag_values(argv, "--add-dir")
            assert len(add_dirs) == 1, f"{where} must pass exactly one --add-dir; argv={argv!r}"
            value = add_dirs[0]
            assert value is not None, (
                f"{where} passed --add-dir as the final argument, with no value after it. "
                f"argv={argv!r}"
            )
            assert Path(value).is_absolute(), (
                f"{where} passed agy a RELATIVE --add-dir ({value!r}). agy 1.1.22 does not "
                "resolve a relative path into an active workspace: it silently loses all "
                "file context and still exits 0."
            )
            expected_model = _EXPECTED_SKILL_MODELS.get(rel_path)
            if expected_model is not None:
                models = _extract_flag_values(argv, "--model")
                assert models == [expected_model], (
                    f"{where} must pass exactly one --model {expected_model!r}; "
                    f"actual values={models!r}; argv={argv!r}"
                )


# --------------------------------------------------------------------------- #
# Behavioral integration test (stage 1)
# --------------------------------------------------------------------------- #

_FAKE_AGY = """#!/usr/bin/env bash
# Fake agy: append this invocation's argv, NUL-delimited, then emit the canned review.
#
# NUL is the only byte that cannot occur inside an argv element, so this encoding is
# lossless. A newline-delimited rendering is NOT: every one of these scripts passes the
# whole review prompt -- including diff.patch -- as the `-p` value, and that argument sits
# BEFORE --add-dir. Decoded by lines, a diff line reading `--add-dir` followed by a line
# holding an absolute path is indistinguishable from the real flag and its value, so the
# check reads PR-controlled content instead of the executed argument. That was a live
# false PASS, not a hypothetical (PR #409 Round 2).
#
# \\1 terminates each record so a script invoking agy more than once stays inspectable;
# appending rather than overwriting is what makes the second invocation visible at all.
#
# `--help` is answered without recording: the 3rd-tools scripts probe `agy --help` for
# --print-timeout / --log-file before invoking agy (an agy too old for those flags exits 2,
# which would otherwise be indistinguishable from their own argument-validation exit 2).
# That probe is not a content invocation, so recording it would make the --add-dir contract
# check below fail on an argv that legitimately carries no --add-dir.
if [ "$1" = --help ]; then
    printf '%s\\n' '  --print-timeout  Timeout for print mode wait (default 5m0s)'
    printf '%s\\n' '  --log-file       Override CLI log file path'
    exit 0
fi
if [ "${AGY_FAKE_CAPTURE:-1}" = 1 ]; then
    printf '%s\\0' "$@" >> "$AGY_FAKE_ARGV"
    printf '\\1' >> "$AGY_FAKE_ARGV"
fi
cat "$AGY_FAKE_OUTPUT"
"""

_ROGUE_AGY = """#!/usr/bin/env bash
# Fake agy attempts a tracked-file write; the OS must deny it.
echo "rogue edit" >> seed.txt
cat "$AGY_FAKE_OUTPUT"
"""

_FAKE_AGY_SANDBOX_DENY = """#!/usr/bin/env bash
# Fake agy simulating sandbox auto-deny: exits 0 with empty stdout and a
# stderr message about the command permission being denied. This is the exact
# failure shape agy produces in headless -p mode when --sandbox is used and a
# tool requiring the "command" permission is needed but cannot be interactively
# approved. <!-- verified: probe, agy 1.1.12 -->
if [ "$1" = --help ]; then
    printf '%s\\n' '  --print-timeout  Timeout for print mode wait (default 5m0s)'
    printf '%s\\n' '  --log-file       Override CLI log file path'
    exit 0
fi
printf '%s\\0' "$@" >> "$AGY_FAKE_ARGV"
printf '\\1' >> "$AGY_FAKE_ARGV"
for arg in "$@"; do
    if [ "$arg" = "--sandbox" ]; then
        echo "no output produced -- a tool required the command permission" >&2
        exit 0
    fi
done
cat "$AGY_FAKE_OUTPUT"
"""

GOOD_REVIEW = """## Verdict
NEEDS_CHANGES

### [important] race in tasks/foo/service.py
Missing lock around the shared counter.
"""

WRONG_TARGET_REVIEW = """## Verdict
NEEDS_CHANGES

### [critical] bug in lib/other/handler.go
Reviewed an entirely different file.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


@pytest.fixture
def stage1_env(tmp_path: Path) -> dict[str, object]:
    """A throwaway git repo + .pr-review dir + fake agy on PATH for stage1."""
    if shutil.which("git") is None or shutil.which("bash") is None:
        pytest.skip("git/bash not available")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")

    review = repo / ".pr-review"
    review.mkdir()
    (review / "prompt-r1.md").write_text("REVIEW PROMPT MARKER\n", encoding="utf-8")
    (review / "diff.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")
    (review / "changed-files.txt").write_text("tasks/foo/service.py\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_agy = bin_dir / "agy"
    fake_agy.write_text(_FAKE_AGY, encoding="utf-8")
    fake_agy.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    argv_capture = tmp_path / "agy_argv.txt"
    out_file = tmp_path / "agy_out.md"

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "AGY_FAKE_ARGV": str(argv_capture),
        "AGY_FAKE_OUTPUT": str(out_file),
        "AGY_FAKE_CAPTURE": "0",
    }
    return {
        "repo": repo,
        "review": review,
        "env": env,
        "argv_capture": argv_capture,
        "out_file": out_file,
        "fake_agy": fake_agy,
    }


def _run_stage1(env_info: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["bash", str(STAGE1)],
        cwd=str(env_info["repo"]),
        env=env_info["env"],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
    )


class TestStage1Behavioral:
    def test_agys_st_001_happy_path_inlines_and_passes(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-001: a good review survives isolation and the validation gate."""
        require_isolation()
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode == 0, result.stderr

        review = Path(str(stage1_env["review"]))
        raw = (review / "gemini-r1-raw.md").read_text(encoding="utf-8")
        assert "race in tasks/foo/service.py" in raw

        assert "[WARN]" not in result.stderr

    def test_agys_st_002_wrong_target_review_fails(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-002: a review citing only foreign files is rejected (exit 1)."""
        require_isolation()
        Path(str(stage1_env["out_file"])).write_text(WRONG_TARGET_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode != 0
        assert "WRONG target" in result.stderr

    def test_agys_st_003_oversize_input_fails_loud(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-003: input over the 256000-byte inline guard fails before calling agy."""
        review = Path(str(stage1_env["review"]))
        (review / "diff.patch").write_text("x" * 300_000, encoding="utf-8")
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode != 0
        assert "256000" in result.stderr
        # agy must NOT have been invoked (guard fires first)
        assert not Path(str(stage1_env["argv_capture"])).exists()

    def test_agys_st_004_out_of_band_edit_is_denied(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-004: a rogue review cannot modify even its disposable snapshot."""
        require_isolation()
        Path(str(stage1_env["fake_agy"])).write_text(_ROGUE_AGY, encoding="utf-8")
        Path(str(stage1_env["fake_agy"])).chmod(0o755)
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")

        result = _run_stage1(stage1_env)

        assert result.returncode == 0, result.stderr
        assert "[WARN]" not in result.stderr
        assert (Path(str(stage1_env["repo"])) / "seed.txt").read_text() == "seed\n"
        log = Path(str(stage1_env["review"])) / "gemini-r1.stage1.log"
        assert "seed.txt" in log.read_text()


# --------------------------------------------------------------------------- #
# Permission flag contract (Layer 1)
# --------------------------------------------------------------------------- #


def _extract_agy_invocation_line(src: str) -> str:
    """Extract the full agy invocation including backslash continuations."""
    raw_lines = src.splitlines()
    result_parts: list[str] = []
    in_continuation = False
    for line in raw_lines:
        stripped = line.lstrip()
        if stripped.startswith("#") and not in_continuation:
            continue
        if in_continuation:
            result_parts.append(stripped.rstrip("\\").strip())
            if not line.rstrip().endswith("\\"):
                in_continuation = False
            continue
        if re.search(r"(^|\s)agy\s+-p\s+", stripped):
            result_parts.append(stripped.rstrip("\\").strip())
            if line.rstrip().endswith("\\"):
                in_continuation = True
    return " ".join(result_parts)


class TestPermissionFlagContract:
    """Permission flag contract: each agy script uses the correct permission mode.

    stage1/R2 need the `command` tool for exploring surrounding code during review,
    which --sandbox auto-denies in headless mode. stage2 does extraction only and
    does not need `command`, so --sandbox is sufficient and more secure.

    This contract was previously unguarded — zero tests pinned which script used
    which flag, so regressions could ship silently.
    """

    def test_agys_dt_015_extract_stage_uses_sandbox(self) -> None:
        """AGYS-DT-015: extract stage uses --sandbox, NOT --dangerously-skip-permissions.

        spec: agy-sandbox-permission-contract#extract-flag-regressed-to-bypass
        """
        invocation = _extract_agy_invocation_line(STAGE2.read_text(encoding="utf-8"))
        assert invocation, "agy-r1-stage2.sh: no agy invocation line found"
        assert "--sandbox" in invocation, (
            "agy-r1-stage2.sh: extract stage MUST use --sandbox "
            "(extraction does not need the command tool)"
        )
        assert "--dangerously-skip-permissions" not in invocation, (
            "agy-r1-stage2.sh: extract stage MUST NOT use --dangerously-skip-permissions "
            "(unnecessary privilege escalation for a text extraction task)"
        )


# --------------------------------------------------------------------------- #
# Sandbox auto-deny detection (Layer 2)
# --------------------------------------------------------------------------- #


class TestSandboxAutoDenyDetection:
    """Behavioral tests verifying scripts detect agy's sandbox auto-deny failure.

    agy exits 0 with empty stdout when --sandbox auto-denies a needed tool in
    headless mode. The calling script's guard must catch this and exit non-zero.
    """

    def test_agys_st_005_stage2_detects_empty_output(self, tmp_path: Path) -> None:
        """AGYS-ST-005: stage2 detects sandbox auto-deny empty output.

        spec: agy-sandbox-permission-contract#stub-auto-deny-detected
        """
        if shutil.which("git") is None or shutil.which("bash") is None:
            pytest.skip("git/bash not available")

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "seed")

        review = repo / ".pr-review"
        review.mkdir()
        (review / "gemini-r1-raw.md").write_text("## Verdict\nLGTM seed.txt\n", encoding="utf-8")
        (review / "changed-files.txt").write_text("seed.txt\n", encoding="utf-8")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_agy = bin_dir / "agy"
        fake_agy.write_text(_FAKE_AGY_SANDBOX_DENY, encoding="utf-8")
        fake_agy.chmod(0o755)

        home = tmp_path / "home"
        prompts = home / ".agents/skills/pr-cycle-deep/prompts"
        prompts.mkdir(parents=True)
        (prompts / "extract-r1.md").write_text("EXTRACT PROMPT\n", encoding="utf-8")

        argv_capture = tmp_path / "agy_argv.txt"
        out_file = tmp_path / "agy_out.md"
        out_file.write_text("should not be used", encoding="utf-8")

        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(home),
            "AGY_FAKE_ARGV": str(argv_capture),
            "AGY_FAKE_OUTPUT": str(out_file),
        }

        result = subprocess.run(  # nosec B603
            ["bash", str(STAGE2)],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode != 0, (
            f"stage2 MUST exit non-zero when agy produces empty output "
            f"(sandbox auto-deny), but exited {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        assert "[FAIL]" in result.stderr, (
            f"stage2 MUST print [FAIL] on stderr when agy output is empty. stderr={result.stderr!r}"
        )


# --------------------------------------------------------------------------- #
# Print-timeout detection (issue #443)
# --------------------------------------------------------------------------- #

_FAKE_AGY_TIMEOUT = """#!/usr/bin/env bash
# Fake agy reproducing the agy >= 1.1.28 print-timeout shape: exit 0, whatever output
# was produced so far on stdout, and the marker line only on stderr. Measured on agy
# 1.2.4: `[agy] print timeout after 40s with turn in progress; returning partial output`.
# AGY_FAKE_SLEEP delays the return (drives the elapsed-time signal); AGY_FAKE_MARKER=1
# emits the stderr marker.
if [ "$1" = --help ]; then
    printf '%s\\n' '  --print-timeout  Timeout for print mode wait (default 5m0s)'
    printf '%s\\n' '  --log-file       Override CLI log file path'
    exit 0
fi
if [ "${AGY_FAKE_CAPTURE:-1}" = 1 ]; then
    printf '%s\\0' "$@" >> "$AGY_FAKE_ARGV"
    printf '\\1' >> "$AGY_FAKE_ARGV"
fi
if [ -n "${AGY_FAKE_SLEEP:-}" ]; then
    sleep "$AGY_FAKE_SLEEP"
fi
cat "$AGY_FAKE_OUTPUT"
if [ "${AGY_FAKE_MARKER:-0}" = 1 ]; then
    echo "[agy] print timeout after 8m0s with turn in progress; returning partial output" >&2
fi
exit 0
"""

# A Round 2 response cut off mid-finding. Its FIRST heading already contains "verdict", so
# agy_validate.py's substring check passes it -- the exact hole issue #443 describes.
TRUNCATED_R2 = """## Cross-review verdict
The other reviewers were broadly right about seed.txt.

## Per-finding response
### Other reviewer's finding: seed handling
- Verdict: AGREE
- Reason: the change in seed.txt is corr"""

COMPLETE_R2 = (
    TRUNCATED_R2
    + """ect.

## New findings (missed in R1)

## Withdrawals (R1 items I'm retracting)

## Final verdict
- LGTM
"""
)

_TIMEOUT_SCRIPTS = {"stage1": STAGE1, "stage2": STAGE2, "r2": R2}


def _run_with_fake_timeout_agy(
    runtime: dict[str, object], script: Path, output: str, **env_extra: str
) -> subprocess.CompletedProcess[str]:
    env = dict(runtime["env"])  # type: ignore[call-overload]
    bin_dir = Path(env["AGY_FAKE_ARGV"]).parent / "bin"
    fake = bin_dir / "agy"
    fake.write_text(_FAKE_AGY_TIMEOUT, encoding="utf-8")
    fake.chmod(0o755)
    Path(env["AGY_FAKE_OUTPUT"]).write_text(output, encoding="utf-8")
    env.pop("AGY_PRINT_TIMEOUT_SECS", None)
    env.update(env_extra)
    if script in (STAGE1, R2):
        env["AGY_FAKE_CAPTURE"] = "0"
        budget = env.get("AGY_PRINT_TIMEOUT_SECS", "480")
        if budget.isdecimal() and 1 <= int(budget) <= 570:
            require_isolation()
    return subprocess.run(  # nosec B603
        ["bash", str(script)],
        cwd=str(runtime["repo"]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestPrintTimeoutDetection:
    """issue #443: agy >= 1.1.28 returns partial output with exit 0 on --print-timeout."""

    def test_agys_st_006_truncated_r2_with_marker_is_not_counted(
        self, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-ST-006: a truncated R2 plus the stderr marker fails with exit 124.

        Before the fix this exited 0: the truncated text passes agy_validate.py (its first
        heading contains "verdict"), so a half-read debate counted as a full mob vote. The
        partial output must also leave gemini-r2.md, where aggregation would pick it up.
        """
        result = _run_with_fake_timeout_agy(agy_runtime_env, R2, TRUNCATED_R2, AGY_FAKE_MARKER="1")
        assert result.returncode == 124, result.stderr
        assert "print timeout" in result.stderr
        review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
        assert not (review / "gemini-r2.md").exists()
        partial = review / "gemini-r2.timeout-partial.md"
        assert partial.read_text(encoding="utf-8") == TRUNCATED_R2
        assert partial.stat().st_mode & 0o777 == 0o600

    @pytest.mark.parametrize("name", sorted(_TIMEOUT_SCRIPTS))
    def test_agys_st_007_marker_with_empty_output_reports_timeout(
        self, name: str, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-ST-007: every agy script reports the timeout, not "empty output".

        agy 1.2.4 measured: a timeout during 429 retry backoff returns 0 bytes. The old
        scripts then blamed an empty/invalid output, hiding the real cause.
        """
        script = _TIMEOUT_SCRIPTS[name]
        result = _run_with_fake_timeout_agy(agy_runtime_env, script, "", AGY_FAKE_MARKER="1")
        assert result.returncode == 124, f"{name}: {result.stderr}"
        assert "print timeout" in result.stderr

    def test_agys_st_008_elapsed_over_budget_without_marker_fails(
        self, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-ST-008: exceeding the budget is a timeout even if agy prints no marker.

        The marker is presentation and may change wording between agy versions; wall-clock
        time over the budget is the second, wording-independent signal.
        """
        result = _run_with_fake_timeout_agy(
            agy_runtime_env,
            R2,
            COMPLETE_R2,
            AGY_PRINT_TIMEOUT_SECS="1",
            AGY_FAKE_SLEEP="3",
        )
        assert result.returncode == 124, result.stderr

    def test_agys_st_009_complete_r2_within_budget_passes(
        self, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-ST-009: negative control -- a complete, in-budget R2 still passes."""
        result = _run_with_fake_timeout_agy(agy_runtime_env, R2, COMPLETE_R2)
        assert result.returncode == 0, result.stderr
        review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
        assert (review / "gemini-r2.md").read_text(encoding="utf-8") == COMPLETE_R2
        assert not (review / "gemini-r2.timeout-partial.md").exists()

    @pytest.mark.parametrize("name", sorted(_TIMEOUT_SCRIPTS))
    @pytest.mark.parametrize("budget", ["600", "0", "abc", "99999999999999999999"])
    def test_agys_st_010_invalid_budget_fails_before_agy(
        self, name: str, budget: str, agy_runtime_env: dict[str, object]
    ) -> None:
        """AGYS-ST-010: an out-of-range budget exits 2 without invoking agy.

        600 would let the Claude Code Bash tool (600 s cap) kill the script before any
        diagnostic prints; 0 would make the elapsed signal fire on every run.
        """
        script = _TIMEOUT_SCRIPTS[name]
        argv_capture = Path(str(agy_runtime_env["argv_capture"]))
        if argv_capture.exists():
            argv_capture.unlink()
        result = _run_with_fake_timeout_agy(
            agy_runtime_env, script, COMPLETE_R2, AGY_PRINT_TIMEOUT_SECS=budget
        )
        assert result.returncode == 2, f"{name}/{budget}: {result.stderr}"
        assert "AGY_PRINT_TIMEOUT_SECS" in result.stderr
        assert not argv_capture.exists(), f"{name}/{budget}: agy was invoked"
