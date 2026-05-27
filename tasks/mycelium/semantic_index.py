"""MemoryIndex：語意索引 interface 與 SqliteVecIndex 實作。

SqliteVecIndex：
  - 優先使用 sqlite-vec extension 做向量搜尋
  - sqlite-vec 不可用時 gracefully fallback 到 FTS5-only 模式（log WARNING）
  - 支援 mode="keyword"、"vector"、"hybrid" 三種搜尋模式
  - hybrid 用 RRF merging（k=60）合併 FTS5 + vector results
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RRF_K = 60


class MemoryIndex(ABC):
    """語意記憶索引抽象介面。"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """將文字轉換為稠密向量（embeddings）。"""

    @abstractmethod
    def upsert(self, lesson_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """以 lesson_id 索引一筆 lesson。"""

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[tuple[str, float]]:
        """搜尋並回傳 (lesson_id, score) pairs，依 score 降序。

        mode: "keyword" 只跑 FTS5；"vector" 只跑 sqlite-vec；"hybrid" 合併。
        """

    @abstractmethod
    def delete(self, lesson_id: str) -> None:
        """從索引移除一筆 lesson。"""


class SqliteVecIndex(MemoryIndex):
    """SQLite FTS5 + sqlite-vec 混合索引。

    sqlite-vec 不可用時 gracefully fallback 到 FTS5-only 模式。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        db_str = str(db_path) if db_path else ":memory:"
        self._conn = sqlite3.connect(db_str)
        self._conn.row_factory = sqlite3.Row
        self._vec_available = self._try_load_sqlite_vec()
        self._init_tables()

    def _try_load_sqlite_vec(self) -> bool:
        """嘗試載入 sqlite-vec extension；不可用時 log WARNING 並回傳 False。"""
        try:
            self._conn.enable_load_extension(True)
            self._conn.load_extension("sqlite_vec")
            self._conn.enable_load_extension(False)
            return True
        except Exception:
            logger.warning(
                "[mycelium-semantic] sqlite-vec extension 不可用，使用 FTS5-only 模式。"
                " 安裝：pip install sqlite-vec"
            )
            return False

    def _init_tables(self) -> None:
        """建立 FTS5 全文索引表和（若可用）vector 表。"""
        self._conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS lesson_fts USING fts5(
                lesson_id UNINDEXED,
                content
            );
            CREATE TABLE IF NOT EXISTS lesson_metadata (
                lesson_id TEXT PRIMARY KEY,
                content TEXT NOT NULL
            );
            """
        )
        if self._vec_available:
            try:
                self._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS lesson_embeddings (
                        lesson_id TEXT PRIMARY KEY,
                        embedding BLOB
                    );
                    """
                )
            except Exception:
                self._vec_available = False
        self._conn.commit()

    def embed(self, text: str) -> list[float]:
        """Phase 4 placeholder — 永遠回傳空 list。

        實際 sqlite-vec 向量搜尋需要外部 embedding model（如 sentence-transformers）。
        此方法在 Phase 4 embedding pipeline 落地前均回傳 []；
        呼叫者不應依賴回傳值非空。
        """
        return []

    def upsert(self, lesson_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """索引一筆 lesson（FTS5 + 若可用則 vector）。"""
        # FTS5: delete + insert（upsert 模式）
        self._conn.execute("DELETE FROM lesson_fts WHERE lesson_id = ?", (lesson_id,))
        self._conn.execute(
            "INSERT INTO lesson_fts (lesson_id, content) VALUES (?, ?)",
            (lesson_id, text),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO lesson_metadata (lesson_id, content) VALUES (?, ?)",
            (lesson_id, text),
        )
        self._conn.commit()

    def search(
        self,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[tuple[str, float]]:
        """搜尋 lessons。mode: keyword / vector / hybrid。"""
        if mode == "keyword":
            return self._fts5_search(query, limit)
        if mode == "vector":
            return self._vector_search(query, limit)
        # hybrid: RRF merge
        return self._hybrid_search(query, limit)

    def delete(self, lesson_id: str) -> None:
        """從 FTS5 和 metadata 移除 lesson。"""
        self._conn.execute("DELETE FROM lesson_fts WHERE lesson_id = ?", (lesson_id,))
        self._conn.execute("DELETE FROM lesson_metadata WHERE lesson_id = ?", (lesson_id,))
        self._conn.commit()

    def _fts5_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """FTS5 全文搜尋；回傳 (lesson_id, score)。"""
        try:
            cur = self._conn.execute(
                "SELECT lesson_id, rank FROM lesson_fts WHERE lesson_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (self._fts5_query(query), limit),
            )
            rows = cur.fetchall()
            return [(row["lesson_id"], -float(row["rank"])) for row in rows]
        except sqlite3.OperationalError:
            # FTS5 MATCH 格式錯誤（特殊字元）：fallback to LIKE
            return self._fts5_like_fallback(query, limit)

    def _fts5_like_fallback(self, query: str, limit: int) -> list[tuple[str, float]]:
        """FTS5 MATCH 失敗時的 LIKE fallback。"""
        like = f"%{query.lower()}%"
        cur = self._conn.execute(
            "SELECT lesson_id FROM lesson_metadata WHERE LOWER(content) LIKE ? LIMIT ?",
            (like, limit),
        )
        rows = cur.fetchall()
        return [(row["lesson_id"], 1.0) for row in rows]

    def _vector_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Phase 4 placeholder — 永遠 fallback 到 FTS5。

        sqlite-vec 的向量搜尋需要 embed() 生成真實 embedding 向量，
        目前 embed() 回傳 []，故向量搜尋尚未實作。
        mode="vector" 與 mode="keyword" 在此版本行為相同。
        """
        return self._fts5_search(query, limit)

    def _hybrid_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """RRF（k=60）合併 FTS5 + vector results。"""
        fts_results = self._fts5_search(query, limit * 2)
        vec_results = self._vector_search(query, limit * 2)

        return _rrf_merge(fts_results, vec_results, k=_RRF_K, limit=limit)

    @staticmethod
    def _fts5_query(text: str) -> str:
        """將查詢文字轉為 FTS5 query（每個 token 以引號包裝做 phrase 匹配）。"""
        tokens = [t for t in text.split() if t]
        if not tokens:
            return '""'
        return " OR ".join(f'"{t}"' for t in tokens)

    def close(self) -> None:
        """關閉 SQLite 連線。"""
        if self._conn:
            self._conn.close()


def _rrf_merge(
    list_a: list[tuple[str, float]],
    list_b: list[tuple[str, float]],
    k: int = 60,
    limit: int = 10,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion（RRF）合併兩個 ranked list。

    score(d) = sum(1 / (k + rank_i(d))) for each list i that contains d
    """
    scores: dict[str, float] = {}

    for rank, (lesson_id, _) in enumerate(list_a, start=1):
        scores[lesson_id] = scores.get(lesson_id, 0.0) + 1.0 / (k + rank)

    for rank, (lesson_id, _) in enumerate(list_b, start=1):
        scores[lesson_id] = scores.get(lesson_id, 0.0) + 1.0 / (k + rank)

    sorted_pairs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_pairs[:limit]
