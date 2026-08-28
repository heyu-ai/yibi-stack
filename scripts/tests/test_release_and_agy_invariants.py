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

        Both scripts default `AGY_MODEL` to a Claude model because Gemini is blocked from
        this region on the standalone `-p` path. That default is the whole reason the
        announcement exists: without it a caller cannot tell whether an `/agy-consult` or
        `/agy-review` answer came from Gemini or from Claude, and counting a Claude answer
        as an independent cross-vendor voice in a mob consensus is a silent correctness
        failure (two votes from one family, presented as two families).

        Five documents now instruct readers to rely on this line — `pr-retro-hard`'s
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


def _make_stub_agy(tmp_path: Path, *, exit_code: int, stdout: str) -> Path:
    """Create a directory containing a stub `agy` executable for PATH injection."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    agy_stub = bin_dir / "agy"
    agy_stub.write_text(f"#!/usr/bin/env bash\nprintf '%s' {stdout!r}\nexit {exit_code}\n")
    agy_stub.chmod(0o755)
    return bin_dir


def _run_agy_script(
    script: Path, tmp_path: Path, *, agy_exit: int, agy_stdout: str
) -> subprocess.CompletedProcess[str]:
    """Run run.sh or consult.sh against a stub `agy`, handling each script's own calling
    convention (run.sh: positional mode/base/instruction args, invoked from the real repo so
    `git diff origin/<base>...HEAD` resolves; consult.sh: no args, reads
    $CLAUDE_JOB_DIR/agy-consult-question.txt)."""
    bin_dir = _make_stub_agy(tmp_path, exit_code=agy_exit, stdout=agy_stdout)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    if script.name == "run.sh":
        args: list[str] = ["review", "main", ""]
        cwd = REPO_ROOT
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
        assert "claude-sonnet-4-6" in result.stderr, (
            "the announcement must name the resolved model, not just say a model was used"
        )
        assert "[INFO]" not in result.stdout, (
            "the announcement must not reach stdout — the skills present stdout verbatim "
            "as the answer"
        )


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
