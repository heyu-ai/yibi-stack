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
