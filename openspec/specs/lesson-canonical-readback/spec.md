# lesson-canonical-readback Specification

## Purpose

Provide a read-only Mycelium CLI readback that lists every canonical lesson row for a project by key or lesson id, so the Hindsight projection protocol can decide ownership and lifecycle without opening SQLite directly. It exists because, on some SQLite versions (observed on 3.51.0), a read-only SQLite URI cannot open a WAL-mode database whose shared-memory file is absent, which degraded retrospective projections depending on which interpreter the agent happened to use.

## Requirements

### Requirement: Complete canonical row listing

The mycelium CLI SHALL provide a lessons rows subcommand that takes a required project and one or more lesson keys and/or lesson ids, and SHALL return every lessons-table row whose project equals the given project and whose key or id is in the requested set. The result SHALL include retired rows, parked rows and superseded rows, SHALL include every row when several rows share a key, and SHALL NOT deduplicate or truncate rows. Output SHALL be a single JSON object with schema_version, project, requested keys and ids (deduplicated and sorted), rows ordered by key then ts then id, missing_keys and missing_ids. Each row SHALL carry all lessons-table columns, with tags and files as JSON arrays. Rows SHALL be read by one parameterized query in a single snapshot.

#### Scenario: duplicate-key-rows -- Several rows share one key

- **WHEN** the project has an active row and a retired row with superseded_by set, both with the same key, and that key is requested
- **THEN** the output rows SHALL contain both rows, each with its own id, retired_at and superseded_by.

#### Scenario: inactive-rows-included -- Parked and retired rows are returned

- **WHEN** a requested key belongs to a row whose tags contain parked, and another requested key belongs to a retired row
- **THEN** both rows SHALL appear in the output rows, and tags SHALL be a JSON array.

#### Scenario: missing-identifiers -- Requested identifiers with no rows

- **WHEN** one requested key and one requested id match no row in the project
- **THEN** the command SHALL exit 0, list that key in missing_keys and that id in missing_ids, and still return the rows that did match.

#### Scenario: cross-project-id-excluded -- Id from another project

- **WHEN** a requested id exists only under a different project
- **THEN** that row SHALL NOT be returned and the id SHALL be listed in missing_ids.

---
### Requirement: Read-only open without creating the database

The rows subcommand SHALL open the database with a read-write file URI that does not create missing files, SHALL enable query_only before any query, SHALL NOT change the journal mode, and SHALL NOT create tables. It SHALL succeed on a WAL-mode database whose shared-memory and write-ahead files are absent. The database path SHALL be MYCELIUM_DB_OVERRIDE when set, otherwise the default Mycelium handover database path.

#### Scenario: wal-without-shm -- WAL database without shared-memory file

- **GIVEN** a WAL-mode database that was checkpointed and whose -shm and -wal files were removed
- **WHEN** a read-only SQLite URI open of that database fails with unable to open database file
- **THEN** the rows subcommand SHALL still exit 0 and return the matching rows.

#### Scenario: missing-database -- Database path does not exist

- **WHEN** the configured database path does not exist
- **THEN** the command SHALL exit 3 and the path SHALL still not exist after the command finishes.

#### Scenario: write-rejected -- Connection refuses writes

- **WHEN** an INSERT is attempted on the connection returned by the read-only open function
- **THEN** SQLite SHALL reject it and the lessons table row count SHALL be unchanged.

#### Scenario: missing-lessons-table -- Database without a lessons table

- **WHEN** the database exists but has no lessons table
- **THEN** the command SHALL exit 3 and SHALL NOT create the table.

---
### Requirement: Exit status distinguishes failure from an empty result

The rows subcommand SHALL exit 0 when the query succeeds, including when it returns zero rows. It SHALL exit 2 for invalid arguments: no key and no id, more than 200 keys and ids combined, an empty project, or a key outside the pattern of letters, digits, underscore and hyphen. It SHALL exit 3 when the database is unavailable: missing file, open failure, missing lessons table, or an SQLite error during the query. On exit 3 stdout SHALL be empty and stderr SHALL contain a message starting with [FAIL].

#### Scenario: zero-rows-success -- Successful query with no matches

- **WHEN** every requested key and id matches no row
- **THEN** the command SHALL exit 0 with an empty rows array and all requested identifiers in missing_keys or missing_ids.

#### Scenario: database-unavailable -- Unavailable database is not an empty result

- **WHEN** the database cannot be opened
- **THEN** the command SHALL exit 3 with empty stdout and a [FAIL] line on stderr, and SHALL NOT print an empty rows object.

#### Scenario: invalid-arguments -- Missing or malformed identifiers

- **WHEN** the command is run with no key and no id, with 201 identifiers, or with a key containing a space
- **THEN** the command SHALL exit 2.

---
### Requirement: Effective confidence parity

Each returned row SHALL include effective_confidence computed with the same decay function that the typed lessons show path applies, so a single rows call supplies the confidence used for projection eligibility.

#### Scenario: confidence-matches-show -- Same value as lessons show

- **WHEN** a row is returned by both the rows subcommand and the typed lessons show function for the same database and time
- **THEN** both SHALL report the same effective_confidence.

---
### Requirement: Hindsight protocol readback uses the rows subcommand

The Hindsight projection protocol document SHALL direct canonical readback through one rows subcommand call that passes every candidate key and every previously accepted receipt key and lesson id for the invocation. It SHALL NOT instruct opening the database with a read-only SQLite URI. Any non-zero exit SHALL degrade projection; exit 2 SHALL additionally tell the operator that the installed CLI lacks the rows subcommand or is older than the release that added it, and SHALL name reinstalling from a newer release tag. A requested identifier listed as missing, an absent receipt owner, an ambiguous owner, or several active rows for one key SHALL degrade or reject as before, and readback SHALL NOT interleave with writes.

#### Scenario: protocol-single-call -- One readback call per invocation

- **WHEN** an agent follows the protocol for an invocation with two candidates and one prior receipt
- **THEN** the protocol text SHALL direct one rows call that includes both candidate keys and the receipt key and lesson id, and SHALL NOT contain a SQLite connection string.

#### Scenario: protocol-nonzero-degrades -- Non-zero exit degrades projection

- **WHEN** the rows call exits 2 or 3
- **THEN** the protocol SHALL mark hindsight_sync degraded, publish nothing for the invocation, and for exit 2 name reinstalling the installed CLI.

#### Scenario: protocol-missing-owner-degrades -- Missing receipt owner

- **WHEN** a prior receipt's lesson id appears in missing_ids
- **THEN** the protocol SHALL degrade that document rather than infer a deletion or a new owner.
