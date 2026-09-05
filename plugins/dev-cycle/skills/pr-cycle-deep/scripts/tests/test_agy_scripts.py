"""Tests for the agy shell scripts (agy-r1-stage1/-stage2, agy-r2).

Three layers:
  * Static contract tests — read each script's source and assert the issue #153
    invariants (inline prompt not @file, per-stage validator flags, scratch
    hygiene). These guard against silent regressions (e.g. someone reverting
    `-p "$CONTENT"` back to `-p "@file"`, or stage 2 gaining `--require-verdict`).
  * Runtime `--add-dir` contract — run every agy script against a stub `agy` that
    records its argv, and assert the value actually passed is absolute. Static text
    analysis cannot decide this (see `TestWorkspaceContextContract`), so the static
    layer is reduced to inventory for that invariant.
  * Behavioral integration test — run agy-r1-stage1.sh end-to-end in a throwaway
    git repo with a fake `agy` on PATH, exercising the inline call, the real
    agy_validate.py gate, and the 256KB size guard.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STAGE1 = SCRIPTS_DIR / "agy-r1-stage1.sh"
STAGE2 = SCRIPTS_DIR / "agy-r1-stage2.sh"
R2 = SCRIPTS_DIR / "agy-r2.sh"

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

# Every agy call site in the repo, as repo-relative paths. Asserted as an EXACT set rather
# than a `>=N` floor: a floor only catches the count falling (discovery broke) and is blind
# to it rising. Adding or removing an agy call site is a deliberate act, so updating this
# set — and `_RUNTIME_CASES` alongside it — is part of that act.
_EXPECTED_ADD_DIR_CALL_SITES = frozenset(
    {
        "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh",
        "plugins/3rd-tools/skills/agy-review/scripts/run.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r2.sh",
        "scripts/probe-agy-sandbox.sh",
    }
)


# --------------------------------------------------------------------------- #
# Static contract tests
# --------------------------------------------------------------------------- #


class TestInlinePromptContract:
    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_001_inline_not_at_file(self, script: Path) -> None:
        """AGYS-DT-001: agy is called with an inlined variable, never `-p "@..."`.

        The core issue #153 fix; a revert to @file would reintroduce the
        nested-worktree agentic failure.
        """
        src = script.read_text(encoding="utf-8")
        assert 'agy -p "$' in src, f"{script.name}: agy must inline the prompt var"
        assert '-p "@' not in src, f"{script.name}: agy must not use @file references"

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_002_scratch_hygiene_present(self, script: Path) -> None:
        """AGYS-DT-002: each script clears stale agy scratch input at start."""
        src = script.read_text(encoding="utf-8")
        assert "scratch/gemini-*-input.md" in src
        # must not silently swallow a real cleanup failure
        assert "2>/dev/null || true" not in src

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_003_print_timeout_raised(self, script: Path) -> None:
        """AGYS-DT-003: --print-timeout is raised to 10m."""
        assert "--print-timeout 10m" in script.read_text(encoding="utf-8")

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_007_inline_size_guard_present(self, script: Path) -> None:
        """AGYS-DT-007: every inlining script guards the 256000-byte argv limit.

        Stage 2 was missing this guard (Codex R2 P2) while stage1/R2 had it — a
        verbose R1 raw could otherwise hit 'argument list too long'.
        """
        src = script.read_text(encoding="utf-8")
        assert "256000" in src
        assert "wc -c <" in src

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_008_review_only_guard_and_edit_detection(self, script: Path) -> None:
        """AGYS-DT-008: write-capable scripts prepend a REVIEW-ONLY guard and detect
        out-of-band worktree edits (PR #194 retro: agy autonomously edited 6 files).

        Stage 1 / R2 run agy with the permission-bypass flag (needed for --add-dir
        read context), which also grants write access. The guard string + the
        PRE/POST git-status diff are the two defenses against a review voice editing
        the branch. A revert of either would silently reopen that hole.
        """
        src = script.read_text(encoding="utf-8")
        assert "REVIEW_ONLY_GUARD=" in src
        assert 'INPUT_CONTENT="$REVIEW_ONLY_GUARD' in src, (
            "guard must be prepended to the inlined prompt"
        )
        assert "PRE_TREE=$(git status --porcelain)" in src
        assert "POST_TREE=$(git status --porcelain)" in src
        assert 'if [ "$PRE_TREE" != "$POST_TREE" ]' in src


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


class TestWorkspaceContextContract:
    """`--add-dir` must receive an absolute path, never a relative one.

    agy 1.1.22 no longer resolves a relative `--add-dir .` into an active workspace, even
    when the caller has already `cd`-ed into that directory and the directory is listed in
    `~/.gemini/antigravity-cli/settings.json`'s `trustedWorkspaces`. The failure is the
    worst possible shape: agy exits 0 and returns a fully-formed answer produced with **no
    file context at all** — a 141-byte "there is no active workspace" refusal, or (observed)
    a fabricated number after admitting it has no workspace. No exit-code gate and no
    minimum-length guard can catch that.

    Measured with a negative control (agy 1.1.22): same question, same model, same flags,
    varying only the `--add-dir` argument —
      `--add-dir .`            -> CANNOT_READ (in a *trusted* repo)
      `--add-dir <abs path>`   -> correct answer (same trusted repo)
      `--add-dir <abs path>`   -> correct answer (an *untrusted* repo)
    so `trustedWorkspaces` is not the discriminating variable; the path form is.

    **Two layers, with the split chosen deliberately after a static-only version failed.**

    An earlier revision tried to prove absoluteness by parsing the shell source: a
    quote-state scanner plus a set of regexes deciding whether a `"$VAR"` was assigned from
    an "absoluteness-guaranteeing" source. Two independent frontier-model reviewers plus a
    local probe found five ways past it, each executing a relative `--add-dir` while the
    test stayed green: a `\\#` outside quotes truncating the line as a comment; a heredoc
    body supplying an acceptable token for a call site that had none; a composition
    (`X="$RELATIVE/sub"`) whose base was never checked; a later reassignment to `.`; and an
    unquoted `$VAR` argument. Patching those would invite a sixth — the property is a
    *runtime* one, and no amount of text matching decides it.

    So the layers are:

    * **Runtime (authoritative)** — `AGYS-DT-012` runs each script against a stub `agy` that
      records its argv, and asserts the value bash actually passed is absolute. Immune to
      every evasion above by construction: it reads what was executed, not what was written.
    * **Static (inventory only)** — `AGYS-DT-011` sweeps the repo for `--add-dir` call sites
      and asserts the set equals `_EXPECTED_ADD_DIR_CALL_SITES`. It deliberately makes **no**
      claim about absoluteness. Its job is to fail when a *new* call site appears, so that
      call site gets a runtime test rather than silently having none.
    """

    # --- static layer: discovery / inventory only, no correctness claim --------------- #

    @staticmethod
    def _invokes_agy(src: str) -> bool:
        """Does this script appear to invoke `agy` outside a whole-line comment?

        Keys on the **invocation**, not on `--add-dir`. Keying on the flag would miss the
        worst case: a new script that calls agy and forgets `--add-dir` entirely never
        enters the inventory, so nothing ever tests it — and running agy with no
        `--add-dir` is exactly the zero-file-context failure this whole guard is about.

        Intentionally a heuristic (`agy` followed by whitespace and a flag). This is a
        *discovery screen* for the inventory assertion, not a correctness check —
        correctness lives in the runtime test, so this may be approximate in a way the
        deleted absoluteness scanner must not have been. Measured against the tracked tree:
        this matches exactly the five agy scripts, whereas a bare word-match on `agy` also
        pulls in `commands/scripts/clean_wt.sh` and `scripts/assert_not_worktree.sh`, which
        only mention the word.
        """
        return any(
            re.search(r"(^|[^A-Za-z0-9_-])agy\s+-", line)
            for line in src.splitlines()
            if not line.lstrip().startswith("#")
        )

    @classmethod
    def _sweep_shell_scripts(cls) -> list[Path]:
        """Every `.sh` tracked by git, so the sweep cannot see untracked scratch trees.

        Asking git rather than walking the filesystem is what makes this machine-independent:
        an untracked checkout under `worktrees/`, `.worktrees/`, or any ignored scratch
        directory would otherwise be discovered as an "undeclared call site" and fail CI on
        one machine while passing on another.

        The trade-off, stated because it is this repo's own documented gotcha: a brand-new
        agy script is invisible here until it is `git add`-ed, so `make ci` can be green on
        an unstaged file that CI will later reject. That is the same shape as the
        "`git add` first, then `make ci`" note in CLAUDE.md — the narrower failure mode was
        chosen deliberately over a machine-dependent verdict.
        """
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(REPO_ROOT_DIR), "ls-files", "-z", "--", "*.sh"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            pytest.fail(f"git ls-files failed: {proc.stderr.strip()}")
        return [REPO_ROOT_DIR / rel for rel in proc.stdout.split("\0") if rel]

    def test_agys_dt_011_add_dir_call_site_inventory(self) -> None:
        """AGYS-DT-011: the set of `--add-dir` call sites is exactly the declared set.

        This is an inventory gate, not an absoluteness gate (see the class docstring). A new
        agy call site must be declared here **and** given a runtime case in `AGYS-DT-012` —
        `test_agys_dt_013_runtime_covers_every_call_site` asserts the two lists agree, so
        declaring one without testing it fails too.

        SKILL.md bash fences are covered separately by `scripts/lint_skill_bash.py`
        (issue #410), which detects relative `--add-dir` values in skill/command files while
        naturally excluding `.claude/rules/` counter-examples via its `MD_GLOBS` scope. This
        test continues to sweep `*.sh` only — the two checks are complementary.
        """
        actual = {
            str(path.relative_to(REPO_ROOT_DIR))
            for path in self._sweep_shell_scripts()
            if self._invokes_agy(path.read_text(encoding="utf-8"))
        }
        missing = _EXPECTED_ADD_DIR_CALL_SITES - actual
        unexpected = actual - _EXPECTED_ADD_DIR_CALL_SITES
        assert not missing, (
            f"declared --add-dir call sites not found: {sorted(missing)}. Either discovery "
            "broke, or the call site was removed on purpose — if removed deliberately, "
            "delete it from _EXPECTED_ADD_DIR_CALL_SITES and from _RUNTIME_CASES in the "
            "same commit."
        )
        assert not unexpected, (
            f"undeclared --add-dir call sites: {sorted(unexpected)}. A new agy call site "
            "needs an entry in _EXPECTED_ADD_DIR_CALL_SITES AND a runtime case in "
            "_RUNTIME_CASES — a call site with no runtime test has no absoluteness "
            "guarantee at all."
        )


# --------------------------------------------------------------------------- #
# Runtime --add-dir contract (authoritative)
# --------------------------------------------------------------------------- #

CONSULT_SH = PLUGINS_DIR / "3rd-tools/skills/agy-consult/scripts/consult.sh"
RUN_SH = PLUGINS_DIR / "3rd-tools/skills/agy-review/scripts/run.sh"
PROBE_SH = REPO_ROOT_DIR / "scripts/probe-agy-sandbox.sh"

# script -> positional args it needs. Every entry in _EXPECTED_ADD_DIR_CALL_SITES must
# appear here (AGYS-DT-013 asserts it), so a new agy call site cannot ship untested.
_RUNTIME_CASES: dict[str, tuple[Path, list[str]]] = {
    "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh": (CONSULT_SH, []),
    "plugins/3rd-tools/skills/agy-review/scripts/run.sh": (RUN_SH, ["review", "main", ""]),
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh": (STAGE1, []),
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh": (STAGE2, []),
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r2.sh": (R2, []),
    "scripts/probe-agy-sandbox.sh": (PROBE_SH, []),
}
_EXPECTED_SKILL_MODELS = {
    "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh": "gemini-3.8-flash-high",
    "plugins/3rd-tools/skills/agy-review/scripts/run.sh": "gemini-3.8-flash-high",
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh": "Gemini 3.8 Flash (High)",
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh": "Gemini 3.8 Flash (High)",
    "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r2.sh": "Gemini 3.8 Flash (High)",
}
_MODEL_PIN_EXEMPT_CALL_SITES = frozenset({"scripts/probe-agy-sandbox.sh"})


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

    def test_agys_dt_013_runtime_covers_every_call_site(self) -> None:
        """AGYS-DT-013: every call site has runtime coverage and a model disposition.

        Adding a call site must add both an execution recipe and either an expected skill
        model or an explicit non-skill exemption. This prevents a new skill-owned agy path
        from silently escaping the Gemini 3.8 Flash contract.
        """
        untested = sorted(_EXPECTED_ADD_DIR_CALL_SITES - set(_RUNTIME_CASES))
        undeclared = sorted(set(_RUNTIME_CASES) - _EXPECTED_ADD_DIR_CALL_SITES)
        assert not untested and not undeclared, (
            "every agy call site must have a runtime case: "
            f"declared but untested at runtime = {untested}; "
            f"runtime case for an undeclared site = {undeclared}"
        )
        model_dispositions = set(_EXPECTED_SKILL_MODELS) | _MODEL_PIN_EXEMPT_CALL_SITES
        assert model_dispositions == _EXPECTED_ADD_DIR_CALL_SITES, (
            "every agy call site must declare its expected model or explicit exemption: "
            f"missing={sorted(_EXPECTED_ADD_DIR_CALL_SITES - model_dispositions)}; "
            f"unknown={sorted(model_dispositions - _EXPECTED_ADD_DIR_CALL_SITES)}"
        )
        assert not set(_EXPECTED_SKILL_MODELS) & _MODEL_PIN_EXEMPT_CALL_SITES, (
            "a call site cannot require a model and be exempt simultaneously"
        )
        # Matching key sets is not enough: a copy-pasted Path constant would leave one
        # script with no runtime check while both sets still agree, which is precisely the
        # "declared but untested" hole this test exists to close.
        mismatched = {
            key: str(path)
            for key, (path, _) in _RUNTIME_CASES.items()
            if str(path.resolve().relative_to(REPO_ROOT_DIR)) != key
        }
        assert not mismatched, (
            f"_RUNTIME_CASES keys must name the script they run: {mismatched}. A key "
            "pointing at another script silently runs that script twice and leaves this "
            "one unchecked."
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
printf '%s\\0' "$@" >> "$AGY_FAKE_ARGV"
printf '\\1' >> "$AGY_FAKE_ARGV"
cat "$AGY_FAKE_OUTPUT"
"""

_ROGUE_AGY = """#!/usr/bin/env bash
# Fake agy that ALSO edits a tracked file mid-review (simulates the PR #194
# incident where agy autonomously modified the worktree during review).
printf '%s\\n' "$@" > "$AGY_FAKE_ARGV"
echo "rogue edit" >> seed.txt
cat "$AGY_FAKE_OUTPUT"
"""

_FAKE_AGY_SANDBOX_DENY = """#!/usr/bin/env bash
# Fake agy simulating sandbox auto-deny: exits 0 with empty stdout and a
# stderr message about the command permission being denied. This is the exact
# failure shape agy produces in headless -p mode when --sandbox is used and a
# tool requiring the "command" permission is needed but cannot be interactively
# approved. <!-- verified: probe, agy 1.1.12 -->
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
        """AGYS-ST-001: a good review passes; agy receives inline content, not @file."""
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")
        result = _run_stage1(stage1_env)
        assert result.returncode == 0, result.stderr

        review = Path(str(stage1_env["review"]))
        raw = (review / "gemini-r1-raw.md").read_text(encoding="utf-8")
        assert "race in tasks/foo/service.py" in raw

        argv = Path(str(stage1_env["argv_capture"])).read_text(encoding="utf-8")
        # the -p value is the inlined prompt content, not an @file reference
        assert "REVIEW PROMPT MARKER" in argv
        assert "@.pr-review" not in argv
        # negative control (pairs with AGYS-ST-004): a read-only agy must NOT trip the
        # out-of-band-edit detection. Locks specificity — git collapses the fully-untracked
        # .pr-review/ dir to one line, identical in PRE/POST, so no spurious WARN.
        assert "[WARN]" not in result.stderr

    def test_agys_st_002_wrong_target_review_fails(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-002: a review citing only foreign files is rejected (exit 1)."""
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

    def test_agys_st_004_out_of_band_edit_warns(self, stage1_env: dict[str, object]) -> None:
        """AGYS-ST-004: if agy edits a tracked file during review, stage1 emits a
        loud [WARN] but does NOT hard-fail (the review text is still useful).

        This is the PR #194 regression guard: with a rogue agy that mutates a
        tracked file, the PRE/POST git-status diff must detect it. Removing that
        detection from the script makes this test fail.
        """
        Path(str(stage1_env["fake_agy"])).write_text(_ROGUE_AGY, encoding="utf-8")
        Path(str(stage1_env["fake_agy"])).chmod(0o755)
        Path(str(stage1_env["out_file"])).write_text(GOOD_REVIEW, encoding="utf-8")

        result = _run_stage1(stage1_env)

        # review succeeded (WARN, not FAIL) and the detection fired
        assert result.returncode == 0, result.stderr
        assert "[WARN]" in result.stderr
        assert "seed.txt" in result.stderr
        # the rogue edit really landed (sanity: the fake agy did mutate the tree)
        assert "rogue edit" in (Path(str(stage1_env["repo"])) / "seed.txt").read_text(
            encoding="utf-8"
        )


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

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_014_review_scripts_use_skip_permissions(self, script: Path) -> None:
        """AGYS-DT-014: review stages use --dangerously-skip-permissions, NOT --sandbox.

        spec: agy-sandbox-permission-contract#review-flag-regressed-to-sandbox
        """
        invocation = _extract_agy_invocation_line(script.read_text(encoding="utf-8"))
        assert invocation, f"{script.name}: no agy invocation line found"
        assert "--dangerously-skip-permissions" in invocation, (
            f"{script.name}: review script MUST use --dangerously-skip-permissions "
            "(--sandbox auto-denies the command tool in headless mode)"
        )
        assert "--sandbox" not in invocation, (
            f"{script.name}: review script MUST NOT use --sandbox "
            "(command tool is needed for exploring surrounding code)"
        )

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

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_016_mutual_exclusion(self, script: Path) -> None:
        """AGYS-DT-016: no script contains both permission flags in its agy invocation.

        spec: agy-sandbox-permission-contract#mutual-exclusion-violated
        """
        invocation = _extract_agy_invocation_line(script.read_text(encoding="utf-8"))
        has_sandbox = "--sandbox" in invocation
        has_bypass = "--dangerously-skip-permissions" in invocation
        assert not (has_sandbox and has_bypass), (
            f"{script.name}: agy invocation contains BOTH --sandbox and "
            "--dangerously-skip-permissions — these are mutually exclusive"
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
