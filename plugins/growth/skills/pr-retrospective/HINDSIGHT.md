# Hindsight integration protocol

Used by pr-retrospective and lesson-promotion. Mycelium is the canonical ledger; Hindsight is a
derived index, never a source of lifecycle authority. The invoking agent performs MCP calls; the
bundled helper only prepares deterministic JSON and reports observations. Do not call HTTP or invent
MCP parameters to bypass missing capabilities.

## Availability and call receipts

1. Create a unique invocation UUID and an audit file under
   `~/.agents/hindsight-retro/<project>/<invocation_id>.json`. Resolve project from the main Git
   repository (worktrees share it), not the worktree branch name. Record `kind=retro` or
   `promotion`; use a repo-qualified PR URL or a stable session ID as `retro_id`, not a new ID on
   every retry. Use `sample_kind=live` for actual work and `smoke` for exercises. Do not put
   credentials or transcripts in receipts. Store files with owner-only access; atomically replace
   only this invocation's file after each update.
2. Once per invocation, inspect available tool schemas. Required base tools: diagnose, list, search,
   read. Optional operations require their own advertised tool. Initialize
   `HINDSIGHT_AVAILABLE=false`; never assume an endpoint/port from another installation.
3. Call `hindsight_diagnose({})` and verify the resolved workspace/bank belongs to the target
   project. A shared multi-project bank is unsafe for the fixed `[Lesson] <key>` title: permit
   read-only advice with project-verified sources, but skip lesson publication/reconciliation unless
   the bank is dedicated to this canonical project. A diagnostic is local configuration, not server
   liveness proof.
4. Call `hindsight_list_knowledge_pages({})` once with the host's bounded tool timeout. Success
   (including an empty list) establishes read availability. Errors, missing tools, wrong workspace,
   timeout, MCP `isError`, or a returned error object produce `[DEGRADED] Hindsight unavailable;
   continuing Mycelium-only; hindsight_sync=skipped`. Cache the result; do not probe again for each
   lesson.
5. All calls use the wrapper discipline below. A transport/server failure disables remaining calls
   for this invocation. Missing an optional reflect/ingest/capture capability degrades that
   operation only. Never let a Hindsight error skip an original Mycelium step, override an
   Evidence/Promotion Gate, or trigger a canonical lifecycle mutation.

For **each** call, append an event with a unique `event_id`, operation, subject identity,
`outcome=pending`, `page_ids=[]`, `fallback=false`, `human_decision=not_applicable`, and UTC
timestamp **before** issuing it. Replace that event's outcome after return (do not append a
duplicate result event):

| Result | Receipt | Action |
|---|---|---|
| Successful read | `success` + returned candidate page IDs | Continue |
| Ingest returns `ok=true` and expected `doc_id` | `accepted` | Store projection receipt; indexing is still asynchronous |
| Capture returns a real page ID | `accepted` + page ID | Store initiative identity/page receipt; not proof of synthesized content |
| Missing capability | `skipped`, `fallback=true` | Continue original workflow |
| Failure or timeout | `failed`, `fallback=true` + concise reason | Mark invocation degraded; stop further Hindsight calls |
| Interrupted invocation | Leave event `pending` | Outcome unknown; never classify it as a failed/no-write operation |

When audit persistence fails, stop optional Hindsight calls and report degraded; do not perform
unaudited writes. Do not automatically retry timed-out writes: a page/document operation could have
been accepted. In particular, never retry initiative creation blindly. A subsequent invocation can
reconcile from canonical data and exact page identity after resolving the pending operation.

### Actual MCP argument shapes

- `hindsight_search_knowledge_pages({query})` — there is no `limit` argument. Screen provenance, then inspect at most three eligible candidates locally.
- `hindsight_read_knowledge_page({page_id})` — inspect full content when the snippet lacks provenance/incident IDs.
- `hindsight_reflect({query})` — only for high-value, strongly similar but ambiguous/contradictory candidates. Reflected prose is not independent evidence.
- `hindsight_ingest_document({title, content})` — no native metadata, document_id, operation_id, or append-to-page parameters.
- `hindsight_capture_initiative({title, summary, relates_to_page_id?})` — existing initiative updates require the page ID. New calls are not inherently idempotent.

Page titles can appear as `page`, `name`, or `title` depending on the read/list/search response.
Exclude any `[Lesson]` title, any `source_system=mycelium` envelope, and any synthesized paragraph
derived from such a projection. Unknown provenance is not an independent incident. Verify incident
pointers against their actual PR/session sources; two snippets, commits, or summaries describing the
same incident count once. Preserve the evidence pointers and the human recurrence decision in the
audit. Credit useful retrieved memory in human-facing answers, not irrelevant search hits.

## Canonical projection and lifecycle reconciliation

Only perform new retro projections **after** the user accepted the retro and **all required Step 5
canonical mutations succeeded**. Cancelled/failed canonical writes publish neither new lessons nor
initiative outcomes. Step 4b only prepares mutations; it is not a publication point. Read back the
actual stored lesson even if `--skip-if-exists` returned success. Never project the prepared CLI
arguments in place of that readback.

1. Read prior accepted projection receipts for this project across earlier audit files. Receipts are
   delivery bookkeeping, not lesson authority. Keep the latest known accepted receipt per document
   and its canonical `lesson_id`. A pending/unknown write for the same identity must be resolved
   before another write; otherwise mark degraded. Do not count acceptance as `synced`.
2. Read the current canonical record for each new lesson and each previously projected ID. For
   normal lookup, use installed `mycelium lessons show --project <project> --no-include-legacy
   --include-retired --include-parked --min-confidence 0 --last 10000 --json`. This API deduplicates
   and caps results; **a missing row is not evidence of retirement/deletion**.
3. For lifecycle reconciliation, read exact IDs from the same canonical SQLite database using
   read-only mode and bound project/id parameters. Respect `MYCELIUM_DB_OVERRIDE` if configured;
   otherwise the database is `~/.agents/handover/handover.db`. Do not initialize a missing DB or
   import checkout tasks. The query is `SELECT * FROM lessons WHERE project = ? AND id = ?`.
   Read-only SQLite connection example: `sqlite3.connect(path.resolve().as_uri() + '?mode=ro',
   uri=True)`. Zero/multiple matches, missing lifecycle columns, malformed tags or unavailable
   database => degraded; do not fabricate a tombstone. Confirm any same-key replacement via
   `superseded_by` and canonical identity; do not overwrite an active replacement's document using
   an older row's tombstone. If a key maps to conflicting active rows/types, skip as ambiguous
   rather than choosing one arbitrarily.
4. Confirm the source pointers and derive a short background summary (not a copy of full insight).
   Normalize an incident's multiple representations to one repo-qualified PR/session identity. For a
   pitfall, a standalone verified commit can be an incident pointer; a pattern requires two distinct
   incident IDs, not two commits in one PR. A source marked inferred cannot pass the pitfall gate
   merely because it includes a URL.
5. Build an input JSON file using the canonical row and the following shape. `previous` is null for
   a never-published identity; otherwise it is the actual accepted receipt, not a result merely
   prepared earlier.

```json
{
  "project": "payments",
  "record": {
    "id": "canonical-lesson-id",
    "project": "payments",
    "key": "payments-retry-boundary",
    "type": "pitfall",
    "source": "observed",
    "confidence": 8,
    "tags": [],
    "retired_at": null,
    "superseded_by": null
  },
  "summary": "A timeout after acceptance is not evidence that a write did not occur.",
  "evidence_ids": ["https://github.com/team/payments/pull/42"],
  "previous": null
}
```

Use file tools to write this JSON; do not embed user/lesson text in shell strings. Execute the installed helper from the resolved `RETRO_ROOT`:

```bash
python3 "$RETRO_ROOT/scripts/hindsight_projection.py" prepare --input "$INPUT_FILE" --output "$OUTPUT_FILE"
```

Exit 2 means invalid/missing input or I/O failure: record degraded, ignore any old output file, and do not call MCP. Exit 0 yields:

| `action` | Handling |
|---|---|
| `skip` | Record reason; no ingest call |
| `ingest` | Recheck canonical row has not changed since preparation; call ingest with exactly `arguments` |

The helper rejects project mismatch, unsafe keys (only lowercase kebab-case), malformed
canonical/lifecycle fields, and foreign/unaccepted receipts. Active publication requires effective
confidence (when exported) or confidence >=7 and either a non-inferred pitfall with incident
evidence, or a pattern with >=2 unique verified incident IDs. Parked/superseded/retired rows cannot
create a first active projection. A **previously published** inactive row emits a tombstone even if
confidence is now low; it keeps the same title/doc ID. Do not independently change Mycelium
lifecycle to make a lesson eligible.

For a successful call, check `ok=true` and returned `doc_id == expected_doc_id`. A mismatch is
degraded, not an accepted receipt. Save the preparation result minus `arguments`, adding
`outcome=accepted`, canonical `lesson_id`, originating `retro_id` and `accepted_at`. Never save an
accepted receipt when the call fails or times out. These receipts are used by the next retro **or
promotion invocation**, even when there are no new candidates. Retain the audit history; do not
delete it as temporary scratch data.

### Stable identity, not native idempotency

The current MCP derives `lesson-payments-retry-boundary` from `[Lesson] payments-retry-boundary` and
retains against that document ID. Changed content replaces the same logical document; repeated
identical accepted content is skipped by the helper. This is **not** exactly-once operation
execution, nor a concurrency lock. The content envelope contains `source_system`, `source_id`,
`project`, `lesson_id`, `lifecycle`, `summary`, `evidence_ids`, `superseded_by`, `content_hash`, and
`revision_key`. Hashing uses UTF-8 canonical JSON with sorted keys, compact separators and unescaped
Unicode, excluding `content_hash`/`revision_key` themselves.

Provenance fields live in **content**, not native server metadata. The revision key
`mycelium:<project>:<key>:<sha256>` is logical provenance, not an MCP argument. Do not add the hash
to the title: that would create one document per revision and leave obsolete active documents
behind. Do not append directly to a synthesized knowledge page: this MCP cannot do that. Retained
documents feed Hindsight's existing topic-page synthesis; those pages can lag, and new tombstones do
not prove old observations have already disappeared. Retrieval must still check canonical lifecycle
and projection provenance.

## Human decisions and measurement

Before promotion routing, inspect canonical ADR/rules/specs and then Hindsight. Populate
`possible_duplicate` and `possible_contradiction` with source/page IDs; leave human decisions
pending until answered. Similar memory is not proof of an existing rule, nor proof of a duplicate
Mycelium row. Contradictions require an explicit choice: correct the lesson to respect the canonical
decision, or enter the ADR/spec change process. Record accepted/rejected/deferred decisions without
automatically changing confidence, parking, retiring or merging lessons.

Audit shape (write actual values, no fabricated results):

```json
{
  "schema_version": 1,
  "invocation_id": "unique-uuid",
  "project": "payments",
  "kind": "retro",
  "canonical_written": false,
  "sample_kind": "live",
  "retro_id": "https://github.com/team/payments/pull/42",
  "recorded_at": "2026-09-30T12:00:00Z",
  "hindsight_sync": "queued",
  "events": [],
  "projections": [],
  "decisions": [],
  "metrics": []
}
```

`hindsight_sync` is queued/skipped/degraded (never inferred as synced). Each metric row identifies
`source_id` and the **originating** `retro_id`; values for `duplicate`, `invalidated`, `cited`,
`false_recurrence` are boolean observations or null/absent for unknown. A promotion invocation uses
`kind=promotion`; it can add observations about an earlier retro but does not count as a new retro.
Update `recorded_at` in UTC whenever writing the audit.

Initialize `canonical_written=false` at preflight. For a retro, set it to true only after
the confirmed Step 4 retrospective was successfully persisted; cancellation or write failure
leaves it false. The report counts only live retros with `canonical_written=true`, so opening
or cancelling thirty sessions cannot satisfy the thirty-retro threshold. Promotion receipts
do not need this field and never count as retros.

- `duplicate`: a post-publication human review found an equivalent projection; do not count the prepublication same-revision skip as a duplicate.
- `invalidated`: a published lesson was later parked/superseded/retired; a current active state alone is not proof it will never be invalidated.
- `cited`: subsequent retrieval actually used that projection as background with a source citation (not as independent recurrence evidence).
- `false_recurrence`: a human rejected an earlier recurrence claim because it was projection feedback or the same incident recounted twice.

Record true or false only when that question was actually evaluated. Each rate's denominator is the
number of evaluated `(retro_id, source_id)` pairs, not all published lessons; unknown is never
silently false. Set explicit false after a reviewed non-event if appropriate, not by default. Keep
candidate page IDs, source pointers, fallback usage and human outcome in events/decisions so
measurements can be audited. Subsequent live invocations supply later observations; a completed run
with no events still counts only if an actual retro was performed.

```bash
python3 "$RETRO_ROOT/scripts/hindsight_projection.py" report --audit-dir "$AUDIT_DIR" --project "$ORIG_PROJECT"
```

Run this at the end of each invocation. Exit 2 => measurement degraded, preserve canonical results.
It deduplicates invocation IDs and counts distinct retro IDs, excludes smoke/other-project audits,
and returns rates with observed denominators. `measurement_ready=true` requires at least 30 distinct
real retros; rates with zero observations stay null. Before then report `insufficient_data`, the
current count and unknown denominators, not an effectiveness claim. Malformed audit files are listed
in `excluded`; do not silently claim full coverage. After 30, present the real report for human
tuning; do not generate retrospective history just to hit the threshold.
