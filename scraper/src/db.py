import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 3

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    content_type TEXT,
    sitemap_source TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    error TEXT,
    html_path TEXT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);",
    "CREATE INDEX IF NOT EXISTS idx_pages_site ON pages(site);",
    "CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);",
    "CREATE INDEX IF NOT EXISTS idx_pages_status_content_type ON pages(status, content_type);",
]

CREATE_CLASSIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    label TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    raw_response TEXT,
    latency_ms INTEGER,
    created_at TEXT NOT NULL
);
"""

CREATE_CLASSIFICATIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_classifications_page_id ON classifications(page_id);",
    "CREATE INDEX IF NOT EXISTS idx_classifications_label ON classifications(label);",
]


class Database:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute(CREATE_TABLE)
            for idx in CREATE_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()
            self.conn.execute(CREATE_CLASSIFICATIONS_TABLE)
            for idx in CREATE_CLASSIFICATIONS_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def add_url(self, site: str, url: str) -> bool:
        """Insert a URL if it doesn't exist. Returns True if inserted, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO pages (site, url, discovered_at) VALUES (?, ?, ?)",
                (site, url, now),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def add_urls_batch(self, site: str, urls: list[str], sitemap_source: str | None = None) -> int:
        """Insert multiple URLs in a single transaction. Returns count of new rows inserted."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [(site, url, sitemap_source, now) for url in urls]
        with self._lock:
            cursor = self.conn.executemany(
                "INSERT OR IGNORE INTO pages (site, url, sitemap_source, discovered_at) VALUES (?, ?, ?, ?)",
                rows,
            )
            self.conn.commit()
            return cursor.rowcount

    def get_pending(self, site: str | None = None, limit: int | None = None, content_type: str | None = None) -> list[dict]:
        query = "SELECT * FROM pages WHERE status = 'pending'"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        if content_type:
            query += " AND content_type = ?"
            params.append(content_type)
        query += " ORDER BY site, discovered_at"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def mark_blocked(self, url: str, reason: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = 'blocked', error = ? WHERE url = ?",
                (reason, url),
            )
            self.conn.commit()

    def mark_content(self, url: str, status: str, reason: str, html_path: str | None = None):
        """Mark a page with an arbitrary content status (JSON-LD @type, 'unverified', etc.)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = ?, error = ?, html_path = ?, fetched_at = ? WHERE url = ?",
                (status, reason, html_path, now, url),
            )
            self.conn.commit()

    def mark_failed(self, url: str, error: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET attempts = attempts + 1, error = ? WHERE url = ?",
                (error, url),
            )
            self.conn.execute(
                "UPDATE pages SET status = 'failed' WHERE url = ? AND attempts >= ?",
                (url, MAX_ATTEMPTS),
            )
            self.conn.commit()

    def get_recent_statuses(self, site: str, count: int = 20) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT status FROM pages WHERE site = ? AND status != 'pending' ORDER BY id DESC LIMIT ?",
                (site, count),
            ).fetchall()
        return [row["status"] for row in rows]

    def get_stats(self) -> dict:
        with self._lock:
            rows = self.conn.execute(
                "SELECT site, status, COUNT(*) as cnt FROM pages GROUP BY site, status"
            ).fetchall()
        stats: dict = {}
        for row in rows:
            site = row["site"]
            if site not in stats:
                stats[site] = {}
            stats[site][row["status"]] = row["cnt"]
        return stats

    def set_content_type(self, url: str, content_type: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET content_type = ? WHERE url = ?",
                (content_type, url),
            )
            self.conn.commit()

    def set_content_type_batch(self, ids: list[int], content_type: str):
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            self.conn.execute(
                f"UPDATE pages SET content_type = ? WHERE id IN ({placeholders})",
                [content_type] + ids,
            )
            self.conn.commit()

    def record_classification(
        self,
        page_id: int,
        label: str,
        model: str,
        prompt_version: str,
        raw_response: str | None,
        latency_ms: int | None,
    ):
        """Insert an audit record and update pages.content_type atomically."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "INSERT INTO classifications (page_id, label, model, prompt_version, raw_response, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (page_id, label, model, prompt_version, raw_response, latency_ms, now),
            )
            self.conn.execute(
                "UPDATE pages SET content_type = ? WHERE id = ?",
                (label, page_id),
            )
            self.conn.commit()

    def get_unclassified(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        query = "SELECT id, site, url, sitemap_source FROM pages WHERE content_type IS NULL"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        query += " ORDER BY id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def sample_classifications(self, site: str, label: str, n: int = 10) -> list[dict]:
        """Return n random (url, label, raw_response) rows for a (site, label) pair.

        Returns the MOST RECENT classification per page, so re-classifications don't
        produce duplicates in the sample.
        """
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT p.url, c.label, c.raw_response, c.created_at
                FROM classifications c
                JOIN pages p ON p.id = c.page_id
                WHERE p.site = ? AND c.label = ?
                  AND c.id = (
                      SELECT MAX(id) FROM classifications WHERE page_id = c.page_id
                  )
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (site, label, n),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_content_type(self, content_type: str, site: str | None = None, limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM pages WHERE content_type = ?"
        params: list = [content_type]
        if site:
            query += " AND site = ?"
            params.append(site)
        query += " ORDER BY site, discovered_at"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
