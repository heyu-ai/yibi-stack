---
globs: tasks/**/db.py
---
# SQLite DB 層規範

## Class 結構

每個 module 一個 DB class，命名為 `<ModuleName>DB`：

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

## 查詢規範

- 永遠用 `?` 參數化（見 `03-security.md`）
- 回傳 `dict(row)` 而非裸 `sqlite3.Row`
- 動態 WHERE 子句加 `# nosec B608`

## 測試

測試時傳入 `":memory:"` 作為 `db_path`：

```python
db = GmailScanDB(db_path=":memory:")
db.init_db()
```

## CLI 中的 DB 生命週期

在 CLI command function 裡用 try/finally 確保關閉：

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
