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

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_SH = REPO_ROOT / "scripts" / "release-full.sh"
AGY_RUN_SH = REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-review" / "scripts" / "run.sh"
AGY_CONSULT_SH = (
    REPO_ROOT / "plugins" / "3rd-tools" / "skills" / "agy-consult" / "scripts" / "consult.sh"
)

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
