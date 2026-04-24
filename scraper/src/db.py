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
    html_path TEXT,
    extracted_at TEXT,
    extract_error TEXT,
    disabled_reason TEXT
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
            # Idempotent column adds for existing DBs (SQLite has no ADD COLUMN IF NOT EXISTS).
            existing_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(pages)").fetchall()}
            if "extracted_at" not in existing_cols:
                self.conn.execute("ALTER TABLE pages ADD COLUMN extracted_at TEXT")
            if "extract_error" not in existing_cols:
                self.conn.execute("ALTER TABLE pages ADD COLUMN extract_error TEXT")
            self.conn.commit()
            self.conn.execute(CREATE_CLASSIFICATIONS_TABLE)
            for idx in CREATE_CLASSIFICATIONS_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()
            self._migrate()

    def _migrate(self):
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(pages)")}
        if "disabled_reason" not in cols:
            self.conn.execute("ALTER TABLE pages ADD COLUMN disabled_reason TEXT")
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
        query = "SELECT * FROM pages WHERE status = 'pending' AND disabled_reason IS NULL"
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

    def mark_blocked(self, url: str, reason: str, html_path: str | None = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = 'blocked', error = ?, html_path = ?, fetched_at = ? WHERE url = ?",
                (reason, html_path, now, url),
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
        """Work queue for the classifier. Returns rows with `content_type IS NULL`.

        Deliberately ignores `status` — the classifier reads the URL string, not
        the page body, so blocked/failed pages are still classifiable. Orders by
        `id` so iteration is deterministic and resumable across runs.
        """
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

    def get_unextracted(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        """Work queue for the extractor: drink-recipe pages that have fetched HTML but haven't been extracted or errored.

        Ordered by id so iteration is deterministic and resumable across runs.
        """
        query = (
            "SELECT id, site, url, html_path, fetched_at FROM pages "
            "WHERE content_type = 'likely_drink_recipe' "
            "AND html_path IS NOT NULL "
            "AND extracted_at IS NULL "
            "AND extract_error IS NULL"
        )
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
        return [dict(r) for r in rows]

    def mark_extracted(self, url: str):
        """Mark a page as successfully extracted. Clears any prior extract_error."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET extracted_at = ?, extract_error = NULL WHERE url = ?",
                (now, url),
            )
            self.conn.commit()

    def mark_extract_error(self, url: str, reason: str):
        """Mark a page as failed to extract. Leaves extracted_at NULL."""
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET extract_error = ? WHERE url = ?",
                (reason, url),
            )
            self.conn.commit()

    def count_unclassified(self, site: str | None = None) -> int:
        """Count of rows with `content_type IS NULL`, optionally scoped to a site."""
        query = "SELECT COUNT(*) FROM pages WHERE content_type IS NULL"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        with self._lock:
            row = self.conn.execute(query, params).fetchone()
        return row[0]

    def sample_classifications(
        self, site: str | None = None, label: str | None = None, n: int = 10
    ) -> list[dict]:
        """Return n random (site, url, label, raw_response) rows, optionally filtered
        by site and/or label.

        Returns the MOST RECENT classification per page, so re-classifications don't
        produce duplicates in the sample.
        """
        query = [
            "SELECT p.site, p.url, c.label, c.raw_response, c.created_at",
            "FROM classifications c JOIN pages p ON p.id = c.page_id",
            "WHERE c.id = (SELECT MAX(id) FROM classifications WHERE page_id = c.page_id)",
        ]
        params: list = []
        if site:
            query.append("AND p.site = ?")
            params.append(site)
        if label:
            query.append("AND c.label = ?")
            params.append(label)
        query.append("ORDER BY RANDOM() LIMIT ?")
        params.append(n)
        with self._lock:
            rows = self.conn.execute(" ".join(query), params).fetchall()
        return [dict(r) for r in rows]

    def get_classifications_for_urls(self, urls: list[str]) -> list[dict]:
        """Look up the most-recent classification for each URL. URLs not present
        in the DB (or present but never classified) are returned with label=None
        so callers can report 'not found' distinctly from 'has a label'."""
        if not urls:
            return []
        placeholders = ",".join("?" for _ in urls)
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT p.site, p.url, c.label, c.raw_response, c.created_at
                FROM pages p
                LEFT JOIN classifications c
                  ON c.page_id = p.id
                 AND c.id = (SELECT MAX(id) FROM classifications WHERE page_id = p.id)
                WHERE p.url IN ({placeholders})
                """,
                urls,
            ).fetchall()
        found = {r["url"]: dict(r) for r in rows}
        # Preserve input order; synthesize rows for URLs not in DB at all.
        return [
            found.get(u, {"site": None, "url": u, "label": None, "raw_response": None, "created_at": None})
            for u in urls
        ]

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
