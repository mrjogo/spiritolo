import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 3

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
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
]


class Database:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(CREATE_TABLE)
        for idx in CREATE_INDEXES:
            self.conn.execute(idx)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def add_url(self, site: str, url: str) -> bool:
        """Insert a URL if it doesn't exist. Returns True if inserted, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO pages (site, url, discovered_at) VALUES (?, ?, ?)",
            (site, url, now),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_pending(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM pages WHERE status = 'pending'"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        query += " ORDER BY site, discovered_at"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def mark_blocked(self, url: str, reason: str):
        self.conn.execute(
            "UPDATE pages SET status = 'blocked', error = ? WHERE url = ?",
            (reason, url),
        )
        self.conn.commit()

    def mark_content(self, url: str, status: str, reason: str, html_path: str | None = None):
        """Mark a page with an arbitrary content status (JSON-LD @type, 'unverified', etc.)."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE pages SET status = ?, error = ?, html_path = ?, fetched_at = ? WHERE url = ?",
            (status, reason, html_path, now, url),
        )
        self.conn.commit()

    def mark_failed(self, url: str, error: str):
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
        rows = self.conn.execute(
            "SELECT status FROM pages WHERE site = ? AND status != 'pending' ORDER BY id DESC LIMIT ?",
            (site, count),
        ).fetchall()
        return [row["status"] for row in rows]

    def get_stats(self) -> dict:
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
