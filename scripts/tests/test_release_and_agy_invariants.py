"""Contract tests for two silent-failure regressions fixed in the PR #229 retro.

Both guard the same shape of bug: removing the fix produces no error, just quietly
wrong behavior.

  * `agy --print` pipe form -- `-p`/`--print` takes the prompt as its VALUE (agy 1.1.2:
    `printf 'x' | agy --print` exits with `flag needs an argument: -print`). Any
    `... | agy --print --add-dir .` form therefore hands agy the string "--add-dir" as the
    prompt, never reads the piped diff, and exits 0 with an unrelated answer.
  * release-full.sh rollback -- sync_plugin_versions.py writes both package.json and
    .claude-plugin/plugin.json, but the ERR trap only reverted the former, leaving a
    half-rolled-back tree after a failed gate.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_SH = REPO_ROOT / "scripts" / "release-full.sh"
AGY_RUN_SH = REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-review" / "scripts" / "run.sh"
AGY_CONSULT_SH = (
    REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-consult" / "scripts" / "consult.sh"
)
AGY_REVIEW_SKILL_MD = REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-review" / "SKILL.md"
AGY_CONSULT_SKILL_MD = REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-consult" / "SKILL.md"

# Both scripts share the identical inline-`-p` calling contract (consult.sh was added in PR #367
# specifically mirroring run.sh's already-verified safety pattern), so every AGYRUN-DT-* case
# below runs against both -- a regression in either script must fail this suite.
AGY_SCRIPTS = [AGY_RUN_SH, AGY_CONSULT_SH]

# Matches a pipe into `agy --print` / `agy -p` with no prompt value of its own -- the broken
# form. A comment line explaining the trap must not trip this, so callers strip comments first.
_PIPED_AGY_PRINT = re.compile(r"\|\s*agy\s+(?:--print|-p)\b(?!\s+[\"'$])")


def _code_lines(path: Path) -> str:
    """Return the script source with whole-line comments removed."""
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


class TestAgyRunScriptContract:
    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_001_no_piped_print_form(self, script: Path) -> None:
        """AGYRUN-DT-001: run.sh/consult.sh must not pipe a prompt into `agy --print`.

        agy has no stdin prompt channel; the pipe form silently reviews nothing.
        """
        assert not _PIPED_AGY_PRINT.search(_code_lines(script)), (
            f"{script.name} must not use the `| agy --print` form -- agy would take the "
            "following flag as its prompt and never read the piped input (silent failure, exit 0)"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_002_prompt_inlined_as_p_value(self, script: Path) -> None:
        """AGYRUN-DT-002: the prompt is passed as -p's value."""
        assert 'agy -p "$PROMPT_CONTENT"' in script.read_text(encoding="utf-8"), (
            f"{script.name} must inline the prompt as -p's value"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_003_argmax_guard_present(self, script: Path) -> None:
        """AGYRUN-DT-003: inlining costs the ARG_MAX immunity stdin would have given, so an
        explicit size guard must gate the call (parity with pr-cycle-deep's agy scripts)."""
        src = script.read_text(encoding="utf-8")
        assert "256000" in src, f"{script.name} must guard the 256000-byte inline limit"
        assert "[FAIL]" in src, f"{script.name}'s size guard must fail loud"

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_004_empty_output_is_fail_loud(self, script: Path) -> None:
        """AGYRUN-DT-004: a near-empty agy stdout must not be presented as a clean result.

        PR #367 mob review Critical, agy 1.1.8-verified: under `--sandbox`, agy's own
        (independent) permission system can silently block an exploratory read in headless
        mode, so agy exits with empty/near-empty stdout and no signal. Both scripts must
        capture the output and fail loud rather than propagating it as-is.
        """
        src = _code_lines(script)
        assert re.search(r'OUTPUT=\$\(agy -p "\$PROMPT_CONTENT"', src), (
            f"{script.name} must capture agy's stdout into a variable, not stream it directly, "
            "so it can be inspected for empty/near-empty output"
        )
        assert "[FAIL]" in src and '-z "$OUTPUT"' in src, (
            f"{script.name} must fail loud when agy's output is empty"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_005_model_announced_on_stderr(self, script: Path) -> None:
        """AGYRUN-DT-005: the resolved agy model is announced on stderr before the call.

        Both scripts now default `AGY_MODEL` to a Gemini model (2026-09-03, agy 1.1.25:
        five Gemini model ids probed from Taiwan, all succeeded — the earlier
        `FAILED_PRECONDITION: User location is not supported` premise that forced a Claude
        default no longer holds).

        The announcement contract does NOT depend on which vendor the default names, and
        this test deliberately asserts nothing about that. It exists because the vendor is
        overridable in both directions: a caller who cannot see the resolved model cannot
        tell whether an `/agy-consult` or `/agy-review` answer came from Gemini or from
        Claude, and counting two same-family answers as two independent vendor voices in a
        mob consensus is a silent correctness failure. Flipping the default made that risk
        larger, not smaller — `AGY_MODEL=claude-sonnet-4-6` is now the override a reader
        might set, which re-creates the collapse the announcement exists to expose.

        Four documents now instruct readers to rely on this line — `pr-retro-hard`'s
        SKILL.md makes reading it a procedural gate before treating agreement as
        cross-family evidence — so it is a contract, not a debug aid. Deleting it left the
        whole suite green before this test existed.

        stderr, not stdout: the skills present the script's stdout verbatim as the answer,
        so an `[INFO]` line there would be read as part of the model's reply.
        """
        src = _code_lines(script)
        match = re.search(r'echo "\[INFO\][^"]*\$\{AGY_MODEL\}[^"]*"\s*>&2', src)
        assert match, (
            f"{script.name} must echo the resolved ${{AGY_MODEL}} to stderr (>&2) so the "
            "caller can tell which vendor actually answered"
        )
        agy_call = src.index("agy -p")
        assert match.start() < agy_call, (
            f"{script.name} must announce the model BEFORE invoking agy, so the line is "
            "present even when the agy call itself hangs or fails"
        )


# How the stub answers `agy --help`, which the scripts probe before invoking agy for real.
_HELP_MODES = {
    # A current agy: help lists both flags the scripts depend on.
    "ok": (
        "  printf '%s\\n' '  --print-timeout  Timeout for print mode wait (default 5m0s)'\n"
        "  printf '%s\\n' '  --log-file       Override CLI log file path'\n"
        "  exit 0\n"
    ),
    # An agy predating 1.1.28: help works, but neither flag exists.
    "missing_flags": (
        "  printf '%s\\n' '  --sandbox  Run in a sandbox with terminal restrictions'\n  exit 0\n"
    ),
    # agy is installed but `--help` itself fails (broken runtime, missing node, a future
    # version demanding auth first). Must NOT be reported as "your agy is too old".
    "fail": (
        "  printf '%s\\n' 'agy: failed to start language server: ENOENT node' >&2\n  exit 1\n"
    ),
}


def _make_stub_agy(
    tmp_path: Path,
    *,
    exit_code: int,
    stdout: str,
    stderr: str = "",
    log_content: str = "",
    sleep_secs: int = 0,
    help_mode: str = "ok",
) -> Path:
    """Create a directory containing a stub `agy` executable for PATH injection.

    Besides stdout/exit code, the stub can emit stderr, write `log_content` to whatever path
    the script passes via `--log-file` (agy 1.2.3 writes its RESOURCE_EXHAUSTED retries only
    there, never to stderr), sleep to simulate a slow agentic run, and records its argv one
    token per line in `<tmp_path>/stub-argv.txt`.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    argv_file = tmp_path / "stub-argv.txt"
    agy_stub = bin_dir / "agy"
    agy_stub.write_text(
        "#!/usr/bin/env bash\n"
        # The scripts probe `agy --help` for --print-timeout / --log-file before invoking agy,
        # so an old agy is rejected with its real cause instead of colliding with the scripts'
        # own exit 2 (agy exits 2 on an unknown flag too). The probe is recorded SEPARATELY:
        # keeping it out of stub-argv.txt keeps the content-invocation assertions clean, but it
        # must still be observable — AC-5 says an invalid argument may not invoke agy **at all**,
        # and `agy --help` is an invocation. A stub that silently swallowed the probe made the
        # bounds tests pass while the preflight ran before validation (Codex re-review Critical).
        f'if [ "$1" = --help ]; then\n  : >> {str(tmp_path / "stub-help-called.txt")!r}\n'
        + _HELP_MODES[help_mode]
        + "fi\n"
        f"printf '%s\\n' \"$@\" > {str(argv_file)!r}\n"
        "log=''; prev=''\n"
        'for a in "$@"; do [ "$prev" = --log-file ] && log="$a"; prev="$a"; done\n'
        f'if [ -n "$log" ]; then printf \'%s\' {log_content!r} > "$log"; fi\n'
        f"sleep {sleep_secs}\n"
        f"printf '%s' {stderr!r} >&2\n"
        f"printf '%s' {stdout!r}\n"
        f"exit {exit_code}\n"
    )
    agy_stub.chmod(0o755)
    return bin_dir


def _make_isolated_git_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo with a fake `origin/main` ref one commit behind HEAD.

    run.sh resolves its diff via `git diff origin/<base>...HEAD` against whatever `cwd` it
    is invoked from. Invoking it from the real yibi-stack checkout made the diff depend on
    that checkout's ambient state: when local HEAD is git-identical to origin/main (a clean
    sync, or the moment `make release`'s pytest gate runs -- before the version bump is
    committed), the diff is empty, run.sh's own `[FAIL] diff is empty` guard fires first, and
    every test below fails for a reason unrelated to what it is actually checking. An
    isolated repo with its own `origin/main` ref and a divergent HEAD keeps the diff
    non-empty regardless of the real checkout's state.
    """
    repo = tmp_path / "fake-repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    run("update-ref", "refs/remotes/origin/main", base_sha)
    (repo / "README.md").write_text("base\nchanged\n")
    run("add", "-A")
    run("commit", "-q", "-m", "change")
    return repo


def _run_agy_script(
    script: Path,
    tmp_path: Path,
    *,
    agy_exit: int,
    agy_stdout: str,
    agy_model: str | None = None,
    agy_stderr: str = "",
    agy_log: str = "",
    agy_sleep: int = 0,
    extra_env: dict[str, str] | None = None,
    help_mode: str = "ok",
) -> subprocess.CompletedProcess[str]:
    """Run run.sh or consult.sh against a stub `agy`, handling each script's own calling
    convention (run.sh: positional mode/base/instruction args, invoked from an isolated
    throwaway git repo -- see `_make_isolated_git_repo` -- so `git diff origin/<base>...HEAD`
    resolves independent of the real checkout's state; consult.sh: no args, reads
    $CLAUDE_JOB_DIR/agy-consult-question.txt).

    `agy_model=None` means "test the default path": `AGY_MODEL` is **removed** from the
    child environment rather than inherited. Inheriting it made these tests fail for anyone
    who had set the variable — which this repo's own docs tell readers to do — so the
    ambient value has to be controlled, not assumed absent.
    """
    bin_dir = _make_stub_agy(
        tmp_path,
        exit_code=agy_exit,
        stdout=agy_stdout,
        stderr=agy_stderr,
        log_content=agy_log,
        sleep_secs=agy_sleep,
        help_mode=help_mode,
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    # 與 AGY_MODEL 同理：環境裡殘留的覆寫值不可影響「預設路徑」測試
    env.pop("AGY_PRINT_TIMEOUT_SECS", None)
    env.update(extra_env or {})
    if agy_model is None:
        env.pop("AGY_MODEL", None)
    else:
        env["AGY_MODEL"] = agy_model
    if script.name == "run.sh":
        args: list[str] = ["review", "main", ""]
        cwd = _make_isolated_git_repo(tmp_path)
    else:
        (tmp_path / "agy-consult-question.txt").write_text("測試問題", encoding="utf-8")
        env["CLAUDE_JOB_DIR"] = str(tmp_path)
        args = []
        cwd = REPO_ROOT
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=cwd,
    )


class TestAgyScriptExecutionContract:
    """Execution-level regression tests using a stub `agy` binary (Codex R2 suggestion, PR
    #367 mob review): the static AGYRUN-DT-004 check above cannot see the two real bugs only
    actual execution surfaced -- `set -e` aborting the script at `OUTPUT=$(agy ...)` before
    `AGY_EXIT=$?` could ever run, and a bare `$AGY_EXIT` immediately followed by a full-width
    `）` folding into a different, unset variable name under `set -u` (rule 13 Quoting Rule 7:
    a non-ASCII character directly after `$VAR` with no space/ASCII boundary)."""

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_006_nonzero_agy_exit_reports_fail_not_crash(
        self, script: Path, tmp_path: Path
    ) -> None:
        """A failing agy must produce the script's own [FAIL] message and its exit code --
        not a bash crash (e.g. "unbound variable") from set -e / set -u interacting badly
        with the error-handling code that captures agy's exit status."""
        result = _run_agy_script(script, tmp_path, agy_exit=7, agy_stdout="")
        assert result.returncode == 7, (result.stdout, result.stderr)
        assert "unbound variable" not in result.stderr, result.stderr
        assert "[FAIL]" in result.stderr and "exit 7" in result.stderr, result.stderr

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_007_empty_agy_output_reports_fail(
        self, script: Path, tmp_path: Path
    ) -> None:
        """agy exiting 0 with empty stdout must fail loud, not present a blank result."""
        result = _run_agy_script(script, tmp_path, agy_exit=0, agy_stdout="")
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert "[FAIL]" in result.stderr, result.stderr

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_008_successful_agy_output_is_presented(
        self, script: Path, tmp_path: Path
    ) -> None:
        """A clean agy run must exit 0 and print its real answer to stdout.

        Also asserts AGYRUN-DT-005's runtime half: the model announcement really reaches
        stderr and really carries the resolved model name, and the answer on stdout is
        not polluted by it. The static check cannot see either property — a line moved
        below an early `exit`, or redirected to stdout, passes it.
        """
        result = _run_agy_script(
            script, tmp_path, agy_exit=0, agy_stdout="a genuine agy answer, long enough"
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "a genuine agy answer" in result.stdout
        assert "[INFO]" in result.stderr and "agy 模型" in result.stderr, result.stderr
        assert "gemini-3.8-flash-high" in result.stderr, (
            "the announcement must name the resolved model, not just say a model was used"
        )
        assert "[INFO]" not in result.stdout, (
            "the announcement must not reach stdout — the skills present stdout verbatim "
            "as the answer"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_009_announcement_follows_agy_model_override(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-009: the announcement reports the OVERRIDE, not the default.

        The default-only test above cannot tell "prints the resolved model" from "prints a
        hardcoded string" — and the override path is the one that matters, because
        mis-reporting it re-creates the exact mis-attribution the announcement exists to
        prevent.

        The override under test is deliberately `claude-sonnet-4-6`: since the default
        flipped to Gemini, falling back to Claude is the override a reader actually sets,
        and it is the one that silently collapses a mob's vendor diversity. Asserting the
        cross-family direction also keeps the two strings free of any substring overlap, so
        a passing result cannot come from one model name being contained in the other.
        """
        override = "claude-sonnet-4-6"
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, long enough",
            agy_model=override,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert override in result.stderr, (
            f"{script.name} must announce the overridden model; stderr={result.stderr!r}"
        )
        assert "gemini-3.8-flash-high" not in result.stderr, (
            f"{script.name} announced the default while AGY_MODEL was {override!r} — the "
            "line reports a hardcoded string, not the resolved model"
        )


# agy 1.2.3 實測的 print-timeout 形狀：exit 0、stdout 只有已產出的片段、stderr 多這一行。
# `--output-format json` 在同一情境回 `"status":"SUCCESS"`，所以 exit code 與 JSON 都不帶判決。
_AGY_TIMEOUT_STDERR = (
    "[agy] print timeout after 480s with turn in progress; returning partial output\n"
)
_PARTIAL_ANSWER = "I will start by listing the files under tasks/ and then read"
# agy 1.2.3 只把 429 重試寫進 --log-file，stderr 與 stdout 完全沒有痕跡
_QUOTA_LOG_LINE = (
    "I0914 19:51:47.006956     601 run.go:389] Run: attempt 2 failed (RESOURCE_EXHAUSTED "
    "(code 429): Individual quota reached. Please upgrade your subscription to increase "
    "your limits. Resets in 89h27m1s.), retrying in 7.703411217s\n"
)


class TestAgyTimeoutAndQuotaContract:
    """agy 1.2.3 的三種「exit 0 但其實失敗」必須 fail loud 並講出真正原因。

    事故：/agy-consult 與 /agy-review 在 agy 1.2.3 上反覆「失敗或 timeout」。log 顯示
    (a) print 模式預設 5 分鐘上限到期時 agy exit 0 並回傳部分輸出；(b) consumer 帳號額度
    用完時 agy 只在自己的 log 裡指數退避重試，呼叫端看到的是無聲卡住直到被 600 秒上限砍掉。
    """

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_010_timeout_marker_fails_loud_without_partial_answer(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-010: exit 0 + timeout marker must be a [FAIL], and the partial answer
        must NOT reach stdout — the skills present stdout verbatim as the finished answer."""
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout=_PARTIAL_ANSWER,
            agy_stderr=_AGY_TIMEOUT_STDERR,
        )
        assert result.returncode == 124, (result.stdout, result.stderr)
        assert "[FAIL]" in result.stderr and "timeout" in result.stderr, result.stderr
        assert _PARTIAL_ANSWER not in result.stdout, result.stdout

        # The discarded output is preserved so a false positive does not cost the user the
        # whole run — but it can hold repo content (for agy-review, the entire diff), so it
        # must be 0600. A plain `> "${LOG}.discarded-output"` is umask-dependent and lands
        # 0644 under the common umask 022 (measured). Codex re-review Critical.
        # The label and the path are glued by a full-width colon, so split on the CJK
        # punctuation the message uses before looking for the path token.
        discarded = [
            Path(word)
            for line in result.stderr.splitlines()
            for word in line.replace("；", " ").replace("：", " ").split()
            if "discarded" in word
        ]
        assert discarded, f"the timeout branch must name the preserved output: {result.stderr!r}"
        saved = discarded[-1]
        assert saved.is_file(), f"{saved} was named but not written"
        assert _PARTIAL_ANSWER in saved.read_text(encoding="utf-8"), saved.read_text(
            encoding="utf-8"
        )
        assert oct(saved.stat().st_mode)[-3:] == "600", (
            f"{saved} is mode {oct(saved.stat().st_mode)[-3:]}; preserved output may contain "
            "repository content and must not be readable by other local users"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_011_elapsed_time_detects_timeout_without_marker(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-011: detection must not hinge on agy's wording. With no marker at all,
        a run that used up the whole budget is still a timeout."""
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout=_PARTIAL_ANSWER,
            agy_sleep=2,
            extra_env={"AGY_PRINT_TIMEOUT_SECS": "1"},
        )
        assert result.returncode == 124, (result.stdout, result.stderr)
        assert _PARTIAL_ANSWER not in result.stdout, result.stdout

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_012_quota_exhaustion_named_from_log(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-012: when agy's log shows RESOURCE_EXHAUSTED, the failure message must
        surface that line instead of guessing a sandbox-permission cause."""
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="",
            agy_stderr=_AGY_TIMEOUT_STDERR,
            agy_log=_QUOTA_LOG_LINE,
        )
        assert result.returncode == 124, (result.stdout, result.stderr)
        # 逐字斷言整行，而不只是 `Individual quota reached` 子字串：只比對子字串的話，把生產端的
        # `grep RESOURCE_EXHAUSTED | tail -n 1` 換成寫死的 echo 也會通過，AC-3 要求的「原始 log
        # 行原樣呈現」（含 429 代碼與重置時間）就無人守著。（Codex R1 提出的存活突變。）
        assert _QUOTA_LOG_LINE.rstrip("\n") in result.stderr, result.stderr

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_013_print_timeout_and_log_file_passed(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-013: the default budget (480s) stays below Claude Code's 600s Bash cap,
        and the override reaches agy. A budget >= 600s means the harness kills the script
        before it can print any [FAIL] — the exact silent timeout this fixes."""
        _run_agy_script(script, tmp_path, agy_exit=0, agy_stdout="a genuine agy answer, ok")
        argv = (tmp_path / "stub-argv.txt").read_text(encoding="utf-8").splitlines()
        assert argv[argv.index("--print-timeout") + 1] == "480s", argv
        assert argv[argv.index("--log-file") + 1], argv

        override_dir = tmp_path / "override"  # run.sh 的 fake repo 不能在同一目錄重建
        override_dir.mkdir()
        _run_agy_script(
            script,
            override_dir,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            extra_env={"AGY_PRINT_TIMEOUT_SECS": "30"},
        )
        argv = (override_dir / "stub-argv.txt").read_text(encoding="utf-8").splitlines()
        assert argv[argv.index("--print-timeout") + 1] == "30s", argv

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_014_non_integer_budget_rejected_before_agy(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-014: `8m` is agy's own syntax but not an integer second count; the
        elapsed-time check needs integers, so reject it instead of silently disabling it."""
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            extra_env={"AGY_PRINT_TIMEOUT_SECS": "8m"},
        )
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "[FAIL]" in result.stderr, result.stderr
        assert not (tmp_path / "stub-argv.txt").exists(), "agy must not run on a bad budget"
        assert not (tmp_path / "stub-help-called.txt").exists(), (
            "AC-5 says an invalid budget must not invoke agy at all — `agy --help` is an "
            "invocation, so the validation must precede the version preflight"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    @pytest.mark.parametrize(
        "budget",
        [
            "0",
            "571",  # one past the bound — pins the bound itself, not just far-away values
            "600",
            "900",
            # digit-only but past the shell's integer range: `[ "$v" -lt 1 ]` errors out with
            # "integer expression expected", and inside an `if` condition that error is not
            # caught by set -e, so BOTH comparisons fail, the condition is false, and the value
            # sails through to agy (measured: PASSED-THROUGH). Codex re-review Critical.
            "999999999999999999999999",
        ],
    )
    def test_agyrun_dt_016_out_of_range_budget_rejected_before_agy(
        self, script: Path, budget: str, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-016: the budget's bounds are enforced by code, not only by prose.

        A budget at or near the 600s Bash cap reproduces this PR's own incident shape — the
        harness kills the script before any `[FAIL]` can print, so the caller sees a bare
        timeout with no cause. `0` makes the elapsed comparison true for every answer. Both
        were accepted by DT-014's integer-only check, while the comment, the `[FAIL]` text and
        both SKILL.md files all claimed the limit existed.

        The bound is 570, not 599: the budget times agy's *internal* clock, so wall time adds
        its language-server boot (~2s measured), and 599 + boot would exceed the 600s cap —
        a value the script advertised as legal while guaranteeing the very failure it guards.
        `571` is parametrized so the bound itself is pinned; `570` is the positive control in
        DT-022 below.
        """
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            extra_env={"AGY_PRINT_TIMEOUT_SECS": budget},
        )
        assert result.returncode == 2, (budget, result.stdout, result.stderr)
        assert "[FAIL]" in result.stderr, result.stderr
        assert not (tmp_path / "stub-argv.txt").exists(), (
            f"budget {budget} reached agy; it must be rejected before the call"
        )
        assert not (tmp_path / "stub-help-called.txt").exists(), (
            f"budget {budget} reached `agy --help`; AC-5 requires no agy invocation at all, "
            "so validation must precede the version preflight"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_022_bound_value_itself_is_accepted(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-022: positive control for DT-016 — the bound itself must still run.

        Without this, tightening the guard to reject everything would pass DT-016 for the
        wrong reason. `570` is the documented maximum and must reach agy unchanged.
        """
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            extra_env={"AGY_PRINT_TIMEOUT_SECS": "570"},
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        argv = (tmp_path / "stub-argv.txt").read_text(encoding="utf-8").splitlines()
        assert argv[argv.index("--print-timeout") + 1] == "570s", argv

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_017_old_agy_named_as_the_cause(self, script: Path, tmp_path: Path) -> None:
        """AGYRUN-DT-017: an agy without the flags is told to upgrade, and agy is never asked
        to answer the prompt.

        Without this, deleting the whole preflight loop leaves the suite green — DT-014/016's
        `stub-help-called.txt` assertions are negatives, which deletion also satisfies.
        """
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            help_mode="missing_flags",
        )
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "--print-timeout" in result.stderr, result.stderr
        assert "1.1.28" in result.stderr, (
            "the message must name the version that introduced the flag, so the reader knows "
            f"what to upgrade to: {result.stderr!r}"
        )
        assert not (tmp_path / "stub-argv.txt").exists(), (
            "the prompt must never be sent to an agy that cannot honour --print-timeout"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_018_broken_help_is_not_blamed_on_the_version(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-018: `agy --help` failing for any other reason must not be reported as
        "your agy is too old".

        The preflight was written with `AGY_HELP=$(agy --help 2>&1 || true)`, which discards
        the status; a broken runtime then produces help text without the flags and the script
        confidently tells the user to upgrade — the wrong-actionable-reason shape the preflight
        exists to remove (rule 13, "`|| true` Turns a Real Result Into a Silent Skip", whose
        literal wrong example is `agy review ... || true`).
        """
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=0,
            agy_stdout="a genuine agy answer, ok",
            help_mode="fail",
        )
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "agy --help" in result.stderr and "exit 1" in result.stderr, result.stderr
        assert "ENOENT node" in result.stderr, (
            f"the real help output must be surfaced verbatim: {result.stderr!r}"
        )
        assert "1.1.28" not in result.stderr, (
            "a broken --help is not a version problem; naming an upgrade here is the "
            f"misdiagnosis this test exists to prevent: {result.stderr!r}"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    @pytest.mark.parametrize(
        ("case", "agy_exit", "agy_stdout", "expected_rc"),
        [
            ("agy 非零退出", 7, "", 7),
            ("agy 空輸出 exit 0", 0, "", 1),
        ],
        ids=["nonzero-exit", "empty-output"],
    )
    def test_agyrun_dt_019_quota_reported_at_every_failure_branch(
        self,
        script: Path,
        case: str,
        agy_exit: int,
        agy_stdout: str,
        expected_rc: int,
        tmp_path: Path,
    ) -> None:
        """AGYRUN-DT-019: the quota diagnosis fires on all three failure branches, not just
        the timeout one.

        "Quota exhausted -> agy returns nothing and exits" is a realistic shape, and there the
        empty-output branch's canned guidance blames sandbox permissions — an actionable reason
        that is simply wrong. Deleting `report_quota_if_any` from either of these two branches
        left the whole suite green (mutations M2 / M3).
        """
        result = _run_agy_script(
            script,
            tmp_path,
            agy_exit=agy_exit,
            agy_stdout=agy_stdout,
            agy_log=_QUOTA_LOG_LINE,
        )
        assert result.returncode == expected_rc, (case, result.stdout, result.stderr)
        assert _QUOTA_LOG_LINE.rstrip("\n") in result.stderr, (
            f"{case}: the quota line from agy's log must reach the caller here too, not only "
            f"on the timeout branch: {result.stderr!r}"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_021_sigterm_replays_agy_stderr_exactly_once(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-021: killing the script mid-run still hands agy's stderr to the caller,
        with the right signal exit code and no duplication.

        This is the commonest real failure — both SKILL.md files name "Bash tool timeout not
        set to 600000" as cause #1 — and buffering stderr to a temp file made it strictly worse
        than before the fix: measured, the caller got only the `[INFO]` line.

        What this pins, stated no more strongly than it is: **bash defers signal handling until
        the foreground child returns** (measured — SIGTERM at t=3s, the script exits only after
        the stub's sleep ends, and replays a line the stub wrote at t=10s). So the guarantee is
        "once agy returns, the caller that is still reading gets agy's stderr, exactly once,
        with the signal's exit code" — not "stderr appears the instant the kill lands". A
        harness that kills the whole process group, or sends SIGKILL, defeats both traps; that
        residual has no shell-level fix.

        Deleting `trap … TERM` does NOT fail this test: the EXIT trap independently covers the
        replay, so the signal traps are a redundant second layer (they matter only when the
        signal arrives while no foreground child is running, where bash does not defer).
        """
        marker = "[agy] exploring repository files..."
        # 10s, not 60: the stub outlives the script and holds the wrapper's inherited fds, so
        # the whole case costs its sleep. It only has to still be sleeping at t=3s.
        bin_dir = _make_stub_agy(
            tmp_path, exit_code=0, stdout="never reached", stderr=f"{marker}\n", sleep_secs=10
        )
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
        env.pop("AGY_MODEL", None)
        env.pop("AGY_PRINT_TIMEOUT_SECS", None)
        if script.name == "run.sh":
            args, cwd = ["review", "main", ""], _make_isolated_git_repo(tmp_path)
        else:
            (tmp_path / "agy-consult-question.txt").write_text("測試問題", encoding="utf-8")
            env["CLAUDE_JOB_DIR"] = str(tmp_path)
            args, cwd = [], REPO_ROOT

        # Signal from a shell wrapper rather than `Popen.send_signal`: the script must be a
        # background job whose parent then `wait`s for it, which is how a harness timeout
        # actually reaches it. Driving it straight from Python leaves bash deferring the trap
        # until its 60s foreground child returns, so the test would measure the harness, not
        # the script. stderr goes to a file because the stub outlives the script and would
        # hold a pipe open past its exit.
        err_file = tmp_path / "sigterm-stderr.txt"
        wrapper = (
            f"bash {script!s} {' '.join(args)} > /dev/null 2> {err_file!s} &\n"
            "pid=$!\n"
            "sleep 3\n"
            "kill -TERM $pid\n"
            "wait $pid\n"
        )
        result = subprocess.run(  # nosec B603
            ["bash", "-c", wrapper],
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
            cwd=cwd,
            check=False,
        )
        err = err_file.read_text(encoding="utf-8")

        assert result.returncode == 143, (result.returncode, err, result.stderr)
        assert err.count(marker) == 1, (
            f"agy's stderr must reach the caller exactly once on a kill (got {err.count(marker)} "
            f"occurrences): {err!r}"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_020_elapsed_comparison_is_strictly_greater(self, script: Path) -> None:
        """AGYRUN-DT-020: the elapsed check uses `-gt`, never `-ge`.

        Accepted Residual Risk #2 argues this explicitly: agy's own timer starts after its
        language server boots, so a real timeout always exceeds the budget, while `-ge` would
        discard a complete answer that happened to finish exactly on the budget second.
        Flipping the operator survived every execution-level test (mutation M1) because the
        cases sit far from the boundary, and a runtime boundary case would be flaky by
        construction (it depends on landing on an exact `SECONDS` tick) — so the decision is
        pinned statically instead.
        """
        src = _code_lines(script)
        assert '"$AGY_ELAPSED" -gt "$AGY_PRINT_TIMEOUT_SECS"' in src, (
            f"{script.name} must compare elapsed time with -gt"
        )
        assert '"$AGY_ELAPSED" -ge' not in src, (
            f"{script.name} uses -ge: a complete answer finishing on the budget second would "
            "be discarded as a timeout, contradicting Accepted Residual Risk #2"
        )

    @pytest.mark.parametrize("script", AGY_SCRIPTS, ids=lambda p: p.parent.parent.name)
    def test_agyrun_dt_015_agy_stderr_still_reaches_caller(
        self, script: Path, tmp_path: Path
    ) -> None:
        """AGYRUN-DT-015: capturing stderr for diagnosis must not swallow agy's own
        messages — e.g. its headless permission auto-deny explanation."""
        denial = "jetski: no output produced -- a tool required the command permission\n"
        result = _run_agy_script(script, tmp_path, agy_exit=0, agy_stdout="", agy_stderr=denial)
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert "jetski: no output produced" in result.stderr, result.stderr


def _skill_section(path: Path, heading_prefix: str) -> str:
    """Return the body of the first section whose heading starts with `heading_prefix`.

    The section ends at the next heading of the same or shallower depth, so a Step's body
    cannot bleed into the following Step (or into the FAQ).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    depth = heading_prefix.split(" ", 1)[0].count("#")
    body: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(heading_prefix):
            inside = True
            continue
        if inside and line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if 0 < hashes <= depth:
                break
        if inside:
            body.append(line)
    assert inside, f"{path.name} has no section starting with {heading_prefix!r}"
    return "\n".join(body)


class TestAgyReviewSkillDocContract:
    """The runbook's argument-parsing step must cover every invocation form the doc advertises.

    `run.sh` takes BASE as its second positional argument and `[FAIL]`s on an empty value, and
    the FAQ tells the reader to override it with `/agy-review base=develop`. The Step 1 parse
    table, however, listed only `review` / `challenge` + a free-form instruction -- so an agent
    following the table verbatim matched `base=develop` against the free-instruction row, passed
    it through as INSTRUCTION (`特別關注：base=develop` in the prompt), and left BASE at the
    Step 0d auto-detected branch. Result: the diff is taken against the wrong base and the
    review still completes, exit 0, no warning -- the documented-but-inert-flag failure this
    repo's authoring rules forbid. The gap predates the agy -> agy-review split; the rename
    carried it over unchanged, which is why it is pinned by a test rather than a re-read.
    """

    def test_agydoc_dt_001_run_sh_accepts_base_positional(self) -> None:
        """Precondition: the capability the doc promises actually exists in the script."""
        src = _code_lines(AGY_RUN_SH)
        assert 'BASE="${2:-main}"' in src, (
            "run.sh must take BASE as its second positional argument -- if this contract "
            "changed, AGYDOC-DT-002 is asserting against a capability that no longer exists"
        )

    def test_agydoc_dt_002_base_override_is_parsed_in_step_1(self) -> None:
        """AGYDOC-DT-002: `base=` must be parsed where the agent reads arguments, not only in
        the FAQ. Rule 11 "Decision Table and Prose Consistency": an agent executes by table
        row, so a form documented only in prose is silently unreachable."""
        doc = AGY_REVIEW_SKILL_MD.read_text(encoding="utf-8")
        assert "base=" in doc, (
            "precondition: SKILL.md advertises a base= override somewhere. If the override was "
            "deliberately dropped, remove it from every doc surface rather than deleting this test"
        )
        step_1 = _skill_section(AGY_REVIEW_SKILL_MD, "### Step 1")
        assert "base=" in step_1, (
            "Step 1 must state how to parse `base=<branch>` -- run.sh accepts it and the FAQ "
            "advertises it, so leaving it out of the parse table makes the documented override "
            "silently become part of INSTRUCTION while BASE stays auto-detected"
        )

    @pytest.mark.parametrize(
        "skill_md", [AGY_CONSULT_SKILL_MD, AGY_REVIEW_SKILL_MD], ids=lambda p: p.parent.name
    )
    def test_agydoc_dt_003_no_agy_auth_subcommand(self, skill_md: Path) -> None:
        """AGYDOC-DT-003: neither SKILL.md may tell the reader to run `agy auth`.

        agy has no `auth` subcommand -- `agy help auth` answers `Error: unknown subcommand:
        auth` and it is absent from `agy --help`'s subcommand list (probed on agy 1.2.3). Both
        files carried that instruction in two places each; following it does not complete OAuth
        and leaves the reader stuck on a command that does not exist. Pinned by a test because
        nothing else notices a doc regressing: reverting the fix left the whole suite green.

        The negated form ("agy 1.2.3 沒有 `auth` 子命令") and the probe command `agy help auth`
        are both fine -- only the literal imperative `agy auth` is banned.
        """
        text = skill_md.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "agy auth" in line.replace("agy help auth", "")
        ]
        assert not offenders, (
            f"{skill_md.parent.name}/SKILL.md still instructs `agy auth`, which does not exist: "
            f"{offenders}. Point the reader at plain `agy` (interactive browser OAuth) instead."
        )


class TestReleaseRollbackContract:
    def test_release_dt_001_rollback_reverts_plugin_json(self) -> None:
        """RELEASE-DT-001: the ERR trap reverts .claude-plugin/plugin.json too.

        Step 5 git-adds both package.json and plugin.json; reverting only the former leaves
        plugin.json holding the bumped version after a failed gate.
        """
        src = RELEASE_SH.read_text(encoding="utf-8")
        assert "git checkout -- 'plugins/*/.claude-plugin/plugin.json'" in src, (
            "rollback() must revert plugin.json, not just package.json"
        )

    def test_release_dt_002_rollback_covers_every_synced_path(self) -> None:
        """RELEASE-DT-002: every path sync_plugin_versions.py writes is reverted by rollback().

        Ties the trap to the sync script's actual glob list, so adding a third synced file
        without extending rollback() fails here rather than silently at release time.
        """
        sync_src = (REPO_ROOT / "scripts" / "sync_plugin_versions.py").read_text(encoding="utf-8")
        # Strip comments before matching: rollback()'s own explanatory comment names both paths,
        # so scanning raw source would pass on the comment alone even with the checkout line gone
        # (caught by mutation -- the first draft of this test was a no-op guard).
        rollback_region = _code_lines(RELEASE_SH).split("trap rollback ERR")[0]
        for synced in ("package.json", ".claude-plugin/plugin.json"):
            assert synced in sync_src, f"precondition: sync script writes {synced}"
            assert f"git checkout -- 'plugins/*/{synced}'" in rollback_region, (
                f"rollback() must revert {synced} -- sync_plugin_versions.py writes it"
            )
