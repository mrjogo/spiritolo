import json
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
    disabled_reason TEXT,
    validated_at TEXT
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


# Pipeline runs + per-stage eval tables.
#
# Each evaluator owns a `*_runs` table keyed by page_id PK (latest-only: a re-run
# UPSERTs and overwrites). Every eval row carries a `run_id` FK to pipeline_runs,
# its evaluator version, and — for stages that mutate a `pages` field — a
# snapshot of that field's value right before this evaluation ran. That snapshot
# is how we answer "what flipped on the last run" without keeping history.
#
# These tables are intentionally prunable. Dropping them (or deleting rows) does
# not break `pages`; it just means the affected stage will re-evaluate next run.

CREATE_PIPELINE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stage       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    site        TEXT,
    args        TEXT,
    summary     TEXT
);
"""

CREATE_CLASSIFY_URL_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS classify_url_runs (
    page_id                    INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    run_id                     INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    label                      TEXT NOT NULL,
    model                      TEXT NOT NULL,
    prompt_version             TEXT NOT NULL,
    raw_response               TEXT,
    latency_ms                 INTEGER,
    evaluated_at               TEXT NOT NULL,
    pages_content_type_before  TEXT
);
"""

CREATE_VALIDATE_HTML_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS validate_html_runs (
    page_id              INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    run_id               INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    status               TEXT NOT NULL,
    reason               TEXT,
    validator_version    TEXT NOT NULL,
    evaluated_at         TEXT NOT NULL,
    pages_status_before  TEXT
);
"""

CREATE_CLASSIFY_DRINK_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS classify_drink_runs (
    page_id                    INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    run_id                     INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    label                      TEXT,
    score                      REAL,
    score_detail               TEXT,
    scorer_version             TEXT NOT NULL,
    evaluated_at               TEXT NOT NULL,
    pages_content_type_before  TEXT
);
"""

CREATE_EXTRACT_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS extract_runs (
    page_id            INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    run_id             INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    outcome            TEXT NOT NULL,
    error              TEXT,
    extractor_version  TEXT NOT NULL,
    evaluated_at       TEXT NOT NULL
);
"""

CREATE_EVAL_RUN_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_classify_url_runs_run_id ON classify_url_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_validate_html_runs_run_id ON validate_html_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_classify_drink_runs_run_id ON classify_drink_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_extract_runs_run_id ON extract_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage ON pipeline_runs(stage);",
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
            self.conn.execute(CREATE_PIPELINE_RUNS_TABLE)
            self.conn.execute(CREATE_CLASSIFY_URL_RUNS_TABLE)
            self.conn.execute(CREATE_VALIDATE_HTML_RUNS_TABLE)
            self.conn.execute(CREATE_CLASSIFY_DRINK_RUNS_TABLE)
            self.conn.execute(CREATE_EXTRACT_RUNS_TABLE)
            for idx in CREATE_EVAL_RUN_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()
            self._migrate()

    def _migrate(self):
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(pages)")}
        if "disabled_reason" not in cols:
            self.conn.execute("ALTER TABLE pages ADD COLUMN disabled_reason TEXT")
            self.conn.commit()
        if "validated_at" not in cols:
            self.conn.execute("ALTER TABLE pages ADD COLUMN validated_at TEXT")
            self.conn.commit()
        self._backfill_classify_url_runs()

    def _backfill_classify_url_runs(self):
        """One-shot copy of the most-recent classification per page into
        `classify_url_runs`, to land latest-only semantics on existing DBs
        without discarding prior LLM classifications. Skipped if the runs
        table is already populated — we don't want to resurrect rows the user
        may have intentionally pruned."""
        existing = self.conn.execute("SELECT 1 FROM classify_url_runs LIMIT 1").fetchone()
        if existing is not None:
            return
        has_legacy = self.conn.execute("SELECT 1 FROM classifications LIMIT 1").fetchone()
        if has_legacy is None:
            return
        self.conn.execute(
            """
            INSERT INTO classify_url_runs
                (page_id, run_id, label, model, prompt_version,
                 raw_response, latency_ms, evaluated_at, pages_content_type_before)
            SELECT page_id, NULL, label, model, prompt_version,
                   raw_response, latency_ms, created_at, NULL
            FROM classifications c
            WHERE c.id = (SELECT MAX(id) FROM classifications WHERE page_id = c.page_id)
            """
        )
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

    EXTRACT_CONTENT_TYPES = ("likely_drink_recipe", "confirmed_drink")

    def get_unextracted(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        """Work queue for the extractor: drink-recipe pages that have fetched HTML but haven't been extracted or errored.

        Covers both `likely_drink_recipe` (LLM-classified from URL, JSON-LD not
        yet verified) and `confirmed_drink` (validate.py confirmed Schema.org
        Recipe + drink terms at fetch time). Ordered by id so iteration is
        deterministic and resumable across runs.
        """
        placeholders = ",".join("?" for _ in self.EXTRACT_CONTENT_TYPES)
        query = (
            "SELECT id, site, url, html_path, fetched_at FROM pages "
            f"WHERE content_type IN ({placeholders}) "
            "AND html_path IS NOT NULL "
            "AND extracted_at IS NULL "
            "AND extract_error IS NULL"
        )
        params: list = list(self.EXTRACT_CONTENT_TYPES)
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

    def reset_extract_state(self, site: str | None = None) -> int:
        """Clear extracted_at and extract_error on all drink-recipe rows,
        optionally scoped to a site. Covers the same content_type set as
        get_unextracted. Returns row count."""
        placeholders = ",".join("?" for _ in self.EXTRACT_CONTENT_TYPES)
        query = (
            "UPDATE pages SET extracted_at = NULL, extract_error = NULL "
            f"WHERE content_type IN ({placeholders})"
        )
        params: list = list(self.EXTRACT_CONTENT_TYPES)
        if site:
            query += " AND site = ?"
            params.append(site)
        with self._lock:
            cursor = self.conn.execute(query, params)
            self.conn.commit()
            return cursor.rowcount

    def mark_validated(self, url: str):
        """Stamp validated_at = now() so the validate CLI's work queue
        (`validated_at IS NULL`) skips this row on future runs."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET validated_at = ? WHERE url = ?",
                (now, url),
            )
            self.conn.commit()

    def clear_validated_at(self, site: str | None = None) -> int:
        """Clear validated_at for html-cached rows so the validate CLI
        re-processes them. Optionally scoped to a site. Returns row count."""
        query = "UPDATE pages SET validated_at = NULL WHERE html_path IS NOT NULL"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        with self._lock:
            cursor = self.conn.execute(query, params)
            self.conn.commit()
            return cursor.rowcount

    def count_pending_validation(self, site: str | None = None) -> int:
        """Rows with cached HTML that haven't been validated yet."""
        query = (
            "SELECT COUNT(*) FROM pages "
            "WHERE html_path IS NOT NULL AND validated_at IS NULL"
        )
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        with self._lock:
            return self.conn.execute(query, params).fetchone()[0]

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

    # ------------------------------------------------------------------
    # Pipeline runs + per-stage eval writes
    # ------------------------------------------------------------------

    def start_run(
        self,
        *,
        stage: str,
        site: str | None = None,
        args: dict | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self.conn.execute(
                "INSERT INTO pipeline_runs (stage, started_at, site, args) VALUES (?, ?, ?, ?)",
                (stage, now, site, json.dumps(args) if args is not None else None),
            )
            self.conn.commit()
            return cursor.lastrowid

    def finish_run(self, run_id: int, summary: dict | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pipeline_runs SET finished_at = ?, summary = ? WHERE id = ?",
                (now, json.dumps(summary) if summary is not None else None, run_id),
            )
            self.conn.commit()

    def record_validate_html(
        self,
        *,
        page_id: int,
        run_id: int,
        status: str,
        reason: str | None,
        validator_version: str,
        pages_status_before: str | None,
    ) -> None:
        """UPSERT one row per page. Latest-only; re-runs overwrite."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO validate_html_runs
                    (page_id, run_id, status, reason, validator_version,
                     evaluated_at, pages_status_before)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    status = excluded.status,
                    reason = excluded.reason,
                    validator_version = excluded.validator_version,
                    evaluated_at = excluded.evaluated_at,
                    pages_status_before = excluded.pages_status_before
                """,
                (page_id, run_id, status, reason, validator_version, now, pages_status_before),
            )
            self.conn.commit()

    def record_classify_drink(
        self,
        *,
        page_id: int,
        run_id: int,
        label: str | None,
        score: float | int,
        score_detail: dict,
        scorer_version: str,
        pages_content_type_before: str | None,
    ) -> None:
        """UPSERT one row per page. `label` may be NULL for abstain."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO classify_drink_runs
                    (page_id, run_id, label, score, score_detail, scorer_version,
                     evaluated_at, pages_content_type_before)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    label = excluded.label,
                    score = excluded.score,
                    score_detail = excluded.score_detail,
                    scorer_version = excluded.scorer_version,
                    evaluated_at = excluded.evaluated_at,
                    pages_content_type_before = excluded.pages_content_type_before
                """,
                (
                    page_id, run_id, label, score, json.dumps(score_detail),
                    scorer_version, now, pages_content_type_before,
                ),
            )
            self.conn.commit()

    def get_pending_validate_html(
        self, site: str | None = None, limit: int | None = None,
    ) -> list[dict]:
        """Work queue: pages with cached HTML that have no validate_html_runs
        row. Replaces the old `validated_at IS NULL` query — a missing eval
        row is the signal to re-run, and nothing else."""
        query = [
            "SELECT p.id, p.site, p.url, p.status, p.content_type, p.html_path",
            "FROM pages p",
            "LEFT JOIN validate_html_runs v ON v.page_id = p.id",
            "WHERE p.html_path IS NOT NULL AND v.page_id IS NULL",
        ]
        params: list = []
        if site:
            query.append("AND p.site = ?")
            params.append(site)
        query.append("ORDER BY p.site, p.id")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(" ".join(query), params).fetchall()
        return [dict(r) for r in rows]

    def count_pending_validate_html(self, site: str | None = None) -> int:
        query = [
            "SELECT COUNT(*) c FROM pages p",
            "LEFT JOIN validate_html_runs v ON v.page_id = p.id",
            "WHERE p.html_path IS NOT NULL AND v.page_id IS NULL",
        ]
        params: list = []
        if site:
            query.append("AND p.site = ?")
            params.append(site)
        with self._lock:
            return self.conn.execute(" ".join(query), params).fetchone()["c"]

    def clear_validate_html_runs(self, site: str | None = None) -> int:
        """Delete rows from validate_html_runs, optionally scoped to a site
        (joined via pages). Returns deleted row count."""
        return self._clear_eval_table("validate_html_runs", site)

    def clear_classify_drink_runs(self, site: str | None = None) -> int:
        return self._clear_eval_table("classify_drink_runs", site)

    def _clear_eval_table(self, table: str, site: str | None) -> int:
        with self._lock:
            if site is None:
                cursor = self.conn.execute(f"DELETE FROM {table}")
            else:
                cursor = self.conn.execute(
                    f"DELETE FROM {table} WHERE page_id IN "
                    "(SELECT id FROM pages WHERE site = ?)",
                    (site,),
                )
            self.conn.commit()
            return cursor.rowcount
