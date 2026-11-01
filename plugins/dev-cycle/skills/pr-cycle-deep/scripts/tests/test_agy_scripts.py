"""Behavioral review/timeout tests plus contracts for unchanged extraction callers.

Review-stage containment is exercised against the real OS backend in
test_agy_isolate.py; source/argv-only assertions are not a safety boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
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

_FAKE_AGY_BODY = r"""
import hashlib
import json
import os
import pathlib
import re
import sys
import time

args = sys.argv[1:]
if args == ['--help']:
    print('--print-timeout --log-file')
    sys.exit(0)
if os.environ.get('AGY_FAKE_CAPTURE', '1') == '1':
    with open(os.environ['AGY_FAKE_ARGV'], 'ab') as capture:
        capture.write(b''.join(arg.encode() + b'\0' for arg in args) + b'\1')

streaming = '--input-format' in args
if streaming:
    assert args[args.index('--input-format') + 1] == 'stream-json'
    assert args[args.index('--output-format') + 1] == 'stream-json'
    assert '-p' not in args and '--prompt' not in args
    lines = sys.stdin.buffer.read().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event['event'] == 'user' and event['message']['role'] == 'user'
    prompt = event['message']['content']
    assert isinstance(prompt, str) and not prompt.startswith('@')
if mode == 'rogue':
    try:
        pathlib.Path('seed.txt').write_text('rogue edit\n')
    except OSError as exc:
        print(exc, file=sys.stderr)
if mode == 'deny' and '--sandbox' in args:
    print('no output produced -- a tool required the command permission', file=sys.stderr)
    sys.exit(0)
if mode == 'timeout' and os.environ.get('AGY_FAKE_SLEEP'):
    time.sleep(float(os.environ['AGY_FAKE_SLEEP']))
if os.environ.get('AGY_FAKE_WRITE_PROBE') == '1':
    target = pathlib.Path(args[args.index('--add-dir') + 1]) / 'seed.txt'
    if '--sandbox' not in args or '--dangerously-skip-permissions' in args:
        target.write_text('CORRUPTED by extraction\n', encoding='utf-8')
        print('write probe: allowed', file=sys.stderr)
    else:
        print('write probe: denied', file=sys.stderr)

response = pathlib.Path(os.environ['AGY_FAKE_OUTPUT']).read_text(encoding='utf-8')
if os.environ.get('AGY_FAKE_DIGEST') == '1':
    assert streaming
    report = []
    for match in re.finditer(
        r'BEGIN_TRANSPORT_(\w+)\n(.*?)END_TRANSPORT_\1\n', prompt, re.DOTALL
    ):
        data = match[2].encode('utf-8')
        report.append({
            'segment': match[1], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        })
    summary = json.dumps(report)
    if '--sandbox' in args:
        response = json.dumps({'verdict': 'LGTM', 'summary': summary, 'findings': []})
    else:
        response = '## Verdict\nLGTM\nReviewed seed.txt\n\n' + summary + '\n'
if streaming:
    stream_mode = os.environ.get('AGY_FAKE_STREAM_MODE', 'success')
    if stream_mode in ('missing_result', 'malformed_result'):
        print(json.dumps({'event': 'step_update', 'step_update': {
            'step_type': 'agent_response', 'text_delta': response,
        }}), flush=True)
    result = {'status': 'SUCCESS', 'response': response}
    if stream_mode == 'error':
        result.update(status='ERROR', error='external review failed')
    elif stream_mode == 'interrupted':
        result['finished_reason'] = 'interrupted'
    elif stream_mode == 'malformed_result':
        result['response'] = None
    if os.environ.get('AGY_FAKE_FINISHED_REASON'):
        result['finished_reason'] = os.environ['AGY_FAKE_FINISHED_REASON']
    if stream_mode != 'missing_result':
        print(json.dumps({'event': 'result', 'result': result}), flush=True)
    if stream_mode == 'duplicate':
        print(json.dumps({'event': 'result', 'result': result}), flush=True)
else:
    sys.stdout.write(response)
if mode == 'timeout' and os.environ.get('AGY_FAKE_MARKER') == '1':
    print(
        '[agy] print timeout after 8m0s with turn in progress; returning partial output',
        file=sys.stderr,
    )
"""

_FAKE_AGY = f"#!{sys.executable}\nmode = 'normal'\n" + _FAKE_AGY_BODY
_ROGUE_AGY = f"#!{sys.executable}\nmode = 'rogue'\n" + _FAKE_AGY_BODY
_FAKE_AGY_SANDBOX_DENY = f"#!{sys.executable}\nmode = 'deny'\n" + _FAKE_AGY_BODY

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
    def test_agys_st_001_happy_path_streams_and_passes(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-001: a good review survives isolation and the validation gate."""
        require_isolation()
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode == 0, result.stderr

        review = Path(str(stage1_env["review"]))
        raw = (review / "gemini-r1-raw.md").read_text(encoding="utf-8")
        assert "race in tasks/foo/service.py" in raw

        assert "[WARN]" not in result.stderr

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


@pytest.mark.parametrize("stage", ["stage1", "stage2", "r2"])
def test_agys_st_003_large_input_reaches_published_review_losslessly(
    stage: str, agy_runtime_env: dict[str, object]
) -> None:
    """AGYS-ST-003：完整傳送超過 argv 上限的 Unicode 多行輸入，並發布可驗證的結果。"""
    if stage != "stage2":
        require_isolation()
    env = dict(agy_runtime_env["env"])  # type: ignore[call-overload]
    repo = Path(str(agy_runtime_env["repo"]))
    review = repo / ".pr-review"
    if stage == "stage1":
        script = STAGE1
        inputs = {"prompt": review / "prompt-r1.md", "diff": review / "diff.patch"}
        output = review / "gemini-r1-raw.md"
    elif stage == "r2":
        script = R2
        inputs = {"prompt": review / "prompt-r2.md", "aggregate": review / "r1-aggregate.md"}
        output = review / "gemini-r2.md"
    else:
        script = STAGE2
        inputs = {
            "prompt": Path(env["HOME"]) / ".agents/skills/pr-cycle-deep/prompts/extract-r1.md",
            "raw": review / "gemini-r1-raw.md",
        }
        output = review / "gemini-r1.json"
    expected = []
    for name, path in inputs.items():
        payload = (f'{name}: 雪🙂 "quoted" \\\\path\tline\n' * 20_000) + f"END {name} 尾端\n\n"
        data = payload.encode("utf-8")
        assert len(data) > 300_000
        path.write_text(
            f"BEGIN_TRANSPORT_{name}\n{payload}END_TRANSPORT_{name}\n", encoding="utf-8"
        )
        expected.append(
            {"segment": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    env.update(AGY_FAKE_CAPTURE="0", AGY_FAKE_DIGEST="1")
    result = subprocess.run(  # nosec B603
        ["bash", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    published = output.read_text(encoding="utf-8")
    if stage == "stage2":
        extraction = json.loads(published)
        assert extraction["verdict"] == "LGTM"
        assert extraction["findings"] == []
        actual = json.loads(extraction["summary"])
    else:
        assert "## Verdict\nLGTM\nReviewed seed.txt\n" in published
        actual = json.loads(published.split("\n\n", 1)[1])
    assert actual == expected
    assert not list(review.glob("*.timeout-partial*"))


_STREAM_STAGES = {
    "stage1": (STAGE1, "gemini-r1-raw.md", "gemini-r1.stage1.log", "agy R1 Stage 1 complete"),
    "stage2": (STAGE2, "gemini-r1.json", "gemini-r1.extract.log", "agy R1 Stage 2 complete"),
    "r2": (R2, "gemini-r2.md", "gemini-r2.log", "agy R2 complete"),
}


def _run_stream_stage(
    runtime: dict[str, object], stage: str, response: str, **env_extra: str
) -> subprocess.CompletedProcess[str]:
    if stage != "stage2":
        require_isolation()
    env = dict(runtime["env"])  # type: ignore[call-overload]
    Path(env["AGY_FAKE_OUTPUT"]).write_text(response, encoding="utf-8")
    env.update(AGY_FAKE_CAPTURE="0", AGY_FAKE_STREAM_MODE="success")
    env.update(env_extra)
    return subprocess.run(  # nosec B603
        ["bash", str(_STREAM_STAGES[stage][0])],
        cwd=str(runtime["repo"]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("stage", _STREAM_STAGES)
def test_agys_st_002_wrong_target_review_fails(
    stage: str, agy_runtime_env: dict[str, object]
) -> None:
    """AGYS-ST-002：格式合法但只引用不存在檔案的回應，三階段都不能採用。"""
    response = WRONG_TARGET_REVIEW
    if stage == "stage2":
        response = json.dumps(
            {
                "verdict": "NEEDS_CHANGES",
                "summary": "Found a defect",
                "findings": [{"file": "lib/other/handler.go", "issue": "Missing synchronization"}],
            }
        )
    result = _run_stream_stage(agy_runtime_env, stage, response)
    assert result.returncode != 0, result.stdout
    assert _STREAM_STAGES[stage][3] not in result.stdout
    assert "[FAIL]" in result.stderr
    if stage == "stage2":
        review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
        assert not (review / "gemini-r1.json").exists()


@pytest.mark.parametrize("stage", _STREAM_STAGES)
@pytest.mark.parametrize(
    ("mode", "diagnostic"),
    [
        ("success", None),
        ("error", "external review failed"),
        ("missing_result", "缺少終端 result"),
        ("interrupted", "finished_reason='interrupted'"),
        ("duplicate", "終端 result 之後仍有 event"),
        ("malformed_result", "result 缺少字串 response"),
    ],
)
def test_agys_st_011_stream_failure_is_not_published(
    stage: str, mode: str, diagnostic: str | None, agy_runtime_env: dict[str, object]
) -> None:
    """AGYS-ST-011：完整正文不能掩蓋失敗 envelope；成功對照必須可發布相同正文。"""
    extraction = {"verdict": "LGTM", "summary": "Reviewed seed.txt", "findings": []}
    response = (
        json.dumps(extraction) if stage == "stage2" else "## Verdict\nLGTM\nReviewed seed.txt\n"
    )
    result = _run_stream_stage(agy_runtime_env, stage, response, AGY_FAKE_STREAM_MODE=mode)
    _, artifact, log_name, completion = _STREAM_STAGES[stage]
    review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
    if diagnostic is None:
        assert result.returncode == 0, result.stderr
        assert completion in result.stdout
        published = (review / artifact).read_text(encoding="utf-8")
        if stage == "stage2":
            assert json.loads(published) == extraction
        else:
            assert published == response
    else:
        assert result.returncode != 0, result.stdout
        assert completion not in result.stdout
        assert "[FAIL]" in result.stderr
        assert diagnostic in (review / log_name).read_text(encoding="utf-8")
        if stage == "stage2":
            assert not (review / artifact).exists()
        else:
            # 非逾時失敗仍保留原檔名的正文供診斷，不能誤稱所有失敗都會隔離改名。
            assert (review / artifact).read_text(encoding="utf-8") == response


@pytest.mark.parametrize("stage", ["stage1", "r2"])
@pytest.mark.parametrize("with_verdict", [False, True], ids=["missing-verdict", "complete"])
def test_agys_st_012_review_without_verdict_is_rejected(
    stage: str, with_verdict: bool, agy_runtime_env: dict[str, object]
) -> None:
    """AGYS-ST-012：引用正確檔案且 stream 成功仍須通過 Verdict gate。"""
    response = "## Summary\nReviewed seed.txt; no issues found.\n"
    if with_verdict:
        response += "\n## Verdict\nLGTM\n"
    result = _run_stream_stage(agy_runtime_env, stage, response)
    _, artifact, _, completion = _STREAM_STAGES[stage]
    review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
    assert (review / artifact).read_text(encoding="utf-8") == response
    if with_verdict:
        assert result.returncode == 0, result.stderr
        assert completion in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert completion not in result.stdout
        assert "[FAIL]" in result.stderr


def test_agys_st_013_extraction_does_not_authorize_writes(
    agy_runtime_env: dict[str, object],
) -> None:
    """AGYS-ST-013：萃取成功也不能授權外部 CLI 寫入原始工作樹。"""
    repo = Path(str(agy_runtime_env["repo"]))
    seed = repo / "seed.txt"
    original = seed.read_bytes()
    extraction = {"verdict": "LGTM", "summary": "Reviewed seed.txt", "findings": []}
    result = _run_stream_stage(
        agy_runtime_env, "stage2", json.dumps(extraction), AGY_FAKE_WRITE_PROBE="1"
    )
    assert seed.read_bytes() == original
    assert result.returncode == 0, result.stderr
    assert "agy R1 Stage 2 complete" in result.stdout
    review = repo / ".pr-review"
    assert json.loads((review / "gemini-r1.json").read_text(encoding="utf-8")) == extraction
    assert "write probe: denied" in (review / "gemini-r1.extract.log").read_text(encoding="utf-8")


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

_FAKE_AGY_TIMEOUT = f"#!{sys.executable}\nmode = 'timeout'\n" + _FAKE_AGY_BODY

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

    @pytest.mark.parametrize("name", sorted(_TIMEOUT_SCRIPTS))
    def test_stream_print_timeout_without_stderr_quarantines_partial(
        self, name: str, agy_runtime_env: dict[str, object]
    ) -> None:
        """終端結果宣告逾時時，不得把半截回覆發布為有效 review。"""
        result = _run_with_fake_timeout_agy(
            agy_runtime_env,
            _TIMEOUT_SCRIPTS[name],
            TRUNCATED_R2,
            AGY_FAKE_FINISHED_REASON="print_timeout",
        )
        assert result.returncode == 124, result.stderr
        review = Path(str(agy_runtime_env["repo"])) / ".pr-review"
        published, partial = {
            "stage1": ("gemini-r1-raw.md", "gemini-r1-raw.timeout-partial.md"),
            "stage2": ("gemini-r1.json", "gemini-r1.json.timeout-partial.tmp"),
            "r2": ("gemini-r2.md", "gemini-r2.timeout-partial.md"),
        }[name]
        assert not (review / published).exists()
        assert (review / partial).read_text(encoding="utf-8") == TRUNCATED_R2
        assert (review / partial).stat().st_mode & 0o777 == 0o600

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
