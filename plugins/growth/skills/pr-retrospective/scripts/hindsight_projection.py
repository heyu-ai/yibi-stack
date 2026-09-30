#!/usr/bin/env python3
"""Prepare derived Hindsight documents and report real retrospective observations.

No network or Mycelium mutations. MCP calls remain the invoking agent's job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
METRICS = ("duplicate", "invalidated", "cited", "false_recurrence")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prepare(payload: dict[str, Any]) -> dict[str, Any]:
    """Return an MCP-ready projection only from an eligible canonical snapshot."""
    project = _text(payload.get("project"), "project")
    row = payload.get("record")
    if not isinstance(row, dict):
        raise ValueError("record must be a canonical Mycelium object")
    if row.get("project") != project:
        raise ValueError("canonical record project differs from requested project")
    key = _text(row.get("key"), "record.key")
    if not KEY.fullmatch(key):
        raise ValueError("record.key must be lowercase kebab-case to avoid document ID collisions")
    lesson_id = _text(row.get("id"), "record.id")
    lesson_type = _text(row.get("type"), "record.type")
    source = _text(row.get("source"), "record.source")
    confidence = row.get("effective_confidence", row.get("confidence"))
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 10
    ):
        raise ValueError("record confidence must be a finite number in [0, 10]")
    tags = row.get("tags")
    if isinstance(tags, str):
        tags = json.loads(tags)
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("record.tags must be a JSON string array or an array of strings")
    # Export must include lifecycle columns: absent is unknown, not active.
    if "retired_at" not in row or "superseded_by" not in row:
        raise ValueError("canonical snapshot must include retired_at and superseded_by")
    retired = row["retired_at"]
    superseded = row["superseded_by"]
    for field, value in (("retired_at", retired), ("superseded_by", superseded)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"record.{field} must be null or a nonempty string")
    lifecycle = (
        "retired"
        if retired
        else "superseded"
        if superseded
        else "parked"
        if "parked" in tags
        else "active"
    )
    doc_id = f"lesson-{key}"
    previous = payload.get("previous")
    if previous is not None and (
        not isinstance(previous, dict)
        or (
            previous.get("project") != project
            or previous.get("source_id") != key
            or previous.get("expected_doc_id") != doc_id
            or previous.get("outcome") != "accepted"
            or not isinstance(previous.get("content_hash"), str)
            or not HASH.fullmatch(previous["content_hash"])
        )
    ):
        raise ValueError("previous must be an accepted receipt for this project, key and document")
    evidence = payload.get("evidence_ids", [])
    if not isinstance(evidence, list):
        raise ValueError("evidence_ids must be an array of verified incident IDs")
    evidence = sorted({_text(item, "evidence_id") for item in evidence})
    base = {
        "project": project,
        "source_id": key,
        "lesson_id": lesson_id,
        "expected_doc_id": doc_id,
        "lifecycle": lifecycle,
    }
    if lifecycle != "active":
        if previous is None:
            return {**base, "action": "skip", "reason": "inactive_without_previous_projection"}
        summary = (
            f"Canonical Mycelium lesson is {lifecycle}. "
            "Do not use it as active guidance or recurrence evidence."
        )
        # Stable tombstones do not depend on an agent rephrasing the old summary.
        evidence = []
    else:
        eligible = confidence >= 7 and (
            (lesson_type == "pitfall" and source != "inferred" and bool(evidence))
            or (lesson_type == "pattern" and len(evidence) >= 2)
        )
        if not eligible:
            return {**base, "action": "skip", "reason": "publication_threshold_not_met"}
        summary = _text(payload.get("summary"), "summary")
    envelope = {
        "schema_version": 1,
        "source_system": "mycelium",
        "source_id": key,
        "project": project,
        "lesson_id": lesson_id,
        "lifecycle": lifecycle,
        "superseded_by": superseded,
        "summary": summary,
        "evidence_ids": evidence,
    }
    content_hash = hashlib.sha256(_json(envelope).encode("utf-8")).hexdigest()
    revision_key = f"mycelium:{project}:{key}:{content_hash}"
    result = {**base, "content_hash": content_hash, "revision_key": revision_key}
    if previous and previous["content_hash"] == content_hash:
        return {**result, "action": "skip", "reason": "same_accepted_revision"}
    envelope.update(content_hash=content_hash, revision_key=revision_key)
    return {
        **result,
        "action": "ingest",
        "arguments": {"title": f"[Lesson] {key}", "content": _json(envelope)},
    }


def report(directory: Path, project: str) -> dict[str, Any]:
    """Aggregate observed outcomes; missing measurements are never false/zero."""
    if not directory.is_dir():
        raise ValueError("audit directory does not exist")
    invocations: dict[str, dict[str, Any]] = {}
    excluded: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("audit must be an object")
            if doc.get("project") != project or doc.get("sample_kind") == "smoke":
                continue
            if doc.get("schema_version") != 1 or doc.get("sample_kind") != "live":
                raise ValueError("unsupported audit schema or unknown sample_kind")
            invocation_id = _text(doc.get("invocation_id"), "invocation_id")
            _text(doc.get("recorded_at"), "recorded_at")
            if doc.get("kind") not in ("retro", "promotion"):
                raise ValueError("unknown invocation kind")
            if doc["kind"] == "retro":
                _text(doc.get("retro_id"), "retro_id")
                if type(doc.get("canonical_written")) is not bool:
                    raise ValueError("retro audit requires a canonical_written boolean")
            if not isinstance(doc.get("metrics"), list) or not isinstance(doc.get("events"), list):
                raise ValueError("metrics and events must be arrays")
            for event in doc["events"]:
                if not isinstance(event, dict):
                    raise ValueError("event must be an object")
                _text(event.get("operation"), "event.operation")
                if event.get("outcome") not in (
                    "pending",
                    "success",
                    "accepted",
                    "failed",
                    "degraded",
                    "skipped",
                ):
                    raise ValueError("unknown event outcome")
            for metric in doc["metrics"]:
                if not isinstance(metric, dict):
                    raise ValueError("metric must be an object")
                _text(metric.get("source_id"), "metric.source_id")
                _text(metric.get("retro_id", doc.get("retro_id")), "metric.retro_id")
                if any(
                    metric.get(name) is not None and type(metric[name]) is not bool
                    for name in METRICS
                ):
                    raise ValueError("observations must be booleans or null")
            old = invocations.get(invocation_id)
            if old is None or doc["recorded_at"] > old["recorded_at"]:
                invocations[invocation_id] = doc
        except (OSError, ValueError) as exc:
            excluded.append(f"{path.name}: {exc}")
    rows = sorted(
        invocations.values(), key=lambda item: (item["recorded_at"], item["invocation_id"])
    )
    retros = {
        row["retro_id"] for row in rows if row["kind"] == "retro" and row["canonical_written"]
    }
    observations: dict[tuple[str, str, str], bool] = {}
    call_counts: dict[str, int] = {}
    for row in rows:
        for event in row["events"]:
            outcome = event["outcome"]
            call_counts[outcome] = call_counts.get(outcome, 0) + 1
        for metric in row["metrics"]:
            retro_id = metric.get("retro_id", row.get("retro_id"))
            if retro_id not in retros:
                continue
            for name in METRICS:
                if metric.get(name) is not None:
                    observations[(retro_id, metric["source_id"], name)] = metric[name]
    rates = {}
    for name in METRICS:
        values = [value for (_, _, metric), value in observations.items() if metric == name]
        rates[name] = {
            "positive": sum(values),
            "observed": len(values),
            "rate": sum(values) / len(values) if values else None,
        }
    return {
        "project": project,
        "retro_count": len(retros),
        "invocation_count": len(rows),
        "measurement_ready": len(retros) >= 30,
        "status": "ready" if len(retros) >= 30 else "insufficient_data",
        "rates": rates,
        "call_outcomes": call_counts,
        "excluded": excluded,
    }


def main() -> int:
    """CLI entrypoint with explicit invalid-input failure, not fake MCP success."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--input", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    measurement = commands.add_parser("report")
    measurement.add_argument("--audit-dir", type=Path, required=True)
    measurement.add_argument("--project", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("input must be an object")
            value = prepare(payload)
            args.output.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            value = report(args.audit_dir, args.project)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        print(f"[DEGRADED] Hindsight projection: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
