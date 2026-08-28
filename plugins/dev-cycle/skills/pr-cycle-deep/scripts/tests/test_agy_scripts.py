"""Tests for the agy shell scripts (agy-r1-stage1/-stage2, agy-r2).

Two layers:
  * Static contract tests — read each script's source and assert the issue #153
    invariants (inline prompt not @file, per-stage validator flags, scratch
    hygiene). These guard against silent regressions (e.g. someone reverting
    `-p "$CONTENT"` back to `-p "@file"`, or stage 2 gaining `--require-verdict`).
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
# `tests` is parents[0], NOT parents[1] — an earlier revision of this comment put the
# second caret on `tests` while labelling it parents[1], which invites the reader to
# recount and land on parents[6] for `plugins`. That is the repo root, and a sweep rooted
# there descends into `.claude/worktrees/` (gitignored but present on disk, hundreds of
# .sh files across sibling branches), so the sweep would assert on other branches' copies.
# The exact-set assertion in AGYS-DT-011 catches that direction; the anchor below catches
# it sooner and names the cause.
REPO_ROOT_DIR = Path(__file__).resolve().parents[6]
PLUGINS_DIR = Path(__file__).resolve().parents[5]
assert PLUGINS_DIR.name == "plugins", PLUGINS_DIR
assert (REPO_ROOT_DIR / "pyproject.toml").is_file(), REPO_ROOT_DIR

# Directories the repo-wide sweep must never descend into. `.claude/worktrees` holds
# complete checkouts of other branches — sweeping them makes this test's result depend on
# which worktrees happen to exist on the machine.
_SWEEP_EXCLUDED = (".git", ".venv", "node_modules", "__pycache__")
_SWEEP_EXCLUDED_RELATIVE = (Path(".claude") / "worktrees",)

# Every agy `--add-dir` call site in the repo, as repo-relative paths. Asserted as an
# EXACT set rather than a `>=N` floor: a floor only catches discovery breaking (count
# falling), and the caret incident above is the count *rising*. Adding or removing an agy
# call site is a deliberate act, so updating this set is part of that act.
_EXPECTED_ADD_DIR_CALL_SITES = frozenset(
    {
        "plugins/3rd-tools/skills/agy-consult/scripts/consult.sh",
        "plugins/3rd-tools/skills/agy-review/scripts/run.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh",
        "plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r2.sh",
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

    @pytest.mark.parametrize("script", [STAGE1, R2])
    def test_agys_dt_008_review_model_pinned_to_gemini_pro(self, script: Path) -> None:
        """AGYS-DT-008: the review stages pin --model to a Gemini Pro tier.

        Two failure modes if the flag is dropped. (1) agy's auto-select resolves to
        Gemini 3.5 Flash, silently downgrading review depth. (2) `agy models` also offers
        Claude Sonnet/Opus -- an auto-selected Claude would put this voice in the same
        family as the Claude lead, collapsing the cross-family premise the whole mob review
        rests on, with no warning anywhere. Asserting the Gemini prefix (not the full string)
        keeps a Low/High effort swap from failing the test while still catching a
        cross-family drift.
        """
        src = script.read_text(encoding="utf-8")
        assert "--model 'Gemini" in src, (
            f"{script.name}: agy must pin --model to a Gemini tier "
            "(auto-select can pick Claude and break cross-family review)"
        )

    def test_agys_dt_009_extract_stage_not_pinned(self) -> None:
        """AGYS-DT-009: the extract stage does NOT pin a model.

        Stage 2 turns stage 1's raw markdown into JSON -- no reasoning -- and the script's
        own comment says agy auto-picks a lightweight model there to preserve
        high-reasoning quota. Pinning Pro here would spend that quota on a mechanical
        transform; this test makes the asymmetry explicit rather than incidental.
        """
        assert "--model" not in STAGE2.read_text(encoding="utf-8"), (
            "extract stage must leave model auto-selection alone (lightweight by design)"
        )

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
    """`--add-dir` must receive an absolute path, never a relative `.`.

    agy 1.1.22 no longer resolves a relative `--add-dir .` into an active
    workspace, even when the caller has already `cd`-ed into that directory and
    the directory is listed in `~/.gemini/antigravity-cli/settings.json`'s
    `trustedWorkspaces`. The failure is the worst possible shape: agy exits 0 and
    returns a fully-formed answer produced with **no file context at all** — a
    141-byte "there is no active workspace" refusal, or (observed) a fabricated
    number after admitting it has no workspace. No exit-code gate and no
    minimum-length guard can catch that, so the invariant has to be pinned here.

    Measured with a negative control (agy 1.1.22): same question, same model,
    same flags, varying only the `--add-dir` argument —
      `--add-dir .`            -> CANNOT_READ (in a *trusted* repo)
      `--add-dir <abs path>`   -> correct answer (same trusted repo)
      `--add-dir <abs path>`   -> correct answer (an *untrusted* repo)
    so `trustedWorkspaces` is not the discriminating variable; the path form is.
    """

    @staticmethod
    def _scan_line(line: str) -> tuple[str, list[bool]]:
        """Split a shell line into (code, quoted-mask), cutting an unquoted comment.

        Returns the line truncated at the first `#` that is outside quotes, plus a mask
        where `mask[i]` is True when index `i` of that code sits inside quotes. Content is
        preserved verbatim — the mask, not blanking, is what lets the caller demand that
        the `--add-dir` *flag token* be outside quotes while its *value* may be quoted
        (`--add-dir "$WT_ROOT"`).

        Two failure shapes motivate each half:
          * skipping only whole-line comments lets an inline trailing comment *supply* the
            token that satisfies the check while the real command has no `--add-dir` at all
            → hence the unquoted-`#` cut;
          * a plain `line.split("#")` corrupts a `#` inside a quoted string, and a
            diagnostic `echo "never pass --add-dir . to agy"` would otherwise be reported
            as a violation of a correct call site → hence the quote tracking.

        Backslash escapes are honoured inside double quotes only, matching bash (rule 13's
        "Single-Quote Semantics" note: a backslash inside single quotes is literal).
        """
        code: list[str] = []
        quoted: list[bool] = []
        in_single = in_double = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "\\" and in_double and i + 1 < len(line):
                code.append(ch)
                quoted.append(True)
                code.append(line[i + 1])
                quoted.append(True)
                i += 2
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                code.append(ch)
                quoted.append(True)
            elif ch == '"' and not in_single:
                in_double = not in_double
                code.append(ch)
                quoted.append(True)
            elif ch == "#" and not in_single and not in_double:
                break
            else:
                code.append(ch)
                quoted.append(in_single or in_double)
            i += 1
        return "".join(code), quoted

    @classmethod
    def _add_dir_args(cls, src: str) -> list[str]:
        """Every `--add-dir` argument whose flag token sits in executable code.

        Both agy argument spellings are recognised. agy's flag parser is the Go one
        (`flag needs an argument: -print`), which accepts `--flag=value` as well as
        `--flag value`; matching only the whitespace form left the `=` spelling completely
        invisible to this sweep, so a script whose only call site used it was silently
        dropped from the results rather than flagged.
        """
        args: list[str] = []
        for raw_line in src.splitlines():
            code, quoted = cls._scan_line(raw_line)
            if "--add-dir" not in code:
                continue
            for match in re.finditer(r"--add-dir(?:=|\s+)(\S+)", code):
                if quoted[match.start()]:
                    continue  # the flag itself is inside a string, not an invocation
                args.append(match.group(1))
        return args

    @staticmethod
    def _assigns_absolute(src: str, var: str) -> bool:
        """Does `src` assign `var` from a source that guarantees an absolute path?

        `startswith('"$')` alone is a *spelling* check: `SCRATCH="."` followed by
        `--add-dir "$SCRATCH"` passes it while losing all file context at runtime. The
        accepted sources are the two this repo actually uses to obtain a root, plus a
        composition on an already-verified absolute variable.
        """
        patterns = (
            # WT_ROOT=$(git rev-parse --show-toplevel)  — also the `if ! WT_ROOT=$(...)` form
            rf"{re.escape(var)}=\$\(\s*git rev-parse[^)]*--show-toplevel[^)]*\)",
            # SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
            # `.*?` rather than `[^)]*`: the canonical form nests `$(dirname "$0")`, whose
            # inner `)` stops any negated-paren class before it reaches `&& pwd`. Without
            # DOTALL this still cannot cross a newline, so it stays anchored to one
            # assignment. (This exact form is what AGYS-DT-006 pins, so rejecting it would
            # be a false positive against the repo's own convention.)
            rf"{re.escape(var)}=\$\(\s*cd\b.*?&&\s*pwd",
            # REVIEW_DIR="$WT_ROOT/.pr-review"  — composed on another variable
            rf'{re.escape(var)}="\$\{{?[A-Za-z_][A-Za-z0-9_]*\}}?/',
            # literal absolute
            rf'{re.escape(var)}="?/',
        )
        return any(re.search(p, src) for p in patterns)

    @classmethod
    def _assert_absolute(cls, script: Path) -> None:
        src = script.read_text(encoding="utf-8")
        found = cls._add_dir_args(src)
        assert found, (
            f"{script.name}: no --add-dir found in executable code. agy 1.1.22 runs with "
            "NO file context when the flag is absent and still exits 0, so an agy "
            "invocation without it is the very defect this test exists to catch. (A "
            "trailing comment mentioning --add-dir no longer counts.)"
        )
        for arg in found:
            unquoted = arg.strip("'\"")
            if unquoted.startswith("/"):
                continue
            var_match = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", unquoted)
            assert var_match, (
                f"{script.name}: --add-dir got {arg!r}; agy 1.1.22 silently loses all "
                "file context on a relative path and still exits 0. Pass an absolute "
                'path or a quoted absolute variable (e.g. --add-dir "$WT_ROOT").'
            )
            var = var_match.group(1)
            assert cls._assigns_absolute(src, var), (
                f"{script.name}: --add-dir got {arg!r}, but {var} is not assigned from an "
                "absoluteness-guaranteeing source in this file (git rev-parse "
                "--show-toplevel, cd+pwd, a composition on another absolute variable, or "
                "a literal absolute path). A quoted variable holding a relative value "
                "passes a spelling check while still losing all file context at runtime."
            )

    @pytest.mark.parametrize("script", [STAGE1, STAGE2, R2])
    def test_agys_dt_010_add_dir_absolute(self, script: Path) -> None:
        """AGYS-DT-010: pr-cycle-deep's agy stages pass an absolute --add-dir."""
        self._assert_absolute(script)

    @classmethod
    def _sweep_shell_scripts(cls) -> list[Path]:
        """Every `.sh` in the repo except vendored / per-branch / cache trees."""
        keep: list[Path] = []
        for path in REPO_ROOT_DIR.rglob("*.sh"):
            rel = path.relative_to(REPO_ROOT_DIR)
            if any(part in _SWEEP_EXCLUDED for part in rel.parts):
                continue
            if any(rel.is_relative_to(excluded) for excluded in _SWEEP_EXCLUDED_RELATIVE):
                continue
            keep.append(path)
        return keep

    def test_agys_dt_011_add_dir_absolute_repo_wide(self) -> None:
        """AGYS-DT-011: no shell script in the repo passes a relative --add-dir.

        Rooted at the repo, not at `plugins/`: the same defect shipped in five scripts
        across two plugins, and a `plugins/`-only sweep leaves every `.sh` under
        `scripts/`, `commands/scripts/` and `.claude/hooks/` unguarded — exactly the
        recurrence path this test exists to close. `.claude/worktrees/` is excluded
        because it holds complete checkouts of other branches, which would make this
        test's verdict depend on which worktrees happen to exist locally.

        `rglob` does not follow symlinks (rule 02). That is correct here rather than
        merely tolerable: the real files live under `plugins/`, and the top-level
        `skills/` entries are symlinks into it, so nothing is missed and nothing is
        counted twice.

        Known gap, stated so it can be re-probed rather than assumed closed: this sweeps
        `*.sh` only. A `--add-dir` inside a SKILL.md bash fence is a live execution path
        in this repo (CLAUDE.md: "slash command bash code block rewritten by agent") and
        is NOT covered here — scanning `*.md` would also match the deliberate "Wrong:"
        examples in `.claude/rules/13-bash-anti-patterns.md`, so distinguishing live
        commands from counter-examples belongs in `scripts/lint_skill_bash.py`, which
        already owns SKILL.md bash blocks. Tracked as a follow-up.
        """
        discovered = {
            path: args
            for path in self._sweep_shell_scripts()
            if (args := self._add_dir_args(path.read_text(encoding="utf-8")))
        }
        actual = {str(path.relative_to(REPO_ROOT_DIR)) for path in discovered}
        # Exact set, not a `>=N` floor. A floor only catches the count falling
        # (discovery broke); it cannot catch the count rising, which is what happens
        # when the sweep root drifts upward and starts eating sibling worktrees.
        missing = _EXPECTED_ADD_DIR_CALL_SITES - actual
        unexpected = actual - _EXPECTED_ADD_DIR_CALL_SITES
        assert not missing, (
            f"expected --add-dir call sites not discovered: {sorted(missing)}. Either "
            "discovery broke (check _code_part / the regex) or the call site was removed "
            "on purpose — if removed deliberately, delete it from "
            "_EXPECTED_ADD_DIR_CALL_SITES in the same commit."
        )
        assert not unexpected, (
            f"undeclared --add-dir call sites discovered: {sorted(unexpected)}. If this "
            "is a legitimate new agy call site, add it to _EXPECTED_ADD_DIR_CALL_SITES. "
            "If these are paths outside the repo's own tree, the sweep root drifted — "
            f"REPO_ROOT_DIR is {REPO_ROOT_DIR}."
        )
        for path in discovered:
            self._assert_absolute(path)


# --------------------------------------------------------------------------- #
# Behavioral integration test (stage 1)
# --------------------------------------------------------------------------- #

_FAKE_AGY = """#!/usr/bin/env bash
# Fake agy: record argv, then emit the canned review on stdout.
printf '%s\\n' "$@" > "$AGY_FAKE_ARGV"
cat "$AGY_FAKE_OUTPUT"
"""

_ROGUE_AGY = """#!/usr/bin/env bash
# Fake agy that ALSO edits a tracked file mid-review (simulates the PR #194
# incident where agy autonomously modified the worktree during review).
printf '%s\\n' "$@" > "$AGY_FAKE_ARGV"
echo "rogue edit" >> seed.txt
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
