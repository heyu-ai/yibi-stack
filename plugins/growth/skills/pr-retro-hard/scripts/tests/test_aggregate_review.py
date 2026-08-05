"""Property and contract tests for aggregate_review.py.

The kernel is a pure function, so every rule below is deterministic given a finding set.
That is the whole point of lifting the aggregation rules out of runbook prose: prose can
only be asserted to still *contain* a sentence, never to have been *obeyed*.

Test classes map one-to-one onto the change's task groups, so each task has a named
verification target:

  * TestFindingContract              -- task 2.1, the data contract
  * TestScoringMonotonicity          -- task 2.2, agreement never raises a score
  * TestPresentationInvariants       -- task 2.3, adversarial / no-check / draft preservation
  * TestDemotionGatedOnConfirmedCheck -- task 2.4, demotion needs executed evidence
  * TestInputHygiene                 -- task 2.5, staleness / permutation / idempotence
  * TestShadowFlag                   -- task 2.6, recommendations inert until enabled
"""

from __future__ import annotations

import copy
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest
from aggregate_review import (
    CheckState,
    Classification,
    Effect,
    MalformedInput,
    Round,
    Source,
    VoiceKind,
    aggregate,
    explain_policy,
    parse_input,
    result_to_dict,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
KERNEL = SCRIPTS_DIR / "aggregate_review.py"
SCHEMA = SCRIPTS_DIR.parent / "schemas" / "review-finding.schema.json"

DIGEST = "draft-digest-aaa"


def _finding(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "f1",
        "voice": "codex",
        "voice_kind": VoiceKind.EXTERNAL.value,
        "round": Round.R1.value,
        "target": "lesson-bash-quoting",
        "classification": Classification.OVERCLAIMED.value,
        "settling_check": "rg -n 'pattern' path/",
        "statement": "The cited evidence covers only macOS bash 3.2.",
        "draft_digest": DIGEST,
        "check_state": CheckState.CONFIRMED.value,
    }
    base.update(overrides)
    return base


def _payload(findings: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": "1.0",
        "draft_digest": DIGEST,
        "packet_digest": "packet-digest-bbb",
        "original_confidence": 5,
        "original_source": Source.INFERRED.value,
        "findings": findings,
    }
    base.update(overrides)
    return base


def _run(findings: list[dict[str, Any]], **overrides: Any):
    return aggregate(parse_input(_payload(findings, **overrides)))


def _effect_of(result: Any, finding_id: str) -> str:
    for outcome in result.outcomes:
        if outcome.finding_id == finding_id:
            return outcome.effect
    raise AssertionError(f"finding {finding_id!r} missing from outcomes")


# --------------------------------------------------------------------------- #
# task 2.1 -- the data contract
# --------------------------------------------------------------------------- #


class TestFindingContract:
    def test_agg_dt_001_unknown_classification_rejected(self) -> None:
        """AGG-DT-001: a classification outside the closed enumeration is a hard error
        naming the offending finding -- never a defaulted value.
        """
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([_finding(classification="PROBABLY-FINE")]))
        message = str(exc.value)
        assert "f1" in message, f"error must name the offending finding: {message}"
        assert "PROBABLY-FINE" in message

    def test_agg_dt_002_missing_target_rejected(self) -> None:
        """AGG-DT-002: a finding without a target is rejected, naming the finding."""
        bad = _finding()
        del bad["target"]
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        assert "target" in str(exc.value)
        assert "f1" in str(exc.value)

    def test_agg_dt_003_missing_statement_rejected(self) -> None:
        """AGG-DT-003: a finding without a statement is rejected, naming the finding."""
        bad = _finding()
        del bad["statement"]
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        assert "statement" in str(exc.value)
        assert "f1" in str(exc.value)

    def test_agg_dt_004_unable_to_execute_is_not_refuted(self) -> None:
        """AGG-DT-004: the five settling-check states stay distinct.

        Collapsing `unable_to_execute` into `refuted` would turn "we could not get
        evidence" into "the claim is false" -- the exact conflation the existing
        evidence gate already forbids.
        """
        assert CheckState.UNABLE_TO_EXECUTE is not CheckState.REFUTED
        assert len({s.value for s in CheckState}) == 5

        unable = _run([_finding(check_state=CheckState.UNABLE_TO_EXECUTE.value)])
        refuted = _run([_finding(check_state=CheckState.REFUTED.value)])
        # Neither produces a recommendation, but they must remain separately reported.
        assert unable.demotion_recommendations == []
        assert refuted.demotion_recommendations == []
        assert unable.outcomes[0].check_state is CheckState.UNABLE_TO_EXECUTE
        assert refuted.outcomes[0].check_state is CheckState.REFUTED

    def test_agg_dt_005_duplicate_finding_id_rejected(self) -> None:
        """AGG-DT-005: duplicate ids are rejected rather than silently deduplicated --
        a silent dedup would drop a real voice's finding.
        """
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([_finding(id="f1"), _finding(id="f1", voice="agy")]))
        assert "f1" in str(exc.value)

    def test_agg_dt_006_schema_enumerations_match_the_kernel(self) -> None:
        """AGG-DT-006: the shipped JSON schema and the kernel enumerate the same values.

        Two files describing one contract drift silently; this binds them. The kernel is
        the decision owner, so the schema is checked against it, not the reverse.
        """
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["$defs"]["finding"]["properties"]
        assert set(props["classification"]["enum"]) == {c.value for c in Classification}
        assert set(props["check_state"]["enum"]) == {s.value for s in CheckState}
        assert set(props["voice_kind"]["enum"]) == {k.value for k in VoiceKind}
        assert set(props["round"]["enum"]) == {r.value for r in Round}
        assert set(schema["properties"]["original_source"]["enum"]) == {s.value for s in Source}

    def test_agg_dt_007_unreadable_input_exits_one(self) -> None:
        """AGG-DT-007: a runtime failure (input file absent) exits 1."""
        proc = subprocess.run(  # nosec B603
            [sys.executable, str(KERNEL), "--input", "/nonexistent/path.json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 1, proc.stderr
        assert "[FAIL]" in proc.stderr

    def test_agg_dt_008_contract_violation_exits_two(self, tmp_path: Path) -> None:
        """AGG-DT-008: a contract violation exits 2, distinctly from a runtime failure.

        Collapsing the two would leave a caller unable to tell "your input is wrong"
        (fix the packet) from "I could not run" (fix the environment).
        """
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{not valid json", encoding="utf-8")
        proc = subprocess.run(  # nosec B603
            [sys.executable, str(KERNEL), "--input", str(bad_json)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 2, proc.stderr
        assert "[FAIL]" in proc.stderr

        unknown_enum = tmp_path / "unknown.json"
        unknown_enum.write_text(
            json.dumps(_payload([_finding(classification="NOPE")])), encoding="utf-8"
        )
        proc2 = subprocess.run(  # nosec B603
            [sys.executable, str(KERNEL), "--input", str(unknown_enum)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc2.returncode == 2, proc2.stderr
        assert "NOPE" in proc2.stderr, "the error must name the offending value"


# --------------------------------------------------------------------------- #
# task 2.2 -- agreement never raises a score
# --------------------------------------------------------------------------- #


class TestScoringMonotonicity:
    @pytest.mark.parametrize(
        ("confidence_in", "source_in", "findings", "confidence_out", "source_out"),
        [
            pytest.param(5, Source.INFERRED, [], 5, Source.INFERRED, id="no-findings"),
            pytest.param(
                5,
                Source.INFERRED,
                [_finding(classification=Classification.AGREE.value)],
                5,
                Source.INFERRED,
                id="one-agreement",
            ),
            pytest.param(
                5,
                Source.INFERRED,
                [
                    _finding(id="f1", voice="codex", classification=Classification.AGREE.value),
                    _finding(id="f2", voice="agy", classification=Classification.AGREE.value),
                    _finding(id="f3", voice="claude", classification=Classification.AGREE.value),
                ],
                5,
                Source.INFERRED,
                id="three-agreements",
            ),
            pytest.param(
                5,
                Source.INFERRED,
                [_finding(classification=Classification.OVERCLAIMED.value)],
                4,
                Source.INFERRED,
                id="one-overclaim-dissent-lowers",
            ),
            pytest.param(
                9,
                Source.USER_STATED,
                [_finding(classification=Classification.OVERCLAIMED.value)],
                9,
                Source.USER_STATED,
                id="user-stated-is-not-downgraded",
            ),
        ],
    )
    def test_agg_dt_010_monotonicity_table(
        self,
        confidence_in: int,
        source_in: Source,
        findings: list[dict[str, Any]],
        confidence_out: int,
        source_out: Source,
    ) -> None:
        """AGG-DT-010: the spec's monotonicity table, one parameterised case per row."""
        result = _run(
            copy.deepcopy(findings),
            original_confidence=confidence_in,
            original_source=source_in.value,
        )
        assert result.confidence == confidence_out
        assert result.source is source_out

    def test_agg_dt_011_adding_agreement_changes_nothing(self) -> None:
        """AGG-DT-011: positive control for the asymmetry -- piling on agreement is a
        no-op, so mob consensus can never inflate a lesson's confidence.

        Without this the kernel could treat cross-voice agreement as cross-model
        evidence and lift every retro lesson from inferred (5-6) to cross-model (8),
        systematically corrupting the downstream distillation clusters.
        """
        baseline = _run([])
        piled = _run(
            [
                _finding(id=f"f{n}", voice=f"voice{n}", classification=Classification.AGREE.value)
                for n in range(1, 6)
            ]
        )
        assert piled.confidence == baseline.confidence
        assert piled.source is baseline.source
        assert piled.demotion_recommendations == []

    def test_agg_dt_012_source_is_never_rewritten_to_cross_model(self) -> None:
        """AGG-DT-012: no finding combination rewrites source to cross-model."""
        result = _run(
            [
                _finding(id="f1", voice="codex", classification=Classification.UNSUPPORTED.value),
                _finding(id="f2", voice="agy", classification=Classification.UNSUPPORTED.value),
            ]
        )
        assert result.source is Source.INFERRED

    def test_agg_dt_014_agree_never_reaches_a_consensus_bearing_effect(self) -> None:
        """AGG-DT-014: an AGREE finding never receives an effect that carries weight.

        This asserts directly the invariant that used to be encoded twice -- once in the
        AGREE branch and again as a downstream `is_dissent` guard. The duplicate guard
        *masked* mutations that removed the branch, so the branch's absence went
        undetected. One mechanism plus this assertion is strictly stronger than two
        mutually-shadowing predicates.
        """
        for voice_kind in (VoiceKind.EXTERNAL, VoiceKind.ADVERSARIAL):
            for state in CheckState:
                result = _run(
                    [
                        _finding(
                            classification=Classification.AGREE.value,
                            voice_kind=voice_kind.value,
                            check_state=state.value,
                        )
                    ]
                )
                effect = _effect_of(result, "f1")
                assert effect == Effect.RECORDED_ONLY.value, (
                    f"AGREE with {voice_kind}/{state} became {effect}"
                )
                assert result.consensus == {}, "AGREE must never establish consensus"
                assert result.confidence == 5, "AGREE must never move the score"

    def test_agg_dt_013_confidence_never_drops_below_one(self) -> None:
        """AGG-DT-013: the confidence floor holds even with more dissenting voices than
        confidence points.
        """
        result = _run(
            [
                _finding(
                    id=f"f{n}", voice=f"voice{n}", classification=Classification.UNSUPPORTED.value
                )
                for n in range(1, 9)
            ],
            original_confidence=2,
        )
        assert result.confidence == 1


# --------------------------------------------------------------------------- #
# task 2.3 -- presentation invariants
# --------------------------------------------------------------------------- #


class TestPresentationInvariants:
    def test_agg_dt_020_adversarial_never_counts_toward_consensus(self) -> None:
        """AGG-DT-020: an adversarial finding is reported but never tallied.

        "Make the strongest case that this is wrong" is one-sided by construction, so
        counting it as a vote would let a manufactured objection reach consensus.
        """
        result = _run(
            [
                _finding(
                    id="adv",
                    voice="claude-adversary",
                    voice_kind=VoiceKind.ADVERSARIAL.value,
                    classification=Classification.UNSUPPORTED.value,
                )
            ]
        )
        assert result.consensus == {}, "adversarial findings must not establish consensus"
        assert _effect_of(result, "adv") == Effect.ADVERSARIAL_HYPOTHESIS.value
        assert result.demotion_recommendations == []

    def test_agg_dt_021_adversarial_without_check_is_non_actionable(self) -> None:
        """AGG-DT-021: `(none)` is a valid parsed value; for the adversarial voice it
        yields non-actionable commentary that is still presented to the human.
        """
        result = _run(
            [
                _finding(
                    id="adv",
                    voice_kind=VoiceKind.ADVERSARIAL.value,
                    settling_check="(none)",
                    classification=Classification.CONTRADICTED.value,
                )
            ]
        )
        assert _effect_of(result, "adv") == Effect.NON_ACTIONABLE_COMMENTARY.value
        assert result.confidence == 5, "commentary must not move the score"
        assert result.demotion_recommendations == []
        assert any(o.finding_id == "adv" for o in result.outcomes), "must still be presented"

    def test_agg_dt_022_external_without_check_caps_at_unresolved(self) -> None:
        """AGG-DT-022: an external finding with no settling check is capped at unresolved
        and produces no demotion recommendation.
        """
        result = _run(
            [
                _finding(
                    settling_check="(none)",
                    classification=Classification.UNSUPPORTED.value,
                    check_state=CheckState.CONFIRMED.value,
                )
            ]
        )
        assert _effect_of(result, "f1") == Effect.UNRESOLVED.value
        assert result.demotion_recommendations == []
        assert result.confidence == 5, "an unresolved finding must not lower the score"

    def test_agg_dt_023_every_finding_appears_in_the_output(self) -> None:
        """AGG-DT-023: aggregation annotates, it never removes. Every supplied finding
        has exactly one outcome, whatever its effect.
        """
        findings = [
            _finding(id="f1", voice="codex"),
            _finding(id="f2", voice="agy", settling_check="(none)"),
            _finding(id="f3", voice="claude-adversary", voice_kind=VoiceKind.ADVERSARIAL.value),
            _finding(id="f4", voice="codex", classification=Classification.AGREE.value),
            _finding(id="f5", voice="ghost", draft_digest="some-older-digest"),
        ]
        result = _run(findings)
        assert len(result.outcomes) == len(findings), "one outcome per supplied finding"
        assert {o.finding_id for o in result.outcomes} == {f["id"] for f in findings}
        # Every outcome carries a non-empty reason, so an annotation is never a bare
        # label the human has to decode.
        assert all(o.reason for o in result.outcomes)

    def test_agg_dt_024_two_voices_on_one_target_both_annotate_it(self) -> None:
        """AGG-DT-024: two dissents on the same target both survive as annotations, and
        the consensus entry names both voices.
        """
        result = _run(
            [
                _finding(id="f1", voice="codex", target="Q4"),
                _finding(id="f2", voice="agy", target="Q4"),
            ]
        )
        assert result.consensus == {"Q4": ["agy", "codex"]}
        assert {o.finding_id for o in result.outcomes} == {"f1", "f2"}

    def test_agg_dt_025_r1_blank_voice_has_no_cross_round_eligibility(self) -> None:
        """AGG-DT-025: a voice that produced nothing in R1 cannot establish consensus in
        R2. Agreeing after seeing everyone else's findings is anchoring, not corroboration.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", target="Q4"),
                _finding(id="r2b", voice="agy", target="Q4", round=Round.R2.value),
            ]
        )
        assert _effect_of(result, "r2b") == Effect.NO_CONSENSUS_ELIGIBILITY.value
        assert result.consensus == {"Q4": ["codex"]}, (
            "only the voice that spoke in R1 may establish consensus"
        )

    def test_agg_dt_026_cross_round_from_eligible_voice_adds_no_vote(self) -> None:
        """AGG-DT-026: even an eligible voice's R2 finding does not add an independent
        vote -- R2 may only refute, downgrade, withdraw, or supply a check.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", target="Q1"),
                _finding(id="r2a", voice="codex", target="Q4", round=Round.R2.value),
            ]
        )
        assert _effect_of(result, "r2a") == Effect.CROSS_ROUND_REFUTATION.value
        assert "Q4" not in result.consensus, "R2 must not create a new consensus target"


# --------------------------------------------------------------------------- #
# task 2.4 -- demotion needs executed evidence
# --------------------------------------------------------------------------- #


class TestDemotionGatedOnConfirmedCheck:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (CheckState.NOT_EXECUTED, []),
            (CheckState.UNABLE_TO_EXECUTE, []),
            (CheckState.INCONCLUSIVE, []),
            (CheckState.CONFIRMED, ["lesson-bash-quoting"]),
            (CheckState.REFUTED, []),
        ],
    )
    def test_agg_dt_030_only_confirmed_check_recommends_demotion(
        self, state: CheckState, expected: list[str]
    ) -> None:
        """AGG-DT-030: one case per settling-check state; only `confirmed` recommends.

        The label alone must not trigger a mechanical action: the whole design rests on
        "agreement is not evidence", so an unexecuted UNSUPPORTED label is a value
        judgement and belongs to the human.
        """
        result = _run(
            [
                _finding(
                    classification=Classification.UNSUPPORTED.value,
                    check_state=state.value,
                )
            ]
        )
        assert result.demotion_recommendations == expected

    def test_agg_dt_031_non_unsupported_never_recommends(self) -> None:
        """AGG-DT-031: only UNSUPPORTED can recommend demotion, even when confirmed."""
        for classification in (
            Classification.CONTRADICTED,
            Classification.OVERCLAIMED,
            Classification.MISATTRIBUTED,
            Classification.ALTERNATIVE_CAUSE,
        ):
            result = _run(
                [
                    _finding(
                        classification=classification.value,
                        check_state=CheckState.CONFIRMED.value,
                    )
                ]
            )
            assert result.demotion_recommendations == [], (
                f"{classification} must not produce a demotion recommendation"
            )


# --------------------------------------------------------------------------- #
# task 2.5 -- input hygiene
# --------------------------------------------------------------------------- #


class TestInputHygiene:
    def test_agg_dt_040_stale_digest_is_not_applied(self) -> None:
        """AGG-DT-040: findings produced against an earlier draft are marked stale and
        derive neither a confidence change nor a recommendation.
        """
        result = _run(
            [
                _finding(
                    draft_digest="digest-from-before-calibration",
                    classification=Classification.UNSUPPORTED.value,
                    check_state=CheckState.CONFIRMED.value,
                )
            ]
        )
        assert result.stale_finding_ids == ["f1"]
        assert _effect_of(result, "f1") == Effect.STALE.value
        assert result.confidence == 5
        assert result.demotion_recommendations == []

    def test_agg_dt_041_order_independent(self) -> None:
        """AGG-DT-041: permuting the finding order leaves the result identical."""
        findings = [
            _finding(id="f1", voice="codex", target="Q4"),
            _finding(id="f2", voice="agy", target="Q1", classification=Classification.AGREE.value),
            _finding(id="f3", voice="claude-adversary", voice_kind=VoiceKind.ADVERSARIAL.value),
        ]
        forward = result_to_dict(_run(copy.deepcopy(findings)))
        backward = result_to_dict(_run(list(reversed(copy.deepcopy(findings)))))
        assert forward == backward

    def test_agg_dt_042_idempotent(self) -> None:
        """AGG-DT-042: aggregating the same set twice yields the same result -- no tally
        is incremented twice and no confidence change is applied twice.
        """
        findings = [
            _finding(id="f1", voice="codex", classification=Classification.UNSUPPORTED.value),
            _finding(id="f2", voice="agy", classification=Classification.OVERCLAIMED.value),
        ]
        first = result_to_dict(_run(copy.deepcopy(findings)))
        second = result_to_dict(_run(copy.deepcopy(findings)))
        assert first == second
        assert first["confidence"] == 3, "two dissenting voices lower 5 by exactly 2, once"

    def test_agg_dt_043_stale_voice_does_not_grant_r2_eligibility(self) -> None:
        """AGG-DT-043: a voice whose only R1 finding is stale has not "spoken" in R1, so
        it gains no cross-round consensus eligibility.

        Without this, editing the draft would silently promote an anchored R2 voice.
        """
        result = _run(
            [
                _finding(id="old", voice="agy", draft_digest="older-digest"),
                _finding(id="new", voice="agy", target="Q4", round=Round.R2.value),
            ]
        )
        assert _effect_of(result, "new") == Effect.NO_CONSENSUS_ELIGIBILITY.value


# --------------------------------------------------------------------------- #
# task 2.6 -- shadow flag and policy explanation
# --------------------------------------------------------------------------- #


class TestShadowFlag:
    def test_agg_dt_050_recommendation_computed_but_inert_by_default(self) -> None:
        """AGG-DT-050: the recommendation is always computed and reported; acting on it
        defaults to off, so the skill ships in shadow mode.
        """
        findings = [
            _finding(
                classification=Classification.UNSUPPORTED.value,
                check_state=CheckState.CONFIRMED.value,
            )
        ]
        shadow = _run(copy.deepcopy(findings))
        assert shadow.demotion_recommendations == ["lesson-bash-quoting"]
        assert shadow.demotion_applied is False, "demotion must be inert by default"

    def test_agg_dt_051_flag_enables_application(self) -> None:
        """AGG-DT-051: the explicit switch is what turns a recommendation into an applied
        decision -- and it changes nothing else.
        """
        findings = [
            _finding(
                classification=Classification.UNSUPPORTED.value,
                check_state=CheckState.CONFIRMED.value,
            )
        ]
        enabled = _run(copy.deepcopy(findings), enable_demotion=True)
        assert enabled.demotion_applied is True
        assert enabled.demotion_recommendations == ["lesson-bash-quoting"]

    def test_agg_dt_052_flag_alone_applies_nothing(self) -> None:
        """AGG-DT-052: negative control -- enabling the switch with no recommendation to
        apply must not report an application.
        """
        enabled = _run([_finding(classification=Classification.AGREE.value)], enable_demotion=True)
        assert enabled.demotion_recommendations == []
        assert enabled.demotion_applied is False

    def test_agg_dt_053_explain_policy_covers_every_effect(self) -> None:
        """AGG-DT-053: the policy explanation enumerates every Effect member.

        This is what the runbook cross-check consumes; if a new effect were added
        without a description, the runbook table could never mention it.
        """
        described = set(explain_policy()["effects"])
        assert described == {e.value for e in Effect}
