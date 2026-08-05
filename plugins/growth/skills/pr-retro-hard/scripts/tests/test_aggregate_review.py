"""Property and contract tests for aggregate_review.py.

The kernel is a pure function, so every rule below is deterministic given a finding set.
That is the whole point of lifting the aggregation rules out of runbook prose: prose can
only be asserted to still *contain* a sentence, never to have been *obeyed*.

This file was rewritten after PR #376's R1 mob review found 5 Critical + 3 Important gaps
in the first version -- see the PR discussion for the full mob-review record. The scoring
model changed shape: confidence/source are now keyed per lesson target (a map), not a
single scalar, and R2 findings can supersede their own (target, voice) R1 finding for
scoring rather than being permanently inert.

Test classes map onto the change's task groups plus the mob-review fix groups:

  * TestFindingContract        -- schema/parsing, including the findings-must-be-a-list
                                   regression this rewrite itself introduced and caught
  * TestLessonScoring           -- per-target monotonicity and isolation
  * TestPresentationInvariants  -- adversarial / no-check / draft preservation
  * TestSupersession            -- R2 overriding its own (target, voice) R1 finding
  * TestDemotionGatedOnConfirmedCheck -- demotion needs executed, confirmed evidence
  * TestInputHygiene            -- staleness (both digests) / permutation / idempotence
  * TestShadowFlag              -- recommendations inert until enabled
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
PACKET = "packet-digest-bbb"


def _finding(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "f1",
        "voice": "codex",
        "voice_kind": VoiceKind.EXTERNAL.value,
        "round": Round.R1.value,
        "target": "lesson-x",
        "classification": Classification.OVERCLAIMED.value,
        "settling_check": "rg -n 'pattern' path/",
        "statement": "The cited evidence covers only macOS bash 3.2.",
        "draft_digest": DIGEST,
        "packet_digest": PACKET,
        "check_state": CheckState.CONFIRMED.value,
    }
    base.update(overrides)
    return base


def _lesson(confidence: int = 5, source: str = Source.INFERRED.value) -> dict[str, Any]:
    return {"original_confidence": confidence, "original_source": source}


def _payload(
    findings: list[dict[str, Any]],
    lessons: dict[str, dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": "1.0",
        "draft_digest": DIGEST,
        "packet_digest": PACKET,
        "lessons": {"lesson-x": _lesson()} if lessons is None else lessons,
        "findings": findings,
    }
    base.update(overrides)
    return base


def _run(
    findings: list[dict[str, Any]],
    lessons: dict[str, dict[str, Any]] | None = None,
    **overrides: Any,
):
    return aggregate(parse_input(_payload(findings, lessons, **overrides)))


def _effect_of(result: Any, finding_id: str) -> str:
    for outcome in result.outcomes:
        if outcome.finding_id == finding_id:
            return outcome.effect
    raise AssertionError(f"finding {finding_id!r} missing from outcomes")


def _confidence_of(result: Any, target: str) -> int:
    return result.lessons[target].confidence


# --------------------------------------------------------------------------- #
# schema / parsing contract
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
        assert unable.demotion_recommendations == []
        assert refuted.demotion_recommendations == []
        assert unable.outcomes[0].check_state is CheckState.UNABLE_TO_EXECUTE
        assert refuted.outcomes[0].check_state is CheckState.REFUTED
        # Neither state may be conflated at the effect level either.
        assert _effect_of(unable, "f1") != _effect_of(refuted, "f1")

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
        lesson_props = schema["properties"]["lessons"]["additionalProperties"]["properties"]
        assert set(lesson_props["original_source"]["enum"]) == {s.value for s in Source}

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

    def test_agg_dt_009_findings_must_be_a_list_not_string_coerced(self) -> None:
        """AGG-DT-009: `findings` is validated as a list, not accidentally routed through
        the string-required helper.

        Regression for a bug this very rewrite introduced: `_require` was tightened to
        reject non-string values for required *string* fields (the null-coercion fix),
        and `findings` -- a list -- was still being parsed through it, so a well-formed
        request failed with "must be a string, got list". The fix split `_require` into
        `_require_key` (existence only) and `_require_str` (existence + string type) and
        routed `findings` through the former. This test pins that split.
        """
        good = _run([_finding()])
        assert good is not None  # parses without raising

        bad = _finding()
        payload = _payload([bad])
        payload["findings"] = "not-a-list"
        with pytest.raises(MalformedInput) as exc:
            parse_input(payload)
        assert "陣列" in str(exc.value) or "list" in str(exc.value).lower()

    def test_agg_dt_015_null_required_field_rejected_not_stringified(self) -> None:
        """AGG-DT-015: a JSON null in a required string field is rejected, not coerced by
        `str(None)` into the literal string "None".

        This is the Critical R1 mob-review finding: `target: null` used to produce a
        finding with `target == "None"`, fabricating a false consensus entry keyed by
        that literal string. `isinstance(value, str)` is False for None, so a check that
        only guarded emptiness for actual strings let it straight through.
        """
        bad = _finding(target=None)
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        message = str(exc.value)
        assert "target" in message
        assert "f1" in message

    def test_agg_dt_016_null_settling_check_rejected_not_treated_as_present(self) -> None:
        """AGG-DT-016: `settling_check: null` is rejected outright, rather than being
        coerced to the string "None" and then treated as "a check was supplied" (since
        "None" != "(none)").

        This was the worst manifestation of the null-coercion bug: combined with
        `check_state: confirmed`, a finding that supplied NO check at all produced a real
        `demotion_recommendations` entry, defeating the "check must be executed and
        confirmed" precondition entirely.
        """
        bad = _finding(settling_check=None, check_state=CheckState.CONFIRMED.value)
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        assert "settling_check" in str(exc.value)

    #: every string field `Finding` carries. AGG-DT-015/016 above are the original,
    #: narrative-documented Critical regressions for `target`/`settling_check`; this list
    #: is the exhaustive sweep silent-failure-hunter's Round 2 finding asked for: mutating
    #: `id` back to the pre-fix `str(_require_key(...))` pattern survived the full suite
    #: because no test exercised anything but `target`/`settling_check`/`voice`/`statement`.
    _ALL_FINDING_STRING_FIELDS = (
        "id",
        "voice",
        "voice_kind",
        "round",
        "target",
        "classification",
        "settling_check",
        "statement",
        "draft_digest",
        "packet_digest",
    )

    @pytest.mark.parametrize("field", _ALL_FINDING_STRING_FIELDS)
    def test_agg_dt_017_non_string_type_rejected_for_every_required_field(self, field: str) -> None:
        """AGG-DT-017: a non-string, non-null value (a number) in ANY required string
        field is rejected the same way null is -- the guard is a type check, not a null
        check, and it must cover every field, not just the ones a narrative example
        happened to name.
        """
        bad = _finding(**{field: 12345})
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        assert field in str(exc.value), f"error for {field}=12345 must name the field"

    @pytest.mark.parametrize("field", _ALL_FINDING_STRING_FIELDS)
    def test_agg_dt_017b_null_rejected_for_every_required_field(self, field: str) -> None:
        """AGG-DT-017b: the same exhaustive sweep for JSON `null` specifically -- the
        exact value that produced the fabricated `"None"` string before this fix.
        """
        bad = _finding(**{field: None})
        with pytest.raises(MalformedInput) as exc:
            parse_input(_payload([bad]))
        assert field in str(exc.value), f"error for {field}=None must name the field"

    def test_agg_dt_019_empty_string_rejected_not_just_field_absence(self) -> None:
        """AGG-DT-019 (Important #7 regression): a required string field supplied as an
        empty (or whitespace-only) string is rejected, not just its outright absence.

        pr-test-analyzer proved by mutation that the pre-existing empty-string guard had
        no test: removing it left all 38 tests of that generation green. AGG-DT-002/003
        above only test the *absent-key* case (`del bad["target"]`); this covers the
        distinct *present-but-empty* case.
        """
        for field in ("target", "statement", "voice"):
            bad = _finding(**{field: ""})
            with pytest.raises(MalformedInput) as exc:
                parse_input(_payload([bad]))
            assert field in str(exc.value), f"error for empty {field} must name the field"

        whitespace_only = _finding(target="   ")
        with pytest.raises(MalformedInput):
            parse_input(_payload([whitespace_only]))

    def test_agg_dt_018_lesson_entry_malformed_type_rejected(self) -> None:
        """AGG-DT-018: a lesson's original_confidence/original_source are type- and
        range-checked the same way finding fields are.
        """
        with pytest.raises(MalformedInput):
            parse_input(_payload([_finding()], lessons={"lesson-x": _lesson(confidence=0)}))
        with pytest.raises(MalformedInput):
            parse_input(_payload([_finding()], lessons={"lesson-x": _lesson(confidence=11)}))
        with pytest.raises(MalformedInput):
            parse_input(_payload([_finding()], lessons={"lesson-x": {"original_confidence": None}}))
        with pytest.raises(MalformedInput):
            parse_input(_payload([_finding()], lessons={"lesson-x": _lesson(source="bogus")}))
        # bool is a subclass of int in Python (`isinstance(True, int)` is True), so the
        # int-type check alone would silently accept `original_confidence: true` (JSON)
        # as confidence 1 -- the explicit `isinstance(confidence, bool)` exclusion this
        # asserts guards exactly that.
        with pytest.raises(MalformedInput):
            parse_input(
                _payload(
                    [_finding()],
                    lessons={
                        "lesson-x": {"original_confidence": True, "original_source": "inferred"}
                    },
                )
            )

    def test_agg_dt_071_lesson_entry_rejects_unknown_properties(self) -> None:
        """AGG-DT-071 (Round 2 Important regression): the schema declares
        `additionalProperties: false` for a lesson entry, but the parser silently
        ignored any extra or misspelled key -- a caller who typo'd
        `original_confdence` would see their intended value silently discarded with no
        error, and the kernel would fall back to whatever `original_confidence` (if
        present) or a validation error said instead.
        """
        with pytest.raises(MalformedInput) as exc:
            parse_input(
                _payload(
                    [_finding()],
                    lessons={
                        "lesson-x": {
                            "original_confidence": 5,
                            "original_source": "inferred",
                            "original_confdence": 9,
                        }
                    },
                )
            )
        assert "lesson-x" in str(exc.value)

    def test_agg_dt_072_top_level_lessons_must_be_an_object(self) -> None:
        """AGG-DT-072 (Round 2 Important regression): `lessons` being a non-object (a
        list, a string) is a contract violation, not something that crashes past the
        documented exit-2 path with a raw `AttributeError` from a missing `.items()`.
        """
        for bad_lessons in ([], "not-a-dict", 5):
            payload = _payload([_finding()])
            payload["lessons"] = bad_lessons
            with pytest.raises(MalformedInput):
                parse_input(payload)

    def test_agg_dt_073_top_level_enable_demotion_must_be_bool(self) -> None:
        """AGG-DT-073 (Round 2 Important regression): a non-bool `enable_demotion` (e.g.
        the JSON string `"true"`) is rejected rather than flowing unchecked into
        `demotion_applied = bool(recommendations) and data.enable_demotion` -- where
        Python's `and` returns the second operand verbatim when the first is truthy,
        silently producing the string `"true"` instead of the boolean the JSON output
        contract promises.
        """
        for bad_value in ("true", 1, 0):
            with pytest.raises(MalformedInput):
                parse_input(_payload([_finding()], enable_demotion=bad_value))


# --------------------------------------------------------------------------- #
# per-target confidence/source scoring
# --------------------------------------------------------------------------- #


class TestLessonScoring:
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
            lessons={"lesson-x": _lesson(confidence_in, source_in.value)},
        )
        assert _confidence_of(result, "lesson-x") == confidence_out
        assert result.lessons["lesson-x"].source is source_out

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
        assert _confidence_of(piled, "lesson-x") == _confidence_of(baseline, "lesson-x")
        assert piled.demotion_recommendations == []

    def test_agg_dt_012_source_is_never_rewritten_to_cross_model(self) -> None:
        """AGG-DT-012: no finding combination rewrites source to cross-model."""
        result = _run(
            [
                _finding(id="f1", voice="codex", classification=Classification.UNSUPPORTED.value),
                _finding(id="f2", voice="agy", classification=Classification.UNSUPPORTED.value),
            ]
        )
        assert result.lessons["lesson-x"].source is Source.INFERRED

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
            lessons={"lesson-x": _lesson(2)},
        )
        assert _confidence_of(result, "lesson-x") == 1

    def test_agg_dt_014_agree_never_reaches_a_consensus_bearing_effect(self) -> None:
        """AGG-DT-014: an AGREE finding never receives an effect that carries weight,
        across every voice kind and every check state.
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
                assert _confidence_of(result, "lesson-x") == 5, "AGREE must never move the score"

    def test_agg_dt_068_adversarial_branch_checked_before_user_stated(self) -> None:
        """AGG-DT-068 (Round 2 Important regression): an adversarial finding against a
        user-stated lesson is classified by the ADVERSARIAL branch, not the
        RECORDED_AGAINST_USER_STATED branch -- `_intrinsic_effect` checks voice_kind
        before checking the target's lesson source, and this pins that ordering so a
        future edit that swaps them is caught (previously unverified: swapping the two
        branches left the full suite green).
        """
        result = _run(
            [
                _finding(
                    voice_kind=VoiceKind.ADVERSARIAL.value,
                    classification=Classification.UNSUPPORTED.value,
                )
            ],
            lessons={"lesson-x": _lesson(9, Source.USER_STATED.value)},
        )
        assert _effect_of(result, "f1") == Effect.ADVERSARIAL_HYPOTHESIS.value

    def test_agg_dt_060_only_confirmed_check_state_lowers_confidence(self) -> None:
        """AGG-DT-060 (Critical #1 regression): the full five-state matrix for
        CONFIDENCE, not just for the demotion recommendation. A refuted or unexecuted
        claim must not move the score -- it must be treated exactly as if the voice had
        supplied no check at all.

        This is the mob-review Critical: `check_state` was ignored when deciding
        `ACTIONABLE` (the effect that lowers confidence and counts toward consensus),
        so a dissent whose check came back `refuted` still knocked the score down.
        """
        for state in CheckState:
            result = _run([_finding(check_state=state.value)])
            confidence = _confidence_of(result, "lesson-x")
            if state is CheckState.CONFIRMED:
                assert confidence == 4, f"{state}: confirmed dissent must lower confidence"
            else:
                assert confidence == 5, f"{state}: must NOT lower confidence, got {confidence}"

    def test_agg_dt_061_refuted_check_does_not_establish_consensus(self) -> None:
        """AGG-DT-061: a refuted finding is recorded (still in outcomes) but does not
        count toward consensus, matching its zero effect on confidence.
        """
        result = _run([_finding(check_state=CheckState.REFUTED.value)])
        assert result.consensus == {}
        assert _effect_of(result, "f1") == Effect.NOT_REPRODUCED.value
        assert any(o.finding_id == "f1" for o in result.outcomes), "must still be presented"

    def test_agg_dt_062_multi_target_isolation(self) -> None:
        """AGG-DT-062 (Critical #3 regression): a dissent against one lesson must never
        move a different lesson's confidence, and a lesson with zero dissent must retain
        its exact original value even when other lessons in the same batch are lowered.
        """
        result = _run(
            [
                _finding(
                    id="f1",
                    voice="codex",
                    target="lesson-A",
                    classification=Classification.AGREE.value,
                ),
                _finding(
                    id="f2",
                    voice="agy",
                    target="lesson-B",
                    classification=Classification.OVERCLAIMED.value,
                ),
            ],
            lessons={
                "lesson-A": _lesson(8, Source.INFERRED.value),
                "lesson-B": _lesson(5, Source.INFERRED.value),
            },
        )
        assert _confidence_of(result, "lesson-A") == 8, "lesson-A had zero dissent"
        assert _confidence_of(result, "lesson-B") == 4, (
            "lesson-B's own dissent lowers only lesson-B"
        )

    def test_agg_dt_063_lesson_with_zero_findings_is_still_reported(self) -> None:
        """AGG-DT-063: every target present in the input `lessons` map appears in the
        output, unchanged, even if no finding ever mentions it.
        """
        result = _run([], lessons={"lesson-untouched": _lesson(7, Source.USER_STATED.value)})
        assert _confidence_of(result, "lesson-untouched") == 7
        assert result.lessons["lesson-untouched"].source is Source.USER_STATED

    def test_agg_dt_064_target_outside_lessons_map_produces_no_lessons_entry(self) -> None:
        """AGG-DT-064: a finding whose target has no entry in `lessons` (a Q1-Q5 narrative
        item, or an M2 rule-draft target) still produces an outcome and can still count
        toward consensus, but there is no confidence to report for it.
        """
        result = _run(
            [_finding(target="Q3", classification=Classification.MISATTRIBUTED.value)],
            lessons={},
        )
        assert "Q3" not in result.lessons
        assert _effect_of(result, "f1") == Effect.ACTIONABLE.value
        assert result.consensus == {"Q3": ["codex"]}

    def test_agg_dt_065_distinct_voices_same_target_counts_once_per_voice(self) -> None:
        """AGG-DT-065 (Important #6 regression, generalised to the per-target model):
        TWO DIFFERENT voices each submitting one dissent against the SAME target must
        decrement by exactly the number of distinct voices, not accumulate further --
        `lowering_voices_by_target` is a set of voices, not a running tally.

        This test used to construct two findings from the SAME voice against the same
        target to make this point. Round 2 mob review (4 independent voices: Codex, agy,
        and two Claude subagents) found that shape was actually testing the wrong thing:
        a single voice submitting two R1 findings for one (target, voice) pair is exactly
        the ambiguous-input shape AGG-DT-069 now rejects outright, and the old version of
        this test passed only because Python's dict-overwrite silently kept one of the two
        findings and evaluated to the same confidence either way -- it could not tell
        "correctly deduped both votes" from "silently discarded one vote", which is
        precisely how the discarded-vote bug survived undetected through this round.
        """
        result = _run(
            [
                _finding(id="f1", voice="codex", classification=Classification.OVERCLAIMED.value),
                _finding(id="f2", voice="agy", classification=Classification.UNSUPPORTED.value),
            ]
        )
        assert _confidence_of(result, "lesson-x") == 3, (
            "two distinct voices dissenting, decrement by 2"
        )
        assert result.consensus == {"lesson-x": ["agy", "codex"]}

    def test_agg_dt_069_duplicate_round_target_voice_is_rejected(self) -> None:
        """AGG-DT-069 (Round 2 Critical regression, 4 independent voices): a single voice
        submitting two LIVE findings for the same (round, target, voice) triple is
        rejected outright as malformed input, rather than silently resolved by keeping
        whichever finding happens to be last in the input array.

        Before this fix, the discarded finding was mislabeled `superseded_by_r2` even
        though no R2 finding was involved at all, and which finding survived -- and
        therefore the resulting confidence and demotion recommendations -- depended on
        input order, breaking `aggregate()`'s own documented order-independence
        guarantee. `AGG-DT-041`'s original fixture happened to contain exactly this
        collision by accident (two findings both defaulting to voice="codex",
        target="lesson-x") and still passed, because both directions of the permutation
        hit the same silent-overwrite bug symmetrically.
        """
        with pytest.raises(MalformedInput) as exc:
            parse_input(
                _payload(
                    [
                        _finding(id="f1", voice="codex", classification=Classification.AGREE.value),
                        _finding(
                            id="f2",
                            voice="codex",
                            classification=Classification.OVERCLAIMED.value,
                        ),
                    ]
                )
            )
        message = str(exc.value)
        assert "f1" in message and "f2" in message, f"must name both colliding ids: {message}"
        assert "lesson-x" in message
        assert "codex" in message

    def test_agg_dt_070_stale_duplicate_does_not_collide_with_live_finding(self) -> None:
        """AGG-DT-070: a STALE finding sharing (round, target, voice) with a LIVE finding
        is not a collision -- this is the ordinary calibration-then-rerun workflow (M1
        reruns after the user edits the draft, producing a fresh finding for the same
        target the earlier, now-stale finding also covered). Only LIVE duplicates are
        rejected.
        """
        result = _run(
            [
                _finding(id="old", voice="codex", draft_digest="digest-from-before-calibration"),
                _finding(id="new", voice="codex", classification=Classification.AGREE.value),
            ]
        )
        assert _effect_of(result, "old") == Effect.STALE.value
        assert _effect_of(result, "new") == Effect.RECORDED_ONLY.value


# --------------------------------------------------------------------------- #
# presentation invariants
# --------------------------------------------------------------------------- #


class TestPresentationInvariants:
    def test_agg_dt_020_adversarial_never_counts_toward_consensus(self) -> None:
        """AGG-DT-020: an adversarial finding is reported but never tallied."""
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
        assert _confidence_of(result, "lesson-x") == 5, "commentary must not move the score"
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
        assert _confidence_of(result, "lesson-x") == 5, (
            "an unresolved finding must not lower the score"
        )

    def test_agg_dt_023_every_finding_appears_in_the_output(self) -> None:
        """AGG-DT-023: aggregation annotates, it never removes. Every supplied finding
        has exactly one outcome, whatever its effect.

        Each finding here targets a distinct (target, voice) pair -- since AGG-DT-069
        pins that a duplicate (round, target, voice) triple is now a hard input error,
        not something aggregate() resolves silently. Two findings defaulting to the same
        target+voice by coincidence (both use `_finding()`'s defaults) previously slipped
        past unnoticed here; this is the same accidental-collision shape Round 2 mob
        review found in production code, reproduced by this very test fixture.
        """
        findings = [
            _finding(id="f1", voice="codex", target="lesson-a"),
            _finding(id="f2", voice="agy", target="lesson-b", settling_check="(none)"),
            _finding(
                id="f3",
                voice="claude-adversary",
                target="lesson-c",
                voice_kind=VoiceKind.ADVERSARIAL.value,
            ),
            _finding(
                id="f4",
                voice="gemini",
                target="lesson-d",
                classification=Classification.AGREE.value,
            ),
            _finding(id="f5", voice="ghost", target="lesson-e", draft_digest="some-older-digest"),
        ]
        result = _run(findings)
        assert len(result.outcomes) == len(findings), "one outcome per supplied finding"
        assert {o.finding_id for o in result.outcomes} == {f["id"] for f in findings}
        assert all(o.reason for o in result.outcomes)

    def test_agg_dt_024_two_voices_on_one_target_both_annotate_it(self) -> None:
        """AGG-DT-024: two dissents on the same target both survive as annotations, and
        the consensus entry names both voices.
        """
        result = _run(
            [
                _finding(id="f1", voice="codex", target="Q4"),
                _finding(id="f2", voice="agy", target="Q4"),
            ],
            lessons={},
        )
        assert result.consensus == {"Q4": ["agy", "codex"]}
        assert {o.finding_id for o in result.outcomes} == {"f1", "f2"}


# --------------------------------------------------------------------------- #
# R2 supersession (Critical #5)
# --------------------------------------------------------------------------- #


class TestSupersession:
    def test_agg_dt_025_r1_blank_voice_has_no_cross_round_eligibility(self) -> None:
        """AGG-DT-025: a voice that never spoke to THIS target in R1 cannot establish
        scoring effect for it in R2, even if that voice spoke to a DIFFERENT target in
        R1. Eligibility is per (target, voice), not per voice.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", target="Q1"),
                _finding(id="r2b", voice="codex", target="Q4", round=Round.R2.value),
            ],
            lessons={},
        )
        assert _effect_of(result, "r2b") == Effect.NO_CONSENSUS_ELIGIBILITY.value
        assert "Q4" not in result.consensus
        assert result.consensus == {"Q1": ["codex"]}

    def test_agg_dt_026_eligible_r2_supersedes_r1_and_applies(self) -> None:
        """AGG-DT-026 (Critical #5 regression): an R2 finding for a (target, voice) pair
        that DID speak in R1 supersedes the R1 finding for scoring -- it is not a new
        vote (the pair already existed), and its content now actually governs.

        Before the fix, R2 findings were unconditionally inert regardless of content:
        a voice supplying a settling check in R2 for its own unresolved R1 finding had
        that check silently discarded.
        """
        result = _run(
            [
                _finding(
                    id="r1a",
                    voice="codex",
                    round=Round.R1.value,
                    settling_check="(none)",
                ),
                _finding(
                    id="r2a",
                    voice="codex",
                    round=Round.R2.value,
                    settling_check="rg -n foo",
                    check_state=CheckState.CONFIRMED.value,
                ),
            ]
        )
        assert _effect_of(result, "r1a") == Effect.SUPERSEDED_BY_R2.value
        assert _effect_of(result, "r2a") == Effect.ACTIONABLE.value
        assert _confidence_of(result, "lesson-x") == 4, "the R2-supplied check must actually apply"
        assert result.consensus == {"lesson-x": ["codex"]}

    def test_agg_dt_027_eligible_r2_can_downgrade_r1(self) -> None:
        """AGG-DT-027: supersession works in the other direction too -- an R1 finding
        that was ACTIONABLE (confirmed) can be downgraded by an R2 finding for the same
        (target, voice) that reports the check came back refuted.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", check_state=CheckState.CONFIRMED.value),
                _finding(
                    id="r2a",
                    voice="codex",
                    round=Round.R2.value,
                    check_state=CheckState.REFUTED.value,
                ),
            ]
        )
        assert _effect_of(result, "r1a") == Effect.SUPERSEDED_BY_R2.value
        assert _effect_of(result, "r2a") == Effect.NOT_REPRODUCED.value
        assert _confidence_of(result, "lesson-x") == 5, "the downgrade must reverse the R1 lowering"

    def test_agg_dt_028_r2_new_target_from_r1_voice_does_not_supersede_anything(self) -> None:
        """AGG-DT-028: a voice's R2 finding on a target it never touched in R1 does not
        supersede any R1 finding (there is nothing to supersede) and does not establish
        a new vote -- it is simply not eligible.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", target="lesson-x"),
                _finding(id="r2b", voice="codex", target="lesson-y", round=Round.R2.value),
            ],
            lessons={
                "lesson-x": _lesson(5),
                "lesson-y": _lesson(8),
            },
        )
        assert _effect_of(result, "r1a") == Effect.ACTIONABLE.value
        assert _effect_of(result, "r2b") == Effect.NO_CONSENSUS_ELIGIBILITY.value
        assert _confidence_of(result, "lesson-y") == 8, "the ineligible R2 finding must not apply"

    def test_agg_dt_029_two_voices_r2_supersession_independent(self) -> None:
        """AGG-DT-029: when two different voices each supersede their own R1 finding on
        the same target, both supersessions apply independently and consensus reflects
        both voices' R2-governing findings.
        """
        result = _run(
            [
                _finding(id="r1a", voice="codex", settling_check="(none)"),
                _finding(id="r1b", voice="agy", settling_check="(none)"),
                _finding(
                    id="r2a",
                    voice="codex",
                    round=Round.R2.value,
                    check_state=CheckState.CONFIRMED.value,
                ),
                _finding(
                    id="r2b",
                    voice="agy",
                    round=Round.R2.value,
                    check_state=CheckState.CONFIRMED.value,
                ),
            ]
        )
        assert _effect_of(result, "r1a") == Effect.SUPERSEDED_BY_R2.value
        assert _effect_of(result, "r1b") == Effect.SUPERSEDED_BY_R2.value
        assert _effect_of(result, "r2a") == Effect.ACTIONABLE.value
        assert _effect_of(result, "r2b") == Effect.ACTIONABLE.value
        assert _confidence_of(result, "lesson-x") == 3, "both voices now lower the same target"
        assert result.consensus == {"lesson-x": ["agy", "codex"]}


# --------------------------------------------------------------------------- #
# demotion needs executed evidence
# --------------------------------------------------------------------------- #


class TestDemotionGatedOnConfirmedCheck:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (CheckState.NOT_EXECUTED, []),
            (CheckState.UNABLE_TO_EXECUTE, []),
            (CheckState.INCONCLUSIVE, []),
            (CheckState.CONFIRMED, ["lesson-x"]),
            (CheckState.REFUTED, []),
        ],
    )
    def test_agg_dt_030_only_confirmed_check_recommends_demotion(
        self, state: CheckState, expected: list[str]
    ) -> None:
        """AGG-DT-030: one case per settling-check state; only `confirmed` recommends."""
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

    def test_agg_dt_066_actionable_effect_implies_confirmed_check_state(self) -> None:
        """AGG-DT-066: `Effect.ACTIONABLE` can only be reached when `check_state` is
        `confirmed` -- for every voice_kind/classification/check_state combination.

        `recommendations` deliberately does not re-check `check_state` (it would be a
        redundant guard shadowing a mutation to this exact invariant, the same failure
        shape this file's own history already produced once for `is_dissent`). This test
        is the single place that invariant is pinned, directly, instead of twice.
        """
        for classification in Classification:
            if classification is Classification.AGREE:
                continue
            for state in CheckState:
                result = _run(
                    [_finding(classification=classification.value, check_state=state.value)]
                )
                if _effect_of(result, "f1") == Effect.ACTIONABLE.value:
                    assert state is CheckState.CONFIRMED, (
                        f"ACTIONABLE reached with check_state={state}, classification="
                        f"{classification} -- the implication is broken"
                    )


# --------------------------------------------------------------------------- #
# input hygiene
# --------------------------------------------------------------------------- #


class TestInputHygiene:
    def test_agg_dt_040_stale_draft_digest_is_not_applied(self) -> None:
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
        assert _confidence_of(result, "lesson-x") == 5
        assert result.demotion_recommendations == []

    def test_agg_dt_044_stale_packet_digest_is_not_applied(self) -> None:
        """AGG-DT-044 (Critical #4 regression): a finding whose packet_digest no longer
        matches is stale even when its draft_digest still matches -- the packet's source
        material can change (a new PR commit lands) while the draft text stays fixed.
        """
        result = _run(
            [
                _finding(
                    packet_digest="packet-digest-from-before-new-commit-landed",
                    classification=Classification.UNSUPPORTED.value,
                    check_state=CheckState.CONFIRMED.value,
                )
            ]
        )
        assert result.stale_finding_ids == ["f1"]
        assert _confidence_of(result, "lesson-x") == 5
        assert result.demotion_recommendations == []

    def test_agg_dt_041_order_independent(self) -> None:
        """AGG-DT-041: permuting the finding order leaves the result identical."""
        findings = [
            _finding(id="f1", voice="codex", target="lesson-x"),
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
        assert first["lessons"]["lesson-x"]["confidence"] == 3, (
            "two dissenting voices lower 5 by exactly 2, once"
        )

    def test_agg_dt_043_stale_voice_does_not_grant_r2_eligibility(self) -> None:
        """AGG-DT-043: a voice whose only R1 finding on a target is stale has not
        "spoken" to that target in R1, so it gains no cross-round eligibility for it.
        """
        result = _run(
            [
                _finding(id="old", voice="agy", draft_digest="older-digest"),
                _finding(id="new", voice="agy", target="lesson-x", round=Round.R2.value),
            ]
        )
        assert _effect_of(result, "new") == Effect.NO_CONSENSUS_ELIGIBILITY.value


# --------------------------------------------------------------------------- #
# shadow flag and policy explanation
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
        assert shadow.demotion_recommendations == ["lesson-x"]
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
        assert enabled.demotion_recommendations == ["lesson-x"]

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
