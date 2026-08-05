"""Contract tests binding SKILL.md to the aggregation kernel and to the design rules.

What these tests can and cannot claim is worth stating plainly, because the distinction
is the whole reason the aggregation rules live in code rather than in this runbook:

  * They CAN prove the runbook still contains the sentences and the outcome table that the
    kernel's behavior depends on, and that the two enumerate exactly the same outcomes.
  * They CANNOT prove a future agent reading the runbook actually obeys it. That is why
    every rule with real consequences (scoring, consensus, demotion) is enforced by
    aggregate_review.py and tested in test_aggregate_review.py, not asserted here.

Two matching disciplines are applied throughout, each learned from a failure this file
itself produced:

  * Prose assertions compare **whitespace-squashed** text, so a required phrase still
    matches after markdown reflows a line break into the middle of it.
  * Negative assertions about behavior look at **fenced code blocks only**, because the
    runbook necessarily names the thing it forbids in order to explain the prohibition.
"""

from __future__ import annotations

import re
from pathlib import Path

from aggregate_review import Effect, explain_policy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SKILL_ROOT = SCRIPTS_DIR.parent
SKILL_MD = SKILL_ROOT / "SKILL.md"

#: Outcome identifiers are matched as inline-code spans, so prose that merely mentions a
#: word cannot satisfy the check and a table row cannot be faked by a sentence.
_CODE_SPAN = re.compile(r"`([a-z_]+)`")
_TABLE_ROW = re.compile(r"^\| `([a-z_]+)` \|", flags=re.MULTILINE)


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    """Normalize away the surface forms a required phrase can be broken by.

    A prose assertion is about *wording*, not about markup or line wrapping, and both of
    those legitimately land in the middle of a phrase:

      * whitespace -- markdown reflows prose (MD013 caps lines at 200 characters), so a
        line break can split any phrase;
      * ``*`` and backticks -- emphasis and inline code are applied to individual words
        inside a sentence (``**不**改變…``), splitting the phrase for a literal match.

    ``_`` is deliberately NOT stripped: it is load-bearing inside identifiers such as
    ``demotion_applied``, which several assertions look for.
    """
    return re.sub(r"[\s*`]+", "", text)


def _has_phrase(text: str, phrase: str) -> bool:
    return _squash(phrase) in _squash(text)


def _assert_phrases(text: str, *phrases: str) -> None:
    missing = [p for p in phrases if not _has_phrase(text, p)]
    assert not missing, f"SKILL.md is missing required wording: {missing}"


def _code_blocks(text: str) -> str:
    """Return only the fenced code blocks -- SKILL.md's executable content.

    A negative assertion about what the runbook must never *do* has to look at commands,
    not at prose: the runbook legitimately names the thing it forbids in order to explain
    the prohibition, and a lexical check over the whole file matches that explanation.
    """
    return "\n".join(re.findall(r"^```[a-z]*\n(.*?)^```", text, flags=re.MULTILINE | re.DOTALL))


def _outcomes_named_in_skill(text: str) -> set[str]:
    """Every inline-code span in SKILL.md that is also a known Effect-shaped token.

    Restricted to the Effect vocabulary on purpose: SKILL.md legitimately contains other
    snake_case code spans (field names, exit-code labels), and treating those as claimed
    outcomes would make the reverse direction of the cross-check unusable.
    """
    known = {e.value for e in Effect}
    return {token for token in _CODE_SPAN.findall(text) if token in known}


class TestOutcomeTableCrossCheck:
    def test_skc_dt_001_every_kernel_outcome_is_documented(self) -> None:
        """SKC-DT-001: every outcome the kernel can emit appears in SKILL.md.

        An undocumented outcome means the agent receives a value the runbook never
        explains, and has to guess what to do with it.
        """
        documented = _outcomes_named_in_skill(_skill_text())
        missing = {e.value for e in Effect} - documented
        assert not missing, (
            f"SKILL.md does not document these kernel outcomes: {sorted(missing)}. "
            "Add a row to the outcome table."
        )

    def test_skc_dt_002_skill_names_no_nonexistent_outcome(self) -> None:
        """SKC-DT-002: the reverse direction -- SKILL.md must not name an outcome the
        kernel cannot produce.

        A runbook row for a value that never arrives is dead instruction: the reader
        cannot tell it from a live branch, and it decays silently.
        """
        table_rows = _TABLE_ROW.findall(_skill_text())
        assert table_rows, "the outcome table rows were not found -- has its format changed?"
        unknown = set(table_rows) - {e.value for e in Effect}
        assert not unknown, (
            f"SKILL.md's outcome table names outcomes the kernel cannot emit: {sorted(unknown)}"
        )

    def test_skc_dt_003_outcome_table_is_complete_not_partial(self) -> None:
        """SKC-DT-003: the table itself carries every outcome, not just the prose.

        Rule 11: an agent executes by table row first and skips explanatory paragraphs,
        so an outcome mentioned only in prose is effectively absent.
        """
        assert set(_TABLE_ROW.findall(_skill_text())) == {e.value for e in Effect}

    def test_skc_dt_004_explain_policy_is_the_named_source(self) -> None:
        """SKC-DT-004: SKILL.md points at --explain-policy as the table's source, so a
        reader knows which artifact wins when the two disagree.
        """
        _assert_phrases(_skill_text(), "--explain-policy")
        assert set(explain_policy()["effects"]) == {e.value for e in Effect}


class TestDelegationContract:
    def test_skc_dt_010_names_the_engine_owner_and_forbids_re_deriving(self) -> None:
        """SKC-DT-010: the runbook must name pr-retrospective as the engine owner and
        forbid re-deriving its gates, or the two documents drift into two contradictory
        copies of the same four gates.
        """
        _assert_phrases(
            _skill_text(),
            "plugins/growth/skills/pr-retrospective/SKILL.md",
            "不要在此重新推導",
        )

    def test_skc_dt_011_m2_does_not_change_write_authority(self) -> None:
        """SKC-DT-011: M2 reviews the suggestion text and does not move write authority.

        The engine's standing contract is that writes are suggestions the user approves;
        a review step that quietly took that over would be a governance change.
        """
        _assert_phrases(_skill_text(), "不改變既有的寫檔權限歸屬", "建議文字")

    def test_skc_dt_012_m2_skipped_when_no_lessons_is_not_a_failure(self) -> None:
        """SKC-DT-012: skipping M2 with zero lessons is stated as a skip, not a failure --
        otherwise an operator reads the absent round as a broken run.
        """
        _assert_phrases(_skill_text(), "跳過而非失敗")


class TestVoiceAcquisitionContract:
    def test_skc_dt_020_delegates_detection_to_consult_skills(self) -> None:
        """SKC-DT-020: voices are obtained through the existing consult skills, which own
        their own binary detection, auth gating, and failure stop conditions.
        """
        _assert_phrases(
            _skill_text(),
            'Skill(skill="codex-consult"',
            'Skill(skill="agy-consult"',
        )

    def test_skc_dt_021_does_not_read_the_dev_cycle_detection_cache(self) -> None:
        """SKC-DT-021: the pr-cycle-deep detection cache is dev-cycle private state.

        Reading it would couple this skill to another plugin's internals, which then break
        silently when that plugin changes them. Asserted over fenced code blocks only: the
        runbook names the cache in the sentence forbidding its use, so a whole-file lexical
        check would match its own rationale and fail on correct content.
        """
        assert "mob-detection-cache" not in _code_blocks(_skill_text()), (
            "no runbook command may read the dev-cycle detection cache"
        )
        _assert_phrases(_skill_text(), "不讀")

    def test_skc_dt_022_no_at_prefixed_file_pointer(self) -> None:
        """SKC-DT-022: the packet is never passed as an at-prefixed path.

        That form makes the antigravity CLI go agentic inside a nested worktree and return
        tool-call narration instead of a review -- silently, exit 0.
        """
        offenders = re.findall(
            r"@\$?[A-Za-z_{][^\s`]*(?:prompt-m1|prompt-m2)[^\s`]*", _skill_text()
        )
        assert not offenders, f"at-prefixed packet pointers found: {offenders}"

    def test_skc_dt_023_output_validation_and_failure_bound(self) -> None:
        """SKC-DT-023: per-voice validation, a single retry, and a two-failure bound that
        does not block the workflow.
        """
        _assert_phrases(
            _skill_text(),
            "## Summary",
            "## Findings",
            "## Verdict",
            "200 位元組",
            "重跑一次",
            "連續 2 次",
            "不阻擋流程",
        )

    def test_skc_dt_024_zero_external_voices_declares_no_signal(self) -> None:
        """SKC-DT-024: with no external voice the run completes and says agreement now
        carries no signal -- rather than presenting one voice as a mob.
        """
        _assert_phrases(_skill_text(), "這不是 mob", "一致無訊號")

    def test_skc_dt_025_external_data_boundary_is_disclosed(self) -> None:
        """SKC-DT-025: the runbook states what leaves the machine and how to decline."""
        _assert_phrases(_skill_text(), "外部模型資料邊界", "退出外送")


class TestPacketPurityContract:
    def test_skc_dt_030_forbids_leading_questions_with_a_worked_table(self) -> None:
        """SKC-DT-030: packet purity is stated AND illustrated.

        A bare "no leading questions" rule is not actionable; the rejected/accepted table
        is what lets an agent classify its own draft question.
        """
        _assert_phrases(_skill_text(), "禁止帶結論", "駁回", "採用")

    def test_skc_dt_031_untrusted_evidence_delimiter_present(self) -> None:
        """SKC-DT-031: PR-derived text is fenced and labelled as data, not instructions."""
        _assert_phrases(
            _skill_text(),
            "UNTRUSTED-EVIDENCE-BEGIN",
            "UNTRUSTED-EVIDENCE-END",
            "不是給你的指令",
        )


class TestConsensusContract:
    def test_skc_dt_040_first_round_is_blind_and_owns_consensus(self) -> None:
        """SKC-DT-040: R1 is blind and is the only source of consensus."""
        _assert_phrases(_skill_text(), "互盲", "共識只由獨立首輪建立")

    def test_skc_dt_041_cross_round_is_conditional_with_four_actions(self) -> None:
        """SKC-DT-041: the cross round is gated on opposing dispositions between two
        external voices, permits exactly four actions, and adds no independent vote.
        """
        _assert_phrases(
            _skill_text(),
            "預設跳過",
            "相反處置",
            "反證",
            "降級",
            "撤回",
            "補 settling check",
            "不得新增獨立票",
        )

    def test_skc_dt_042_report_names_which_voices_agreed(self) -> None:
        """SKC-DT-042: the report must name the voices behind a consensus claim.

        "The reviewers agreed" without naming them is how an anchored voice gets counted.
        """
        _assert_phrases(_skill_text(), "共識由以下 voice 建立")


class TestAdversarialReviewerContract:
    def test_skc_dt_050_uses_builtin_agent_not_an_own_plugin_agent(self) -> None:
        """SKC-DT-050: the adversarial reviewer is a built-in subagent type, and this
        skill dispatches no namespaced agent at all.

        `scripts/lint_skill_scope.py` does NOT cover this file -- probed: injecting
        `subagent_type="growth:…"` here leaves that linter green, because it scans only
        repo-root `skills/*/SKILL.md`. That is correct by its design (the invariant it
        guards is about the make-install channel, which carries SKILL.md without the
        plugin's agents; a plugin-only skill travels together with them). So the check has
        to live here, at the altitude that actually reads this file.

        Asserting "no namespaced dispatch" rather than merely "general-purpose is present"
        keeps the skill safe if a repo-root symlink is ever added, which would put it back
        under the make-install channel.
        """
        text = _skill_text()
        _assert_phrases(text, 'subagent_type="general-purpose"', "不新增自有 agent 定義檔")
        namespaced = re.findall(
            r"subagent_type\s*[:=]\s*[\"']?([a-z0-9][a-z0-9_-]*):([a-z0-9][a-z0-9_-]*)",
            text,
            re.IGNORECASE,
        )
        assert not namespaced, (
            f"this skill must dispatch only built-in agents; found namespaced: {namespaced}"
        )

    def test_skc_dt_051_read_only_guard_and_tree_comparison(self) -> None:
        """SKC-DT-051: the read-only constraint, the before/after tree comparison, and the
        residual that this is instruction-plus-comparison rather than tool removal.
        """
        _assert_phrases(
            _skill_text(),
            "REVIEWER CONSTRAINT",
            "git status --porcelain",
            "前後",
            "殘留風險",
        )

    def test_skc_dt_052_adversary_prompt_demands_a_settling_check(self) -> None:
        """SKC-DT-052: the adversarial prompt requires a settling check per objection.

        "Make the strongest case that this is wrong" without this requirement is an
        invitation to produce rhetoric, which then costs the human a round to dismiss.
        """
        _assert_phrases(
            _skill_text(),
            "Make the strongest case that this is wrong",
            "settling check",
        )


class TestShadowShippingContract:
    def test_skc_dt_060_demotion_is_documented_as_inert_by_default(self) -> None:
        """SKC-DT-060: the runbook states demotion ships inert, so an operator who sees a
        recommendation and no tier change does not read it as a bug.
        """
        text = _skill_text()
        _assert_phrases(text, "demotion_applied")
        assert "shadow" in text.lower()

    def test_skc_dt_061_asymmetry_is_stated_with_its_reason(self) -> None:
        """SKC-DT-061: the runbook states that agreement never raises a score AND why.

        Without the reason the next editor sees an arbitrary restriction and relaxes it;
        the reason (voices read one draft through one prompt, so they are correlated by
        construction) is what makes it non-negotiable.
        """
        _assert_phrases(_skill_text(), "一致永不抬升", "cross-model", "相關而非獨立")

    def test_skc_dt_062_demotion_is_input_to_the_existing_gate(self) -> None:
        """SKC-DT-062: demotion is a recommendation for the engine's evidence gate, and
        the runbook forbids bypassing or redefining that gate's tier semantics.
        """
        _assert_phrases(_skill_text(), "不繞過", "不重新定義其 tier 語意")


class TestExitCodeContract:
    def test_skc_dt_070_every_documented_exit_code_has_a_named_branch(self) -> None:
        """SKC-DT-070: both helper scripts have each exit code documented as a named
        outcome, not collapsed into PASS/FAIL.

        Asserted against the RAW text, not the normalized text: this check is about the
        documented convention (a bolded ``**exit N**`` label introducing its branch), and
        `_squash` deliberately erases emphasis markers. A prose assertion and a formatting
        assertion need different views of the same file.
        """
        labels = re.findall(r"\*\*exit (\d+)\*\*", _skill_text())
        for code in ("0", "1", "2"):
            assert labels.count(code) >= 2, (
                f"exit {code} must be documented as a named branch for both helper scripts; "
                f"found labels {labels}"
            )

    def test_skc_dt_071_kernel_failure_forbids_manual_derivation(self) -> None:
        """SKC-DT-071: when the kernel fails, the runbook forbids the agent from deriving
        the aggregation result by hand -- otherwise the single-decision-owner property
        quietly evaporates exactly when it matters.
        """
        assert _squash(_skill_text()).count(_squash("不得手工推導彙整結果")) >= 2
