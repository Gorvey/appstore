from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS crawls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id TEXT NOT NULL UNIQUE,
    collection TEXT NOT NULL,
    created_at TEXT NOT NULL,
    wacz_path TEXT NOT NULL,
    wacz_size INTEGER NOT NULL,
    wacz_mtime_ns INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('indexing', 'ready', 'failed')),
    baseline INTEGER NOT NULL DEFAULT 0,
    archive_available INTEGER NOT NULL DEFAULT 1,
    relation_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS contents (
    digest TEXT PRIMARY KEY,
    size INTEGER,
    mime TEXT,
    encoding TEXT,
    stored INTEGER NOT NULL DEFAULT 0,
    content_path TEXT,
    unsupported_reason TEXT,
    decoded_sha256 TEXT,
    first_crawl_id TEXT NOT NULL REFERENCES crawls(crawl_id),
    first_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id TEXT NOT NULL REFERENCES crawls(crawl_id) ON DELETE CASCADE,
    digest TEXT NOT NULL REFERENCES contents(digest),
    url TEXT NOT NULL,
    hostname TEXT NOT NULL DEFAULT '',
    captured_at TEXT,
    http_status INTEGER,
    mime TEXT,
    warc_type TEXT NOT NULL,
    warc_filename TEXT,
    record_id TEXT,
    UNIQUE(crawl_id, digest, url, captured_at, warc_type)
);

CREATE TABLE IF NOT EXISTS crawl_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id TEXT NOT NULL REFERENCES crawls(crawl_id) ON DELETE CASCADE,
    digest TEXT NOT NULL REFERENCES contents(digest),
    UNIQUE(crawl_id, digest)
);

CREATE INDEX IF NOT EXISTS idx_crawls_created ON crawls(created_at, id);
CREATE INDEX IF NOT EXISTS idx_changes_crawl ON crawl_changes(crawl_id, id);
CREATE INDEX IF NOT EXISTS idx_occurrences_crawl_digest ON occurrences(crawl_id, digest);
CREATE INDEX IF NOT EXISTS idx_occurrences_url ON occurrences(url, id);
CREATE INDEX IF NOT EXISTS idx_occurrences_hostname ON occurrences(hostname);
"""


class Repository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ready_count(self, connection: sqlite3.Connection | None = None) -> int:
        if connection is not None:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM crawls WHERE status = 'ready'"
                ).fetchone()[0]
            )
        with self.connect() as current:
            return self.ready_count(current)

    def health(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT
                    SUM(status = 'ready') AS ready,
                    SUM(status = 'failed') AS failed,
                    SUM(status = 'indexing') AS indexing
                   FROM crawls"""
            ).fetchone()
        return {
            "status": "ok",
            "crawls": {
                "ready": int(row["ready"] or 0),
                "failed": int(row["failed"] or 0),
                "indexing": int(row["indexing"] or 0),
            },
        }

    def list_crawls(self, after: int, limit: int) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM crawl_changes cc
                           WHERE cc.crawl_id = c.crawl_id) AS change_count,
                          (SELECT COUNT(*) FROM occurrences o
                           WHERE o.crawl_id = c.crawl_id) AS occurrence_count
                   FROM crawls c
                   WHERE c.status = 'ready' AND c.id > ?
                   ORDER BY c.id LIMIT ?""",
                (after, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "items": [self._crawl(row) for row in page],
            "nextCursor": encode_cursor(page[-1]["id"]) if has_more and page else None,
        }

    def get_crawl(self, crawl_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM crawl_changes cc
                           WHERE cc.crawl_id = c.crawl_id) AS change_count,
                          (SELECT COUNT(*) FROM occurrences o
                           WHERE o.crawl_id = c.crawl_id) AS occurrence_count
                   FROM crawls c WHERE c.crawl_id = ?""",
                (crawl_id,),
            ).fetchone()
        return self._crawl(row) if row else None

    def list_changes(
        self,
        crawl_id: str,
        after: int,
        limit: int,
        hostname: str | None = None,
        mime: str | None = None,
        status: int | None = None,
        url_prefix: str | None = None,
    ) -> dict[str, Any]:
        clauses = ["cc.crawl_id = ?", "cc.id > ?"]
        params: list[Any] = [crawl_id, after]
        filters: list[str] = ["o.crawl_id = cc.crawl_id", "o.digest = cc.digest"]
        if hostname:
            filters.append("o.hostname = ?")
            params.append(hostname.lower())
        if mime:
            filters.append("o.mime = ?")
            params.append(mime.lower())
        if status is not None:
            filters.append("o.http_status = ?")
            params.append(status)
        if url_prefix:
            filters.append("o.url LIKE ? ESCAPE '\\'")
            escaped = url_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"{escaped}%")
        clauses.append(f"EXISTS (SELECT 1 FROM occurrences o WHERE {' AND '.join(filters)})")
        params.append(limit + 1)
        sql = f"""SELECT cc.id AS change_id, c.*
                  FROM crawl_changes cc
                  JOIN contents c ON c.digest = cc.digest
                  WHERE {' AND '.join(clauses)}
                  ORDER BY cc.id LIMIT ?"""
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            has_more = len(rows) > limit
            page = rows[:limit]
            items = [
                self._content(
                    row,
                    self._occurrences(connection, crawl_id, row["digest"]),
                )
                for row in page
            ]
        return {
            "items": items,
            "nextCursor": encode_cursor(page[-1]["change_id"])
            if has_more and page
            else None,
        }

    def get_content(self, digest: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM contents WHERE digest = ?", (digest,)
            ).fetchone()
            if not row:
                return None
            occurrences = connection.execute(
                "SELECT * FROM occurrences WHERE digest = ? ORDER BY id", (digest,)
            ).fetchall()
        return self._content(row, occurrences)

    def url_history(self, url: str, after: int, limit: int) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT o.*, c.created_at AS crawl_created_at,
                          ct.stored, ct.size, ct.unsupported_reason
                   FROM occurrences o
                   JOIN crawls c ON c.crawl_id = o.crawl_id
                   JOIN contents ct ON ct.digest = o.digest
                   WHERE o.url = ? AND o.id > ? AND c.status = 'ready'
                   ORDER BY o.id LIMIT ?""",
                (url, after, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "items": [dict(row) for row in page],
            "nextCursor": encode_cursor(page[-1]["id"]) if has_more and page else None,
        }

    @staticmethod
    def _crawl(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "crawlId": row["crawl_id"],
            "collection": row["collection"],
            "createdAt": row["created_at"],
            "status": row["status"],
            "baseline": bool(row["baseline"]),
            "archiveAvailable": bool(row["archive_available"]),
            "changeCount": int(row["change_count"] or 0),
            "occurrenceCount": int(row["occurrence_count"] or 0),
            "relation": json.loads(row["relation_json"] or "{}"),
            "indexedAt": row["indexed_at"],
            "error": row["error"],
        }

    @staticmethod
    def _occurrences(
        connection: sqlite3.Connection, crawl_id: str, digest: str
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT url, hostname, captured_at, http_status, mime, warc_type,
                      warc_filename, record_id
               FROM occurrences WHERE crawl_id = ? AND digest = ? ORDER BY id""",
            (crawl_id, digest),
        ).fetchall()

    @staticmethod
    def _content(row: sqlite3.Row, occurrences: list[sqlite3.Row]) -> dict[str, Any]:
        return {
            "digest": row["digest"],
            "size": row["size"],
            "mime": row["mime"],
            "encoding": row["encoding"],
            "stored": bool(row["stored"]),
            "contentUnsupported": bool(row["unsupported_reason"]),
            "unsupportedReason": row["unsupported_reason"],
            "decodedSha256": row["decoded_sha256"],
            "firstCrawlId": row["first_crawl_id"],
            "firstUrl": row["first_url"],
            "contentUrl": f"/api/v1/contents/{row['digest']}"
            if row["stored"]
            else None,
            "occurrences": [dict(item) for item in occurrences],
        }


def encode_cursor(value: int) -> str:
    raw = f"v1:{value}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> int:
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded).decode("ascii")
        version, number = raw.split(":", 1)
        if version != "v1":
            raise ValueError
        result = int(number)
        if result < 0:
            raise ValueError
        return result
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc
