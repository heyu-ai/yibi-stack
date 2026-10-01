#!/usr/bin/env python3
"""準備 Hindsight 衍生文件，並彙整真實 retrospective 的觀測結果。

不連線、不修改 Mycelium；MCP 呼叫由執行 skill 的 agent 負責。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
METRICS = ("duplicate", "invalidated", "cited", "false_recurrence")
PR_URL = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)(?:[/?#]\S*)?\Z",
    re.IGNORECASE,
)
PR_SHORT = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#(\d+)\Z")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必須是非空字串")
    return value.strip()


def _identity(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != value:
        raise ValueError(f"{field} 的 canonical identity 不可含首尾空白")
    return text


def _incident_id(value: Any, field: str) -> str:
    """合併已知 GitHub PR 表示法；其他已核實的 session／commit identity 保持原樣。"""
    text = _text(value, field)
    match = PR_URL.fullmatch(text) or PR_SHORT.fullmatch(text)
    if match:
        owner, repo, number = match.groups()
        return f"{owner.lower()}/{repo.lower()}#{int(number)}"
    return text


def _instant(value: Any) -> datetime:
    """用實際時間比較紀錄；沒有時區就無法判定先後，必須拒絕。"""
    try:
        result = datetime.fromisoformat(_text(value, "recorded_at"))
    except ValueError as exc:
        raise ValueError("recorded_at 必須是含時區的 ISO 8601 時間") from exc
    if result.tzinfo is None:
        raise ValueError("recorded_at 不可省略時區")
    return result.astimezone(UTC)


def _path_argument(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("路徑不可為空字串")
    return Path(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _lifecycle(row: dict[str, Any]) -> str:
    tags = row.get("tags")
    if isinstance(tags, str):
        tags = json.loads(tags)
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("record.tags 必須是字串陣列，或該陣列的 JSON 字串")
    if "retired_at" not in row or "superseded_by" not in row:
        raise ValueError("canonical snapshot 必須包含 retired_at 與 superseded_by")
    retired = row["retired_at"]
    superseded = row["superseded_by"]
    for field, value in (("retired_at", retired), ("superseded_by", superseded)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"record.{field} 必須是 null 或非空字串")
    return (
        "retired"
        if retired
        else "superseded"
        if superseded
        else "parked"
        if "parked" in tags
        else "active"
    )


def _receipt_owner(previous: Any, project: str, key: str) -> str:
    if (
        not isinstance(previous, dict)
        or previous.get("project") != project
        or previous.get("source_id") != key
        or previous.get("expected_doc_id") != f"lesson-{key}"
        or previous.get("outcome") != "accepted"
        or not isinstance(previous.get("content_hash"), str)
        or not HASH.fullmatch(previous["content_hash"])
    ):
        raise ValueError("previous 必須是同 project、key 與 document 的 accepted receipt")
    return _identity(previous.get("lesson_id"), "previous.lesson_id")


def _prepare_record(payload: dict[str, Any]) -> dict[str, Any]:
    """僅對符合條件的 canonical snapshot 產生 MCP 可接受的投影。"""
    project = _identity(payload.get("project"), "project")
    row = payload.get("record")
    if not isinstance(row, dict):
        raise ValueError("record 必須是 canonical Mycelium 物件")
    if row.get("project") != project:
        raise ValueError("canonical record 的 project 與要求不符")
    key = _identity(row.get("key"), "record.key")
    if not KEY.fullmatch(key):
        raise ValueError("record.key 必須是小寫 kebab-case，避免文件 ID 衝突")
    lesson_id = _identity(row.get("id"), "record.id")
    lesson_type = _text(row.get("type"), "record.type")
    source = _text(row.get("source"), "record.source")
    confidence = row.get("effective_confidence", row.get("confidence"))
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 10
    ):
        raise ValueError("record confidence 必須是 [0, 10] 的有限數值")
    lifecycle = _lifecycle(row)
    superseded = row["superseded_by"]
    doc_id = f"lesson-{key}"
    previous = payload.get("previous")
    if previous is not None:
        previous_id = _receipt_owner(previous, project, key)
        if previous_id != lesson_id:
            predecessor = payload.get("predecessor")
            if (
                lifecycle != "active"
                or not isinstance(predecessor, dict)
                or predecessor.get("id") != previous_id
                or predecessor.get("project") != project
                or predecessor.get("key") != key
                or predecessor.get("superseded_by") != lesson_id
            ):
                raise ValueError("receipt 屬於其他 canonical 列，且未驗證有效的接替關係")
    evidence = payload.get("evidence_ids", [])
    if not isinstance(evidence, list):
        raise ValueError("evidence_ids 必須是已核實的事故 ID 陣列")
    evidence = sorted({_incident_id(item, "evidence_id") for item in evidence})
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
        # tombstone 使用固定摘要，不因 agent 改寫舊文字而產生無意義的新 revision。
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


def prepare(payload: dict[str, Any]) -> dict[str, Any]:
    """先合併整次 invocation 的意圖，再回傳每份文件最多一個計畫；不接受舊單列格式。"""
    project = _identity(payload.get("project"), "project")
    items = payload.get("items")
    receipts = payload.get("receipts")
    if not isinstance(items, list) or not isinstance(receipts, list):
        raise ValueError("prepare 必須接收整次 invocation 的 items 與 receipts 陣列")

    by_id: dict[str, dict[str, Any]] = {}
    by_key: dict[str, list[str]] = {}
    states: dict[str, str] = {}
    candidates: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("record"), dict):
            raise ValueError("每個 item 必須包含 canonical record")
        row = item["record"]
        if row.get("project") != project:
            raise ValueError("canonical record 的 project 與要求不符")
        lesson_id = _identity(row.get("id"), "record.id")
        key = _identity(row.get("key"), "record.key")
        if not KEY.fullmatch(key):
            raise ValueError("record.key 必須是小寫 kebab-case")
        if lesson_id in by_id:
            raise ValueError("同一次 invocation 不可重複提供 canonical lesson ID")
        by_id[lesson_id] = row
        by_key.setdefault(key, []).append(lesson_id)
        states[lesson_id] = _lifecycle(row)
        if "summary" in item or "evidence_ids" in item:
            candidates[lesson_id] = item

    previous_by_key: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ValueError("receipt 必須是物件")
        key = _identity(receipt.get("source_id"), "receipt.source_id")
        owner_id = _receipt_owner(receipt, project, key)
        if key in previous_by_key:
            raise ValueError("每份文件只可提供最新的一份 accepted receipt")
        if owner_id not in by_id or by_id[owner_id]["key"] != key:
            raise ValueError("缺少 receipt owner 的同 project/key canonical readback")
        previous_by_key[key] = receipt

    keys = set(previous_by_key)
    keys.update(by_id[lesson_id]["key"] for lesson_id in candidates)
    plans = []
    for key in sorted(keys):
        row_ids = by_key[key]
        active_ids = [lesson_id for lesson_id in row_ids if states[lesson_id] == "active"]
        if len(active_ids) > 1:
            raise ValueError(f"{key} 有多個 active canonical rows，不能判定文件歸屬")
        previous = previous_by_key.get(key)
        owner = by_id[previous["lesson_id"]] if previous else None
        candidate_plan = None
        if active_ids and active_ids[0] in candidates:
            item = candidates[active_ids[0]]
            candidate_plan = _prepare_record(
                {
                    **item,
                    "project": project,
                    "previous": previous,
                    "predecessor": owner,
                }
            )
            if (
                candidate_plan["action"] == "ingest"
                or candidate_plan.get("reason") == "same_accepted_revision"
            ):
                # successor 的最終意圖勝出；不再為同 doc 產生舊列 tombstone。
                plans.append(candidate_plan)
                continue
        if owner is not None and states[owner["id"]] != "active":
            plans.append(
                _prepare_record({"project": project, "record": owner, "previous": previous})
            )
        elif candidate_plan is not None:
            plans.append(candidate_plan)
        elif owner is not None:
            if previous.get("lifecycle") != "active":
                raise ValueError("恢復 active 投影需要該 owner 的已核實候選摘要與證據")
            plans.append(
                {
                    "project": project,
                    "source_id": key,
                    "lesson_id": owner["id"],
                    "expected_doc_id": f"lesson-{key}",
                    "lifecycle": "active",
                    "action": "skip",
                    "reason": "active_owner_unchanged",
                }
            )
        else:
            candidate_id = next(
                lesson_id for lesson_id in sorted(row_ids) if lesson_id in candidates
            )
            plans.append(_prepare_record({**candidates[candidate_id], "project": project}))
    return {"project": project, "plans": plans}


def report(directory: Path, project: str) -> dict[str, Any]:
    """彙整已觀測結果；未知值不當成 false 或零。"""
    project = _identity(project, "project")
    if not directory.is_dir():
        raise ValueError("audit 目錄不存在")
    invocations: dict[str, tuple[datetime, dict[str, Any]]] = {}
    excluded: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("audit 必須是物件")
            audit_project = _identity(doc.get("project"), "audit.project")
            if audit_project != project or doc.get("sample_kind") == "smoke":
                continue
            if doc.get("schema_version") != 1 or doc.get("sample_kind") != "live":
                raise ValueError("audit schema 不支援或 sample_kind 不明")
            invocation_id = _identity(doc.get("invocation_id"), "invocation_id")
            recorded_at = _instant(doc.get("recorded_at"))
            if doc.get("kind") not in ("retro", "promotion"):
                raise ValueError("invocation kind 不明")
            if doc["kind"] == "retro":
                doc["retro_id"] = _incident_id(doc.get("retro_id"), "retro_id")
                if type(doc.get("canonical_written")) is not bool:
                    raise ValueError("retro audit 必須有 canonical_written 布林值")
            if not isinstance(doc.get("metrics"), list) or not isinstance(doc.get("events"), list):
                raise ValueError("metrics 與 events 必須是陣列")
            for event in doc["events"]:
                if not isinstance(event, dict):
                    raise ValueError("event 必須是物件")
                _text(event.get("operation"), "event.operation")
                if event.get("outcome") not in (
                    "pending",
                    "success",
                    "accepted",
                    "failed",
                    "degraded",
                    "skipped",
                ):
                    raise ValueError("event outcome 不明")
            for metric in doc["metrics"]:
                if not isinstance(metric, dict):
                    raise ValueError("metric 必須是物件")
                metric["source_id"] = _identity(metric.get("source_id"), "metric.source_id")
                metric["retro_id"] = _incident_id(
                    metric.get("retro_id", doc.get("retro_id")), "metric.retro_id"
                )
                if any(
                    metric.get(name) is not None and type(metric[name]) is not bool
                    for name in METRICS
                ):
                    raise ValueError("observations 必須是布林值或 null")
            old = invocations.get(invocation_id)
            if old is None or recorded_at > old[0]:
                invocations[invocation_id] = (recorded_at, doc)
        except (OSError, ValueError) as exc:
            excluded.append(f"{path.name}: {exc}")
    rows = [
        doc
        for _, doc in sorted(
            invocations.values(), key=lambda item: (item[0], item[1]["invocation_id"])
        )
    ]
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
    """CLI 入口：無效輸入明確失敗，不冒充 MCP 成功。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--input", type=_path_argument, required=True)
    prep.add_argument("--output", type=_path_argument, required=True)
    measurement = commands.add_parser("report")
    measurement.add_argument("--audit-dir", type=_path_argument, required=True)
    measurement.add_argument("--project", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("input 必須是物件")
            value = prepare(payload)
            args.output.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            value = report(args.audit_dir, args.project)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        print(f"[DEGRADED] Hindsight 投影：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
