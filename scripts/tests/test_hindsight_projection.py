"""HSP: canonical projection eligibility, lifecycle identity and honest measurement."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/growth/skills/pr-retrospective/scripts/hindsight_projection.py"
spec = importlib.util.spec_from_file_location("hindsight_projection", SCRIPT)
assert spec is not None and spec.loader is not None
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


@pytest.fixture
def payload():
    return {
        "project": "payments",
        "record": {
            "id": "lesson-42",
            "project": "payments",
            "key": "payments-retry-boundary",
            "type": "pitfall",
            "source": "observed",
            "confidence": 8,
            "tags": [],
            "retired_at": None,
            "superseded_by": None,
        },
        "summary": "A timeout is not evidence that a write did not occur.",
        "evidence_ids": ["team/payments#42"],
    }


def accepted(result):
    return {key: value for key, value in result.items() if key != "arguments"} | {
        "outcome": "accepted"
    }


@pytest.mark.parametrize(
    ("kind", "source", "confidence", "evidence", "expected"),
    [
        ("pitfall", "observed", 6, ["p#1"], "skip"),
        ("pitfall", "observed", 7, ["p#1"], "ingest"),
        ("pitfall", "inferred", 9, ["p#1"], "skip"),
        ("pitfall", "cross-model", 8, [], "skip"),
        ("pattern", "observed", 8, ["p#1", "p#1"], "skip"),
        ("pattern", "observed", 7, ["p#1", "p#2"], "ingest"),
        ("operational", "observed", 10, ["p#1", "p#2"], "skip"),
    ],
)
def test_hsp_dt_001_publication_requires_evidence_and_threshold(
    payload, kind, source, confidence, evidence, expected
):
    """tc: HSP-DT-001
    spec: retro-hindsight-projection#publication-thresholds
    """
    payload["record"].update(type=kind, source=source, confidence=confidence)
    payload["evidence_ids"] = evidence
    result = projection.prepare(payload)
    assert result["action"] == expected
    if expected == "skip":
        assert "arguments" not in result


def test_hsp_st_002_identical_revision_skips_but_changed_content_replaces(payload):
    """tc: HSP-ST-002
    spec: retro-hindsight-projection#changed-summary
    """
    first = projection.prepare(payload)
    payload["previous"] = accepted(first)
    assert projection.prepare(payload)["reason"] == "same_accepted_revision"
    payload["summary"] = "A verified revised boundary after the incident review."
    revised = projection.prepare(payload)
    assert revised["action"] == "ingest"
    assert revised["content_hash"] != first["content_hash"]
    assert revised["expected_doc_id"] == first["expected_doc_id"]
    assert revised["arguments"]["title"] == first["arguments"]["title"]
    assert set(revised["arguments"]) == {"title", "content"}
    content = json.loads(revised["arguments"]["content"])
    assert content["source_system"] == "mycelium"
    assert content["project"] == "payments"
    assert content["revision_key"].endswith(revised["content_hash"])


def test_hsp_dt_003_evidence_order_does_not_create_revision(payload):
    """tc: HSP-DT-003
    spec: retro-hindsight-projection#pattern-evidence-deduplication
    """
    payload["record"]["type"] = "pattern"
    payload["evidence_ids"] = ["p#2", "p#1"]
    payload["previous"] = accepted(projection.prepare(payload))
    payload["evidence_ids"] = ["p#1", "p#2", "p#1"]
    assert projection.prepare(payload)["reason"] == "same_accepted_revision"


@pytest.mark.parametrize(
    ("updates", "lifecycle"),
    [
        ({"tags": ["parked"]}, "parked"),
        ({"superseded_by": "replacement-id"}, "superseded"),
        ({"retired_at": "2026-09-30T12:00:00Z"}, "retired"),
    ],
)
def test_hsp_st_004_inactive_low_confidence_replaces_previous_only(payload, updates, lifecycle):
    """tc: HSP-ST-004
    spec: retro-hindsight-projection#inactive-record
    """
    first = projection.prepare(payload)
    payload["record"].update(updates, confidence=4)
    assert projection.prepare(payload)["action"] == "skip"
    payload["previous"] = accepted(first)
    tombstone = projection.prepare(payload)
    assert tombstone["action"] == "ingest"
    assert tombstone["expected_doc_id"] == first["expected_doc_id"]
    content = json.loads(tombstone["arguments"]["content"])
    assert content["lifecycle"] == lifecycle
    assert "Do not use it as active guidance" in content["summary"]
    payload["previous"] = accepted(tombstone)
    payload["summary"] = "Rephrased old summary must not create another tombstone."
    assert projection.prepare(payload)["reason"] == "same_accepted_revision"


@pytest.mark.parametrize("field", ["project", "source_id", "expected_doc_id", "outcome"])
def test_hsp_eg_005_rejects_foreign_or_unaccepted_receipts(payload, field):
    """tc: HSP-EG-005
    spec: retro-hindsight-projection#cross-project-receipt
    """
    payload["previous"] = accepted(projection.prepare(payload))
    payload["previous"][field] = "wrong"
    with pytest.raises(ValueError, match="accepted receipt"):
        projection.prepare(payload)


@pytest.mark.parametrize("key", ["Key", "a_b", "a--b", "a b", "../key"])
def test_hsp_eg_006_rejects_slug_collisions(payload, key):
    """tc: HSP-EG-006
    spec: retro-hindsight-projection#unsafe-key
    """
    payload["record"]["key"] = key
    with pytest.raises(ValueError, match="kebab-case"):
        projection.prepare(payload)


@pytest.mark.parametrize("field", ["tags", "retired_at", "superseded_by"])
def test_hsp_eg_007_missing_lifecycle_is_not_active(payload, field):
    """tc: HSP-EG-007
    spec: retro-hindsight-projection#missing-lifecycle
    """
    del payload["record"][field]
    with pytest.raises(ValueError):
        projection.prepare(payload)


def test_hsp_bv_008_effective_confidence_controls_eligibility(payload):
    """tc: HSP-BV-008
    spec: retro-hindsight-projection#publication-thresholds
    """
    payload["record"]["effective_confidence"] = 6.9
    assert projection.prepare(payload)["action"] == "skip"
    payload["record"]["effective_confidence"] = 7
    assert projection.prepare(payload)["action"] == "ingest"


def audit(number, *, invocation=None, kind="retro", sample="live", metrics=None):
    return {
        "schema_version": 1,
        "invocation_id": invocation or f"run-{number}",
        "project": "payments",
        "kind": kind,
        "canonical_written": kind == "retro",
        "sample_kind": sample,
        "retro_id": f"team/payments#{number}",
        "recorded_at": f"2026-09-30T12:{number % 60:02}:00Z",
        "events": [{"operation": "ingest", "outcome": "accepted"}],
        "metrics": metrics or [],
    }


def store(directory, filename, value):
    (directory / filename).write_text(json.dumps(value), encoding="utf-8")


def test_hsp_bv_009_thirty_distinct_real_retros_not_files(tmp_path):
    """tc: HSP-BV-009
    spec: retro-hindsight-projection#repeated-execution
    """
    for number in range(29):
        store(tmp_path, f"{number}.json", audit(number))
    store(tmp_path, "rerun.json", audit(0, invocation="retry-zero"))
    store(tmp_path, "smoke.json", audit(40, sample="smoke"))
    store(tmp_path, "promotion.json", audit(41, kind="promotion"))
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 29
    assert result["status"] == "insufficient_data"
    store(tmp_path, "real-30.json", audit(29))
    assert projection.report(tmp_path, "payments")["measurement_ready"] is True


def test_hsp_dt_010_unknown_is_not_false_and_later_review_updates_once(tmp_path):
    """tc: HSP-DT-010
    spec: retro-hindsight-projection#measurement-observations
    """
    first = audit(1, metrics=[{"source_id": "lesson-a", "duplicate": True}])
    store(tmp_path, "first.json", first)
    store(tmp_path, "copy.json", first)
    review = audit(
        2,
        kind="promotion",
        metrics=[{"retro_id": "team/payments#1", "source_id": "lesson-a", "duplicate": False}],
    )
    store(tmp_path, "review.json", review)
    result = projection.report(tmp_path, "payments")
    assert result["invocation_count"] == 2
    assert result["retro_count"] == 1
    assert result["rates"]["duplicate"] == {"positive": 0, "observed": 1, "rate": 0.0}
    assert result["rates"]["cited"] == {"positive": 0, "observed": 0, "rate": None}


def test_hsp_eg_011_corrupt_audit_is_visible_not_silent_zero(tmp_path):
    """tc: HSP-EG-011
    spec: retro-hindsight-projection#measurement-observations
    """
    store(tmp_path, "bad.json", audit(1, metrics=[{"source_id": "a", "cited": "false"}]))
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 0
    assert result["excluded"] == ["bad.json: observations must be booleans or null"]


def test_hsp_st_012_cancelled_retro_does_not_count_as_delivered(tmp_path):
    """tc: HSP-ST-012
    spec: retro-hindsight-projection#cancelled-retro
    """
    cancelled = audit(42)
    cancelled["canonical_written"] = False
    store(tmp_path, "cancelled.json", cancelled)
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 0
    assert result["measurement_ready"] is False
