"""AgentsDB：handover SQLite 資料庫層。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import HANDOVER_DB_PATH
from .models import EventType, HandoverEvent, HandoverRecord, SessionType

_JSON_ARRAY_COLS = (
    "completed",
    "decisions",
    "blocked",
    "next_priorities",
    "lessons_learned",
    "attempted_approaches",
    "tags",
    "last_files",
)


class AgentsDB:
    """Handover SQLite：lazy connect、WAL 模式、自動建表。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or HANDOVER_DB_PATH)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # :memory: 不需要建父目錄
            if self._db_path != ":memory:":
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_db(self) -> None:
        """建立 handovers table 與索引（冪等）。

        schema 與舊 `skills/handover/scripts/init_db.sh` 相容，另加 project 欄位。
        """
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS handovers (
              id                   TEXT PRIMARY KEY,
              timestamp            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
              operator             TEXT NOT NULL DEFAULT 'howie',
              session_type         TEXT NOT NULL
                                   CHECK(session_type IN ('sdd','debug','discussion','admin')),
              topic                TEXT NOT NULL,
              conversation_summary TEXT NOT NULL,
              completed            TEXT NOT NULL DEFAULT '[]',
              decisions            TEXT NOT NULL DEFAULT '[]',
              blocked              TEXT NOT NULL DEFAULT '[]',
              next_priorities      TEXT NOT NULL DEFAULT '[]',
              lessons_learned      TEXT NOT NULL DEFAULT '[]',
              attempted_approaches TEXT NOT NULL DEFAULT '[]',
              tags                 TEXT NOT NULL DEFAULT '[]',
              device               TEXT,
              agent_type           TEXT DEFAULT 'claude',
              subscription_account TEXT,
              branch               TEXT,
              working_dir          TEXT,
              last_files           TEXT DEFAULT '[]',
              test_status          TEXT,
              token_usage_estimate TEXT,
              project              TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_handovers_timestamp
              ON handovers(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_handovers_topic
              ON handovers(topic);
            CREATE INDEX IF NOT EXISTS idx_handovers_session_type
              ON handovers(session_type);
            CREATE INDEX IF NOT EXISTS idx_handovers_tags ON handovers(tags);
            CREATE INDEX IF NOT EXISTS idx_handovers_project ON handovers(project);
            CREATE INDEX IF NOT EXISTS idx_handovers_account
              ON handovers(subscription_account);

            CREATE TABLE IF NOT EXISTS handover_events (
              id            TEXT PRIMARY KEY,
              timestamp     TEXT NOT NULL,
              session_id    TEXT,
              event_type    TEXT NOT NULL,
              source_layer  TEXT,
              matcher       TEXT,
              handover_id   TEXT,
              project       TEXT,
              device        TEXT,
              extra_json    TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_events_timestamp
              ON handover_events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_events_session
              ON handover_events(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_type
              ON handover_events(event_type);
            """
        )
        self.conn.commit()

    def insert_handover(self, record: HandoverRecord) -> None:
        """寫入一筆 handover；`id` 衝突時 raise sqlite3.IntegrityError（呼叫端處理）。"""
        self.conn.execute(
            """
            INSERT INTO handovers (
              id, timestamp, operator, session_type, topic, conversation_summary,
              completed, decisions, blocked, next_priorities,
              lessons_learned, attempted_approaches, tags,
              device, agent_type, subscription_account,
              branch, working_dir, last_files, test_status, token_usage_estimate, project
            ) VALUES (
              ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record.id,
                record.timestamp,
                record.operator,
                record.session_type.value,
                record.topic,
                record.conversation_summary,
                json.dumps(record.completed, ensure_ascii=False),
                json.dumps(record.decisions, ensure_ascii=False),
                json.dumps(record.blocked, ensure_ascii=False),
                json.dumps(record.next_priorities, ensure_ascii=False),
                json.dumps(record.lessons_learned, ensure_ascii=False),
                json.dumps(record.attempted_approaches, ensure_ascii=False),
                json.dumps(record.tags, ensure_ascii=False),
                record.device,
                record.agent_type,
                record.subscription_account,
                record.branch,
                record.working_dir,
                json.dumps(record.last_files, ensure_ascii=False),
                record.test_status,
                record.token_usage_estimate,
                record.project,
            ),
        )
        self.conn.commit()

    def upsert_handover(self, record: HandoverRecord) -> None:
        """寫入或更新（migrate 用：同 id 視為相同記錄，跳過）。"""
        try:
            self.insert_handover(record)
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: handovers.id" not in str(e):
                raise  # 非重複 id 的 IntegrityError（如 NOT NULL、CHECK），照常拋出

    def read_recent(
        self,
        last: int = 4,
        project: str | None = None,
        exclude_tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """取最近 N 筆，回傳 dict list（JSON array 欄位已 decode）。"""
        if last <= 0:
            raise ValueError("last 必須為正整數")
        conditions: list[str] = []
        params: list[object] = []
        if project:
            conditions.append("project = ?")
            params.append(project)
        for tag in exclude_tags or []:
            conditions.append("tags NOT LIKE ? ESCAPE '\\'")
            params.append(f'%"{_escape_like(tag)}"%')
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
        sql = f"SELECT * FROM handovers {where} ORDER BY timestamp DESC LIMIT ?"  # nosec B608
        params.append(last)
        cur = self.conn.execute(sql, params)
        return [_decode_row(row) for row in cur.fetchall()]

    def search(
        self,
        query: str | None = None,
        session_type: SessionType | None = None,
        project: str | None = None,
        account: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """多條件搜尋：topic / summary / tags / lessons / approaches LIKE，
        搭配 session_type、project、account 等精確匹配。"""
        if limit <= 0:
            raise ValueError("limit 必須為正整數")

        conditions: list[str] = []
        params: list[object] = []

        if query:
            like = f"%{query.lower()}%"
            conditions.append(
                "("
                "LOWER(topic) LIKE ? OR "
                "LOWER(conversation_summary) LIKE ? OR "
                "LOWER(tags) LIKE ? OR "
                "LOWER(lessons_learned) LIKE ? OR "
                "LOWER(attempted_approaches) LIKE ?"
                ")"
            )
            params.extend([like, like, like, like, like])

        if session_type is not None:
            conditions.append("session_type = ?")
            params.append(session_type.value)

        if project:
            conditions.append("project = ?")
            params.append(project)

        if account:
            conditions.append("subscription_account = ?")
            params.append(account)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
        sql = (
            f"SELECT * FROM handovers {where} "  # nosec B608
            "ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        cur = self.conn.execute(sql, params)
        return [_decode_row(row) for row in cur.fetchall()]

    def query_lessons(
        self,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查詢含 lessons_learned 的 handover 記錄。

        只回傳 lessons_learned 非空的記錄，欄位精簡為教訓相關欄位。
        """
        if limit <= 0:
            raise ValueError("limit 必須為正整數")
        if project:
            cur = self.conn.execute(
                "SELECT id, timestamp, topic, project, lessons_learned, attempted_approaches "
                "FROM handovers "
                "WHERE lessons_learned != '[]' AND project = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (project, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT id, timestamp, topic, project, lessons_learned, attempted_approaches "
                "FROM handovers "
                "WHERE lessons_learned != '[]' "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for col in ("lessons_learned", "attempted_approaches"):
                if col in d and isinstance(d[col], str):
                    try:
                        d[col] = json.loads(d[col])
                    except json.JSONDecodeError:
                        d[col] = []
            result.append(d)
        return result

    def count(self) -> int:
        """回傳總筆數（migrate 驗證用）。"""
        cur = self.conn.execute("SELECT COUNT(*) AS c FROM handovers")
        row = cur.fetchone()
        return int(row["c"]) if row else 0

    def insert_event(self, event: HandoverEvent) -> None:
        """寫入一筆 handover_event。"""
        self.conn.execute(
            """
            INSERT INTO handover_events (
              id, timestamp, session_id, event_type, source_layer,
              matcher, handover_id, project, device, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.timestamp,
                event.session_id,
                event.event_type.value,
                event.source_layer.value if event.source_layer else None,
                event.matcher,
                event.handover_id,
                event.project,
                event.device,
                json.dumps(event.extra, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def read_events(
        self,
        last: int = 50,
        session_id: str | None = None,
        event_type: EventType | None = None,
    ) -> list[dict[str, Any]]:
        """讀取最近 N 筆事件，可依 session_id / event_type 過濾。"""
        if last <= 0:
            raise ValueError("last 必須為正整數")

        conditions: list[str] = []
        params: list[object] = []
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type.value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""  # nosec B608
        sql = (
            f"SELECT * FROM handover_events {where} "  # nosec B608
            "ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(last)

        cur = self.conn.execute(sql, params)
        return [_decode_event_row(row) for row in cur.fetchall()]

    def aggregate_success_counts(
        self,
        since: str | None = None,
        project: str | None = None,
    ) -> dict[str, int]:
        """依 session_id 聚合成功/失敗旗標。

        定義：
        - `wrote_after_intercept`：同 session 有 intercept + handover_written
        - `silent_fail`：同 session 有 intercept + passthrough 但無 handover_written
        - `hard_fail`：同 session 有 layer3_session_start 但無 handover_written
        - `layer1_win`：同 session 有 handover_written 但無 layer2_intercept
        """
        conditions: list[str] = ["session_id IS NOT NULL"]
        params: list[object] = []
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if project:
            conditions.append("project = ?")
            params.append(project)

        where = f"WHERE {' AND '.join(conditions)}"  # nosec B608
        sql = f"""
            WITH flags AS (
              SELECT
                session_id,
                MAX(CASE WHEN event_type='layer2_intercept' THEN 1 ELSE 0 END) AS intercepted,
                MAX(CASE WHEN event_type='handover_written' THEN 1 ELSE 0 END) AS wrote,
                MAX(CASE WHEN event_type='layer2_passthrough' THEN 1 ELSE 0 END) AS passed,
                MAX(CASE WHEN event_type='layer3_session_start' THEN 1 ELSE 0 END) AS compacted,
                MAX(CASE WHEN event_type='layer2_stale_reset' THEN 1 ELSE 0 END) AS stale
              FROM handover_events
              {where}
              GROUP BY session_id
            )
            SELECT
              COUNT(*) AS sessions_observed,
              COALESCE(SUM(intercepted), 0) AS total_intercepts,
              COALESCE(SUM(intercepted*wrote), 0) AS wrote_after_intercept,
              COALESCE(SUM(intercepted*(1-wrote)*passed), 0) AS silent_fail,
              COALESCE(SUM(compacted*(1-wrote)), 0) AS hard_fail,
              COALESCE(SUM((1-intercepted)*wrote), 0) AS layer1_win,
              COALESCE(SUM(stale), 0) AS stale_reset
            FROM flags
        """  # nosec B608
        cur = self.conn.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return dict.fromkeys(
                (
                    "sessions_observed",
                    "total_intercepts",
                    "wrote_after_intercept",
                    "silent_fail",
                    "hard_fail",
                    "layer1_win",
                    "stale_reset",
                ),
                0,
            )
        return {k: int(row[k]) for k in row.keys()}  # noqa: SIM118  sqlite3.Row 非 dict


def _escape_like(value: str, escape_char: str = "\\") -> str:
    """逸出 SQLite LIKE 萬用字元（%、_）和 escape 字元本身。"""
    return (
        value.replace(escape_char, escape_char * 2)
        .replace("%", escape_char + "%")
        .replace("_", escape_char + "_")
    )


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    """把 sqlite3.Row 轉成 dict，並把 JSON array 欄位 decode 回 list。"""
    out = dict(row)
    for col in _JSON_ARRAY_COLS:
        if col in out and isinstance(out[col], str):
            try:
                out[col] = json.loads(out[col])
            except json.JSONDecodeError:
                out[col] = []
    return out


def _decode_event_row(row: sqlite3.Row) -> dict[str, Any]:
    """把 handover_events 的 sqlite3.Row 轉成 dict，extra_json decode 為 extra dict。"""
    out = dict(row)
    raw = out.pop("extra_json", "{}")
    if isinstance(raw, str):
        try:
            out["extra"] = json.loads(raw)
        except json.JSONDecodeError:
            out["extra"] = {}
    else:
        out["extra"] = {}
    return out
