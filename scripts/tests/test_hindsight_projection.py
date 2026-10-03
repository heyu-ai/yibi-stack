"""HSP：驗證 canonical 投影門檻、lifecycle identity 與真實觀測計數。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def prepare_one(payload):
    """把單一文件案例放進公開 batch 介面；不直接測 private 單列函式。"""
    item = {key: payload[key] for key in ("record", "summary", "evidence_ids") if key in payload}
    items = [item]
    if payload.get("predecessor") is not None:
        items.append({"record": payload["predecessor"]})
    batch = {
        "project": payload["project"],
        "items": items,
        "receipts": [payload["previous"]] if payload.get("previous") is not None else [],
    }
    return projection.prepare(batch)["plans"][0]


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
    result = prepare_one(payload)
    assert result["action"] == expected
    if expected == "skip":
        assert "arguments" not in result


def test_hsp_st_002_identical_revision_skips_but_changed_content_replaces(payload):
    """tc: HSP-ST-002
    spec: retro-hindsight-projection#changed-summary
    """
    first = prepare_one(payload)
    payload["previous"] = accepted(first)
    assert prepare_one(payload)["reason"] == "same_accepted_revision"
    payload["summary"] = "A verified revised boundary after the incident review."
    revised = prepare_one(payload)
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
    payload["previous"] = accepted(prepare_one(payload))
    payload["evidence_ids"] = ["p#1", "p#2", "p#1"]
    assert prepare_one(payload)["reason"] == "same_accepted_revision"


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
    first = prepare_one(payload)
    payload["record"].update(updates, confidence=4)
    assert prepare_one(payload)["action"] == "skip"
    payload["previous"] = accepted(first)
    tombstone = prepare_one(payload)
    assert tombstone["action"] == "ingest"
    assert tombstone["expected_doc_id"] == first["expected_doc_id"]
    content = json.loads(tombstone["arguments"]["content"])
    assert content["lifecycle"] == lifecycle
    assert "Do not use it as active guidance" in content["summary"]
    payload["previous"] = accepted(tombstone)
    payload["summary"] = "Rephrased old summary must not create another tombstone."
    assert prepare_one(payload)["reason"] == "same_accepted_revision"


@pytest.mark.parametrize("field", ["project", "source_id", "expected_doc_id", "outcome"])
def test_hsp_eg_005_rejects_foreign_or_unaccepted_receipts(payload, field):
    """tc: HSP-EG-005
    spec: retro-hindsight-projection#cross-project-receipt
    """
    payload["previous"] = accepted(prepare_one(payload))
    payload["previous"][field] = "wrong"
    with pytest.raises(ValueError):
        prepare_one(payload)


@pytest.mark.parametrize("key", ["Key", "a_b", "a--b", "a b", "../key"])
def test_hsp_eg_006_rejects_slug_collisions(payload, key):
    """tc: HSP-EG-006
    spec: retro-hindsight-projection#unsafe-key
    """
    payload["record"]["key"] = key
    with pytest.raises(ValueError):
        prepare_one(payload)


@pytest.mark.parametrize("field", ["tags", "retired_at", "superseded_by"])
def test_hsp_eg_007_missing_lifecycle_is_not_active(payload, field):
    """tc: HSP-EG-007
    spec: retro-hindsight-projection#missing-lifecycle
    """
    del payload["record"][field]
    with pytest.raises(ValueError):
        prepare_one(payload)


def test_hsp_bv_008_effective_confidence_controls_eligibility(payload):
    """tc: HSP-BV-008
    spec: retro-hindsight-projection#publication-thresholds
    """
    payload["record"]["effective_confidence"] = 6.9
    assert prepare_one(payload)["action"] == "skip"
    payload["record"]["effective_confidence"] = 7
    assert prepare_one(payload)["action"] == "ingest"


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
    assert [line.split(":", 1)[0] for line in result["excluded"]] == ["bad.json"]


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


@pytest.mark.parametrize("same_invocation", [False, True])
def test_hsp_st_013_latest_timestamp_uses_instants(tmp_path, same_invocation):
    """tc: HSP-ST-013
    spec: retro-hindsight-projection#measurement-observations
    """
    earlier = audit(1, metrics=[{"source_id": "lesson-a", "duplicate": True}])
    later = audit(1, metrics=[{"source_id": "lesson-a", "duplicate": False}])
    earlier["recorded_at"] = "2026-10-01T00:00:00Z"
    later["recorded_at"] = "2026-10-01T00:00:00.500Z"
    if not same_invocation:
        later["invocation_id"] = "later-review"
    store(tmp_path, "earlier.json", earlier)
    store(tmp_path, "later.json", later)
    result = projection.report(tmp_path, "payments")
    assert result["rates"]["duplicate"] == {"positive": 0, "observed": 1, "rate": 0.0}


@pytest.mark.parametrize("stamp", ["yesterday", "2026-10-01T00:00:00", ""])
def test_hsp_eg_014_invalid_or_naive_timestamp_is_excluded(tmp_path, stamp):
    """tc: HSP-EG-014
    spec: retro-hindsight-projection#measurement-observations
    """
    row = audit(1)
    row["recorded_at"] = stamp
    store(tmp_path, "bad-time.json", row)
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 0
    assert [line.split(":", 1)[0] for line in result["excluded"]] == ["bad-time.json"]


def test_hsp_eg_015_old_row_cannot_use_replacement_receipt(payload):
    """tc: HSP-EG-015
    spec: retro-hindsight-projection#receipt-ownership
    """
    current = prepare_one(payload)
    payload["previous"] = accepted(current)
    payload["record"].update(id="old-row", superseded_by="lesson-42")
    with pytest.raises(ValueError):
        prepare_one(payload)


def test_hsp_st_016_active_replacement_requires_canonical_predecessor(payload):
    """tc: HSP-ST-016
    spec: retro-hindsight-projection#receipt-ownership
    """
    payload["previous"] = accepted(prepare_one(payload))
    payload["record"]["id"] = "new-row"
    with pytest.raises(ValueError):
        prepare_one(payload)
    payload["predecessor"] = {
        **payload["record"],
        "id": "lesson-42",
        "project": "payments",
        "key": "payments-retry-boundary",
        "superseded_by": "new-row",
    }
    result = prepare_one(payload)
    assert result["action"] == "ingest"
    assert result["lesson_id"] == "new-row"
    assert result["expected_doc_id"] == payload["previous"]["expected_doc_id"]
    payload["predecessor"]["superseded_by"] = "unrelated-row"
    with pytest.raises(ValueError):
        prepare_one(payload)


def test_hsp_dt_017_github_aliases_are_one_incident(payload, tmp_path):
    """tc: HSP-DT-017
    spec: retro-hindsight-projection#pattern-evidence-deduplication
    """
    payload["record"]["type"] = "pattern"
    payload["evidence_ids"] = [
        "https://github.com/team/payments/pull/42#discussion-1",
        "TEAM/payments#42",
    ]
    assert prepare_one(payload)["action"] == "skip"
    first = audit(42)
    first["retro_id"] = "https://github.com/team/payments/pull/42"
    rerun = audit(42, invocation="rerun")
    store(tmp_path, "first.json", first)
    store(tmp_path, "rerun.json", rerun)
    review = audit(
        43,
        kind="promotion",
        metrics=[{"source_id": "lesson-a", "retro_id": "TEAM/payments#42", "cited": True}],
    )
    store(tmp_path, "review.json", review)
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 1
    assert result["rates"]["cited"] == {"positive": 1, "observed": 1, "rate": 1.0}


@pytest.mark.parametrize("field", ["project", "id", "key"])
def test_hsp_eg_018_canonical_identity_whitespace_is_rejected(payload, field):
    """tc: HSP-EG-018
    spec: retro-hindsight-projection#unsafe-key
    """
    if field == "project":
        payload["project"] += " "
    else:
        payload["record"][field] += " "
    with pytest.raises(ValueError):
        prepare_one(payload)


def test_hsp_st_019_sqlite_json_tags_generate_tombstone(payload):
    """tc: HSP-ST-019
    spec: retro-hindsight-projection#inactive-record
    """
    payload["previous"] = accepted(prepare_one(payload))
    payload["record"].update(tags='["parked"]', confidence=4)
    result = prepare_one(payload)
    assert result["action"] == "ingest"
    assert json.loads(result["arguments"]["content"])["lifecycle"] == "parked"
    payload["previous"]["content_hash"] = "wrong"
    with pytest.raises(ValueError):
        prepare_one(payload)


def test_hsp_eg_022_empty_cli_path_is_not_current_directory(tmp_path):
    """tc: HSP-EG-022
    spec: retro-hindsight-projection#explicit-audit-path
    """
    command = [sys.executable, str(SCRIPT), "report", "--project", "payments", "--audit-dir"]
    invalid = subprocess.run(command + [""], cwd=tmp_path, capture_output=True, check=False)
    assert invalid.returncode == 2
    explicit = subprocess.run(
        command + ["."], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert explicit.returncode == 0
    assert json.loads(explicit.stdout)["status"] == "insufficient_data"


def test_hsp_eg_023_missing_project_audit_is_not_silently_foreign(tmp_path):
    """tc: HSP-EG-023
    spec: retro-hindsight-projection#measurement-observations
    """
    missing = audit(42)
    del missing["project"]
    store(tmp_path, "missing.json", missing)
    foreign = audit(43)
    foreign["project"] = "another-project"
    store(tmp_path, "foreign.json", foreign)
    result = projection.report(tmp_path, "payments")
    assert result["retro_count"] == 0
    assert [line.split(":", 1)[0] for line in result["excluded"]] == ["missing.json"]


def handoff_batch(payload):
    """同一文件的舊 owner、新 successor 與最初 accepted receipt。"""
    before = {**payload["record"], "id": "a1"}
    receipt = accepted(prepare_one({**payload, "record": before}))
    predecessor = {**before, "superseded_by": "b1"}
    successor = {**before, "id": "b1"}
    return {
        "project": payload["project"],
        "items": [
            {
                "record": successor,
                "summary": "New confirmed finding.",
                "evidence_ids": ["team/pay#43"],
            },
            {"record": predecessor, "summary": "Old finding.", "evidence_ids": ["team/pay#42"]},
        ],
        "receipts": [receipt],
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_hsp_st_024_successor_is_only_document_intent(payload, reverse):
    """tc: HSP-ST-024
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    if reverse:
        batch["items"].reverse()
    plans = projection.prepare(batch)["plans"]
    assert [(p["action"], p["lesson_id"], p["lifecycle"]) for p in plans] == [
        ("ingest", "b1", "active")
    ]
    assert json.loads(plans[0]["arguments"]["content"])["lesson_id"] == "b1"


def test_hsp_st_025_ineligible_successor_withdraws_old_owner(payload):
    """tc: HSP-ST-025
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    batch["items"][0]["record"]["confidence"] = 6
    plans = projection.prepare(batch)["plans"]
    assert [(p["action"], p["lesson_id"], p["lifecycle"]) for p in plans] == [
        ("ingest", "a1", "superseded")
    ]


def test_hsp_st_026_existing_successor_blocks_old_reconciliation(payload):
    """tc: HSP-ST-026
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    batch["receipts"] = [accepted(projection.prepare(batch)["plans"][0])]
    batch["items"][0] = {"record": batch["items"][0]["record"]}
    plans = projection.prepare(batch)["plans"]
    assert [(p["action"], p["lesson_id"], p["lifecycle"]) for p in plans] == [
        ("skip", "b1", "active")
    ]


def test_hsp_eg_027_multiple_active_owners_are_ambiguous(payload):
    """tc: HSP-EG-027
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    batch["items"][1]["record"]["superseded_by"] = None
    batch["receipts"] = []
    with pytest.raises(ValueError):
        projection.prepare(batch)


def test_hsp_eg_028_old_scalar_packet_is_rejected(payload):
    """tc: HSP-EG-028
    spec: retro-hindsight-projection#one-document-intent
    """
    with pytest.raises(ValueError):
        projection.prepare(payload)


def test_hsp_st_029_coalescing_preserves_other_documents(payload):
    """tc: HSP-ST-029
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    batch["items"].append(
        {
            "record": {**payload["record"], "id": "c1", "key": "another-boundary"},
            "summary": "Independent confirmed finding.",
            "evidence_ids": ["team/payments#44"],
        }
    )
    plans = projection.prepare(batch)["plans"]
    assert [(p["source_id"], p["lesson_id"], p["action"]) for p in plans] == [
        ("another-boundary", "c1", "ingest"),
        ("payments-retry-boundary", "b1", "ingest"),
    ]


def test_hsp_eg_030_duplicate_receipts_are_rejected(payload):
    """tc: HSP-EG-030
    spec: retro-hindsight-projection#one-document-intent
    """
    batch = handoff_batch(payload)
    batch["receipts"].append(dict(batch["receipts"][0]))
    with pytest.raises(ValueError):
        projection.prepare(batch)
