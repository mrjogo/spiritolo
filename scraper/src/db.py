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
    fetch_error TEXT,
    html_path TEXT,
    disabled_reason TEXT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);",
    "CREATE INDEX IF NOT EXISTS idx_pages_site ON pages(site);",
    "CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);",
    "CREATE INDEX IF NOT EXISTS idx_pages_status_content_type ON pages(status, content_type);",
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
        # Legacy schema cleanup — idempotent. Each of these ALTERs is a
        # one-shot for older DBs; new DBs already ship with the target shape.
        if "error" in cols and "fetch_error" not in cols:
            # Narrow the column to its current meaning: "last fetch exception".
            # Validate reasons (which historically shared this column) moved
            # to validate_html_runs.reason, so clear them on non-failed rows.
            # Re-running validate re-populates those reasons in the eval table.
            self.conn.execute("ALTER TABLE pages RENAME COLUMN error TO fetch_error")
            self.conn.execute("UPDATE pages SET fetch_error = NULL WHERE status != 'failed'")
            self.conn.commit()
        if "validated_at" in cols:
            # Replaced by validate_html_runs — work queue now joins against
            # the presence of an eval row, not this timestamp.
            self.conn.execute("ALTER TABLE pages DROP COLUMN validated_at")
            self.conn.commit()
        # Legacy `classifications` table was superseded by `classify_url_runs`.
        self.conn.execute("DROP TABLE IF EXISTS classifications")
        self.conn.commit()
        self._migrate_extract_columns(cols)

    def _migrate_extract_columns(self, cols: set[str]) -> None:
        """One-shot: backfill extract_runs from pages.extracted_at /
        extract_error, then drop those columns. Preserves "we already
        extracted this" signal so re-running extract after migration
        doesn't redo every Supabase UPSERT."""
        if "extracted_at" not in cols and "extract_error" not in cols:
            return
        # Successful extractions.
        if "extracted_at" in cols:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO extract_runs
                    (page_id, run_id, outcome, error, extractor_version, evaluated_at)
                SELECT id, NULL, 'extracted', NULL, 'legacy', extracted_at
                FROM pages WHERE extracted_at IS NOT NULL
                """
            )
        # Errored extractions — the legacy extract_error text was one of a few
        # known sentinels. Map them so future re-runs can filter cleanly.
        if "extract_error" in cols:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO extract_runs
                    (page_id, run_id, outcome, error, extractor_version, evaluated_at)
                SELECT id, NULL,
                       CASE extract_error
                           WHEN 'no_recipe' THEN 'no_recipe'
                           WHEN 'html_file_missing' THEN 'html_missing'
                           ELSE 'legacy_error'
                       END,
                       CASE WHEN extract_error IN ('no_recipe', 'html_file_missing')
                            THEN NULL ELSE extract_error END,
                       'legacy',
                       ''
                FROM pages WHERE extract_error IS NOT NULL
                """
            )
        if "extracted_at" in cols:
            self.conn.execute("ALTER TABLE pages DROP COLUMN extracted_at")
        if "extract_error" in cols:
            self.conn.execute("ALTER TABLE pages DROP COLUMN extract_error")
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

    def mark_blocked(self, url: str, html_path: str | None = None):
        """Mark a page as blocked by the validator. The blocker reason lives
        in validate_html_runs.reason, written by whichever CLI ran validate;
        pages only tracks the bucketed status."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = 'blocked', html_path = ?, fetched_at = ? WHERE url = ?",
                (html_path, now, url),
            )
            self.conn.commit()

    def mark_content(self, url: str, status: str, html_path: str | None = None):
        """Mark a page with an arbitrary content status (JSON-LD @type,
        'unverified', etc.). The validate reason lives in
        validate_html_runs.reason, not on pages."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = ?, html_path = ?, fetched_at = ? WHERE url = ?",
                (status, html_path, now, url),
            )
            self.conn.commit()

    def mark_failed(self, url: str, error: str):
        """Record a fetch exception (network, HTTP error). fetch_error
        captures the exception message verbatim; after MAX_ATTEMPTS the row
        moves to status='failed' and drops out of the pending queue."""
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET attempts = attempts + 1, fetch_error = ? WHERE url = ?",
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

    def record_classify_url(
        self,
        *,
        page_id: int,
        run_id: int | None,
        label: str,
        model: str,
        prompt_version: str,
        raw_response: str | None,
        latency_ms: int | None,
        pages_content_type_before: str | None,
    ) -> None:
        """UPSERT the classify_url_runs row for this page and update
        pages.content_type atomically. Latest-only — re-running overwrites
        the prior row for this page_id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO classify_url_runs
                    (page_id, run_id, label, model, prompt_version,
                     raw_response, latency_ms, evaluated_at,
                     pages_content_type_before)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    label = excluded.label,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    raw_response = excluded.raw_response,
                    latency_ms = excluded.latency_ms,
                    evaluated_at = excluded.evaluated_at,
                    pages_content_type_before = excluded.pages_content_type_before
                """,
                (page_id, run_id, label, model, prompt_version, raw_response,
                 latency_ms, now, pages_content_type_before),
            )
            self.conn.execute(
                "UPDATE pages SET content_type = ? WHERE id = ?",
                (label, page_id),
            )
            self.conn.commit()

    def get_unclassified(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        """Work queue for the URL classifier. Returns rows with
        `content_type IS NULL`.

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
        """Candidate rows for the extractor: drink-recipe pages with cached
        HTML, excluding those with a known failure (`extract_runs.outcome !=
        'extracted'`).

        NOTE: this does NOT exclude pages that already succeeded — that check
        requires asking Supabase (the source of truth for "extracted"), and
        the DB layer deliberately stays Supabase-agnostic. `extract.py`
        layers the Supabase filter on top of these candidates.

        Covers both `likely_drink_recipe` (LLM-classified) and
        `confirmed_drink` (validate confirmed Schema.org Recipe + drink
        terms).
        """
        placeholders = ",".join("?" for _ in self.EXTRACT_CONTENT_TYPES)
        query = (
            "SELECT p.id, p.site, p.url, p.html_path, p.fetched_at FROM pages p "
            "LEFT JOIN extract_runs e ON e.page_id = p.id AND e.outcome != 'extracted' "
            f"WHERE p.content_type IN ({placeholders}) "
            "AND p.html_path IS NOT NULL "
            "AND e.page_id IS NULL"
        )
        params: list = list(self.EXTRACT_CONTENT_TYPES)
        if site:
            query += " AND p.site = ?"
            params.append(site)
        query += " ORDER BY p.id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def record_extract(
        self,
        *,
        page_id: int,
        run_id: int | None,
        outcome: str,
        error: str | None,
        extractor_version: str,
    ) -> None:
        """UPSERT the extract_runs row for this page. Latest-only; re-runs
        overwrite. `outcome` is 'extracted' | 'no_recipe' | 'html_missing'."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO extract_runs
                    (page_id, run_id, outcome, error, extractor_version, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    outcome = excluded.outcome,
                    error = excluded.error,
                    extractor_version = excluded.extractor_version,
                    evaluated_at = excluded.evaluated_at
                """,
                (page_id, run_id, outcome, error, extractor_version, now),
            )
            self.conn.commit()

    def clear_extract_runs(self, site: str | None = None) -> int:
        """Delete rows from extract_runs (scoped by drink-recipe content types
        — matching the extractor's work queue — and optionally by site).
        Returns deleted row count. Intended as the --reset equivalent for the
        extract CLI."""
        placeholders = ",".join("?" for _ in self.EXTRACT_CONTENT_TYPES)
        query = (
            f"DELETE FROM extract_runs WHERE page_id IN ("
            f"  SELECT id FROM pages WHERE content_type IN ({placeholders})"
        )
        params: list = list(self.EXTRACT_CONTENT_TYPES)
        if site:
            query += " AND site = ?"
            params.append(site)
        query += ")"
        with self._lock:
            cursor = self.conn.execute(query, params)
            self.conn.commit()
            return cursor.rowcount

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

    def sample_classify_url(
        self, site: str | None = None, label: str | None = None, n: int = 10
    ) -> list[dict]:
        """Return n random (site, url, label, raw_response, evaluated_at) rows
        from classify_url_runs, optionally filtered by site and/or label.

        classify_url_runs is already latest-only per page, so the sample is
        naturally de-duplicated across re-classifications.
        """
        query = [
            "SELECT p.site, p.url, c.label, c.raw_response, c.evaluated_at",
            "FROM classify_url_runs c JOIN pages p ON p.id = c.page_id",
        ]
        params: list = []
        wheres: list[str] = []
        if site:
            wheres.append("p.site = ?")
            params.append(site)
        if label:
            wheres.append("c.label = ?")
            params.append(label)
        if wheres:
            query.append("WHERE " + " AND ".join(wheres))
        query.append("ORDER BY RANDOM() LIMIT ?")
        params.append(n)
        with self._lock:
            rows = self.conn.execute(" ".join(query), params).fetchall()
        return [dict(r) for r in rows]

    def get_classify_url_for_urls(self, urls: list[str]) -> list[dict]:
        """Look up the classify_url_runs row for each URL. URLs not present in
        the DB (or present but never classified) are returned with label=None
        so callers can report 'not found' distinctly from 'has a label'."""
        if not urls:
            return []
        placeholders = ",".join("?" for _ in urls)
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT p.site, p.url, c.label, c.raw_response, c.evaluated_at
                FROM pages p
                LEFT JOIN classify_url_runs c ON c.page_id = p.id
                WHERE p.url IN ({placeholders})
                """,
                urls,
            ).fetchall()
        found = {r["url"]: dict(r) for r in rows}
        # Preserve input order; synthesize rows for URLs not in DB at all.
        return [
            found.get(u, {"site": None, "url": u, "label": None, "raw_response": None, "evaluated_at": None})
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
        row. A missing eval row is the only signal that a page needs to run."""
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

    def clear_classify_url_runs(self, site: str | None = None) -> int:
        return self._clear_eval_table("classify_url_runs", site)

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
