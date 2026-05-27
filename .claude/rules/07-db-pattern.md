---
globs: tasks/**/db.py
---
# SQLite DB Layer Pattern

## Class Structure

One DB class per module, named `<ModuleName>DB`:

```python
class GmailScanDB:
    """Gmail 掃描歷史 SQLite 資料庫。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or RUNTIME_DIR / "gmail_scan.db")
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy 連線，首次存取時建立。"""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_db(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ...
            );
            CREATE INDEX IF NOT EXISTS idx_scan_results_date
                ON scan_results(scan_date);
        """)
        self.conn.commit()
```

## Query Rules

- Always use `?` parameterization (see `03-security.md`)
- Return `dict(row)` instead of bare `sqlite3.Row`
- Dynamic WHERE clauses must have `# nosec B608`

## Testing

Pass `":memory:"` as `db_path` for tests:

```python
db = GmailScanDB(db_path=":memory:")
db.init_db()
```

## DB Lifecycle in CLI

Use try/finally in CLI command functions to ensure the connection is closed:

```python
@cli.command()
def status() -> None:
    db = GmailScanDB()
    try:
        db.init_db()
        ...
    finally:
        db.close()
```

## Multi-Source Dedup: Isolate Key-Space Across Sources

When merging records from multiple sources (e.g., typed DB + legacy text) into a
single dedup pass, the key generation for each source must use a distinct prefix
namespace — otherwise synthesized keys can silently overwrite authored keys.

```python
# Wrong: truncated legacy text can collide with a typed lesson key
{"key": text[:40].replace(" ", "-").lower(), "type": "pattern"}

# Correct: "legacy-" prefix isolates the namespace from typed keys
{"key": f"legacy-{text[:34].replace(' ', '-').lower()}", "type": "pattern"}
```

Dedup-within-source is unaffected: the same input text always produces the same
prefixed key, so identical legacy entries across multiple records still dedup.
Typed lessons (explicitly authored keys) are isolated and cannot be overwritten.

## Idempotent Schema Migration

For adding new columns to an existing table, prefer `ALTER TABLE ADD COLUMN` with a
default value over full migration scripts — existing rows automatically get the default,
no backfill required:

```python
def _run_migrations(conn: sqlite3.Connection) -> None:
    for col, default in [
        ("source_bot", "''"),
        ("tier", "'working'"),
        ("access_count", "0"),
    ]:
        try:
            conn.execute(  # nosec B608
                f"ALTER TABLE lessons ADD COLUMN {col} TEXT DEFAULT {default}"
            )
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    conn.commit()
```

- Safe to run multiple times (idempotent)
- No data backfill for existing rows; SQLite fills defaults at read time
- Scope: **column additions only** — renaming or dropping columns still requires a
  dedicated migration with careful data preservation
