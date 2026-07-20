import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 3


class DatabaseNotMigratedError(RuntimeError):
    """Raised when opening a DB whose schema doesn't match what ``migrate()``
    would produce.

    The constructor never mutates the database — callers must run
    ``python -m scraper.db migrate --db <path>`` (or call ``migrate(path)``
    programmatically) before opening it.
    """

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

CREATE_EVAL_RUN_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_classify_url_runs_run_id ON classify_url_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_validate_html_runs_run_id ON validate_html_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_classify_drink_runs_run_id ON classify_drink_runs(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage ON pipeline_runs(stage);",
]


def _create_schema(conn: sqlite3.Connection) -> None:
    """Apply every CREATE statement that defines the modern schema.

    Used by ``migrate()`` against the on-disk DB and by
    ``_expected_signature()`` against an in-memory DB to derive the
    structural target. Anything that mutates schema must go in here (or in
    ``_apply_legacy_migrations`` for one-shot fix-ups) — otherwise the
    in-memory expected signature won't include it and DBs will be flagged
    as drifted.
    """
    conn.execute(CREATE_TABLE)
    for idx in CREATE_INDEXES:
        conn.execute(idx)
    conn.execute(CREATE_PIPELINE_RUNS_TABLE)
    conn.execute(CREATE_CLASSIFY_URL_RUNS_TABLE)
    conn.execute(CREATE_VALIDATE_HTML_RUNS_TABLE)
    conn.execute(CREATE_CLASSIFY_DRINK_RUNS_TABLE)
    for idx in CREATE_EVAL_RUN_INDEXES:
        conn.execute(idx)
    conn.commit()


def migrate(db_path: str | Path) -> None:
    """Bring the SQLite DB at ``db_path`` to the current schema.

    Creates the file and parent directory if missing. Idempotent: applies
    the CREATE TABLE / CREATE INDEX statements (no-ops on a current DB) and
    the one-shot legacy column fix-ups in ``_apply_legacy_migrations``.

    This is the *only* place that mutates schema. ``Database.__init__``
    opens DBs read-structure-only and refuses to run if the live structure
    doesn't match what ``migrate()`` would produce.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        _create_schema(conn)
        _apply_legacy_migrations(conn)
    finally:
        conn.close()


# Canonical, structural representation of a SQLite schema. We compare these
# tuples element-by-element rather than hashing — equal tuples mean equal
# schema, and the first divergence is the diff to show in the error message.
_SchemaSignature = tuple[str, ...]


def _schema_signature(conn: sqlite3.Connection) -> _SchemaSignature:
    """Stable, ordered description of every user-defined table & index.

    Built from PRAGMA introspection (not ``sqlite_master.sql``) because the
    stored CREATE text varies by code path — a column added via ALTER ADD
    leaves a different SQL string than the same column declared in CREATE,
    even though the live structure is identical.

    Comparing two signatures answers "would migrate() produce this DB?"
    without anyone having to maintain a version constant.
    """
    parts: list[str] = []

    table_names = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    for t in table_names:
        parts.append(f"table {t}")
        # PRAGMA returns rows in column order: (cid, name, type, notnull,
        # dflt_value, pk). One signature line per column — including its
        # position — so a one-column change diffs as one line, not a whole
        # block.
        for pos, c in enumerate(conn.execute(f'PRAGMA table_info("{t}")')):
            parts.append(
                f"  {t}.col[{pos}] {c[1]} type={c[2]} notnull={c[3]} "
                f"dflt={c[4]!r} pk={c[5]}"
            )

    # User-defined indexes only (sql IS NOT NULL filters out the auto-created
    # PRIMARY KEY / UNIQUE indexes — those are already encoded in table_info).
    # Tuple-ify rows so sorted() works regardless of the connection's
    # row_factory (Database sets it to sqlite3.Row, which is unorderable).
    idx_rows = sorted(
        (r[0], r[1]) for r in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master "
            "WHERE type = 'index' AND sql IS NOT NULL"
        )
    )
    for name, tbl in idx_rows:
        cols = [c[2] for c in conn.execute(f'PRAGMA index_info("{name}")')]
        unique = next(
            (r[2] for r in conn.execute(f'PRAGMA index_list("{tbl}")') if r[1] == name),
            0,
        )
        parts.append(f"index {name} on {tbl}({','.join(cols)}) unique={unique}")

    return tuple(parts)


_expected_signature_cache: _SchemaSignature | None = None


def _expected_signature() -> _SchemaSignature:
    """Signature of a freshly-migrated DB. Computed once per process by
    running ``_create_schema`` against an in-memory DB and snapshotting it,
    so runtime cost is paid on the first ``Database()`` open per process."""
    global _expected_signature_cache
    if _expected_signature_cache is None:
        with sqlite3.connect(":memory:") as c:
            _create_schema(c)
            _expected_signature_cache = _schema_signature(c)
    return _expected_signature_cache


def _signature_diff(actual: _SchemaSignature, expected: _SchemaSignature) -> str:
    """Human-readable rundown of which schema parts are missing/unexpected.
    Used to make the DatabaseNotMigratedError message actionable."""
    actual_set = set(actual)
    expected_set = set(expected)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    lines: list[str] = []
    if missing:
        lines.append("Missing or wrong shape:")
        lines.extend(f"  - {m}" for m in missing)
    if extra:
        lines.append("Unexpected (not produced by migrate):")
        lines.extend(f"  + {e}" for e in extra)
    return "\n".join(lines) if lines else "(no differences — bug in _schema_signature?)"


def _apply_legacy_migrations(conn: sqlite3.Connection) -> None:
    """One-shot fix-ups for DBs created before the modern schema. Each step
    is idempotent — on a fresh DB (just created by the CREATE TABLE block in
    ``migrate()``) every check short-circuits."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(pages)")}
    if "disabled_reason" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN disabled_reason TEXT")
        conn.commit()
    if "error" in cols and "fetch_error" not in cols:
        # Narrow the column to its current meaning: "last fetch exception".
        # Validate reasons (which historically shared this column) moved
        # to validate_html_runs.reason, so clear them on non-failed rows.
        # Re-running validate re-populates those reasons in the eval table.
        conn.execute("ALTER TABLE pages RENAME COLUMN error TO fetch_error")
        conn.execute("UPDATE pages SET fetch_error = NULL WHERE status != 'failed'")
        conn.commit()
    if "validated_at" in cols:
        # Replaced by validate_html_runs — work queue now joins against
        # the presence of an eval row, not this timestamp.
        conn.execute("ALTER TABLE pages DROP COLUMN validated_at")
        conn.commit()
    # Legacy `classifications` table was superseded by `classify_url_runs`.
    conn.execute("DROP TABLE IF EXISTS classifications")
    # `extract_runs` bookkeeping moved to the Zone-2 extract-recipe stage; drop
    # the table so an existing DB re-migrates to the current schema instead of
    # tripping the drift check with a table migrate() no longer creates.
    conn.execute("DROP TABLE IF EXISTS extract_runs")
    conn.commit()


class Database:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        if not path.exists():
            raise DatabaseNotMigratedError(
                f"No SQLite database at {path}. Create it with:\n"
                f"  cd scraper && uv run python -m scraper.db migrate --db {path}"
            )
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        actual = _schema_signature(self.conn)
        expected = _expected_signature()
        if actual != expected:
            self.conn.close()
            raise DatabaseNotMigratedError(
                f"Schema at {path} doesn't match what migrate() would produce.\n"
                f"{_signature_diff(actual, expected)}\n"
                f"Run:\n"
                f"  cd scraper && uv run python -m scraper.db migrate --db {path}"
            )

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
        """Work queue: pages with cached HTML that are missing EITHER the
        validate_html_runs row or the classify_drink_runs row.

        Both eval rows are written together (by fetch or validate), so a page
        missing only one indicates an interrupted run. Including it in the
        queue heals the gap on next invocation — the remaining eval is
        idempotent UPSERT, so re-running both sides is safe."""
        query = [
            "SELECT p.id, p.site, p.url, p.status, p.content_type, p.html_path",
            "FROM pages p",
            "LEFT JOIN validate_html_runs v ON v.page_id = p.id",
            "LEFT JOIN classify_drink_runs d ON d.page_id = p.id",
            "WHERE p.html_path IS NOT NULL",
            "AND (v.page_id IS NULL OR d.page_id IS NULL)",
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
            "LEFT JOIN classify_drink_runs d ON d.page_id = p.id",
            "WHERE p.html_path IS NOT NULL",
            "AND (v.page_id IS NULL OR d.page_id IS NULL)",
        ]
        params: list = []
        if site:
            query.append("AND p.site = ?")
            params.append(site)
        with self._lock:
            return self.conn.execute(" ".join(query), params).fetchone()["c"]

    # Per-eval-table metadata. Each stage's --reset CLI uses this to build the
    # DELETE filters (site, except_version, older_than) uniformly.
    EVAL_TABLES: dict[str, dict[str, str]] = {
        "classify_url_runs":   {"version_col": "prompt_version"},
        "validate_html_runs":  {"version_col": "validator_version"},
        "classify_drink_runs": {"version_col": "scorer_version"},
    }

    def clear_eval_rows(
        self,
        table: str,
        *,
        site: str | None = None,
        except_version: str | None = None,
        older_than: str | None = None,
    ) -> int:
        """Delete rows from one eval table, filtered by any combination of
        site / except_version / older_than (ANDed). No filters → wipe the
        table. Returns deleted row count. Whether re-queuing needs a
        companion pages.* update is the caller's responsibility."""
        if table not in self.EVAL_TABLES:
            raise ValueError(f"unknown eval table: {table!r}")
        version_col = self.EVAL_TABLES[table]["version_col"]
        wheres: list[str] = []
        params: list = []
        if site is not None:
            wheres.append("page_id IN (SELECT id FROM pages WHERE site = ?)")
            params.append(site)
        if except_version is not None:
            wheres.append(f"{version_col} != ?")
            params.append(except_version)
        if older_than is not None:
            wheres.append("evaluated_at < ?")
            params.append(older_than)
        query = f"DELETE FROM {table}"
        if wheres:
            query += " WHERE " + " AND ".join(wheres)
        with self._lock:
            cursor = self.conn.execute(query, params)
            self.conn.commit()
            return cursor.rowcount

    def count_eval_rows(
        self,
        table: str,
        *,
        site: str | None = None,
        except_version: str | None = None,
        older_than: str | None = None,
    ) -> int:
        """Count rows that clear_eval_rows with the same filters would delete.
        Used by --reset to render the confirmation prompt."""
        if table not in self.EVAL_TABLES:
            raise ValueError(f"unknown eval table: {table!r}")
        version_col = self.EVAL_TABLES[table]["version_col"]
        wheres: list[str] = []
        params: list = []
        if site is not None:
            wheres.append("page_id IN (SELECT id FROM pages WHERE site = ?)")
            params.append(site)
        if except_version is not None:
            wheres.append(f"{version_col} != ?")
            params.append(except_version)
        if older_than is not None:
            wheres.append("evaluated_at < ?")
            params.append(older_than)
        query = f"SELECT COUNT(*) c FROM {table}"
        if wheres:
            query += " WHERE " + " AND ".join(wheres)
        with self._lock:
            return self.conn.execute(query, params).fetchone()["c"]

    def reset_classify_url(
        self,
        *,
        site: str | None = None,
        except_version: str | None = None,
        older_than: str | None = None,
    ) -> int:
        """classify's --reset needs BOTH the eval-row delete AND a
        pages.content_type=NULL update for the same rows — the classify work
        queue gates on `content_type IS NULL`, not on eval-row presence.

        Done in a single transaction so a crash can't leave pages where the
        eval row is gone but content_type is still set (which would put the
        rows out of both the queue and the audit trail).
        Returns the number of eval rows deleted."""
        version_col = "prompt_version"
        wheres: list[str] = []
        params: list = []
        if site is not None:
            wheres.append("page_id IN (SELECT id FROM pages WHERE site = ?)")
            params.append(site)
        if except_version is not None:
            wheres.append(f"{version_col} != ?")
            params.append(except_version)
        if older_than is not None:
            wheres.append("evaluated_at < ?")
            params.append(older_than)
        where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        with self._lock:
            # Snapshot matching page_ids first; we need them for the
            # content_type null-out after the DELETE removes the rows.
            page_ids = [
                r[0] for r in self.conn.execute(
                    f"SELECT page_id FROM classify_url_runs{where_clause}",
                    params,
                ).fetchall()
            ]
            if not page_ids:
                return 0
            placeholders = ",".join("?" for _ in page_ids)
            cursor = self.conn.execute(
                f"DELETE FROM classify_url_runs WHERE page_id IN ({placeholders})",
                page_ids,
            )
            self.conn.execute(
                f"UPDATE pages SET content_type = NULL WHERE id IN ({placeholders})",
                page_ids,
            )
            self.conn.commit()
            return cursor.rowcount

    # Backwards-compat shims — kept so existing call sites keep working.
    def clear_validate_html_runs(self, site: str | None = None) -> int:
        return self.clear_eval_rows("validate_html_runs", site=site)

    def clear_classify_drink_runs(self, site: str | None = None) -> int:
        return self.clear_eval_rows("classify_drink_runs", site=site)

    def clear_classify_url_runs(self, site: str | None = None) -> int:
        return self.clear_eval_rows("classify_url_runs", site=site)


if __name__ == "__main__":
    import argparse

    # Match the DEFAULT_DB_PATH used by fetch.py / discover.py / etc.: the
    # repo-root data/ dir, not scraper/data/. db.py is at scraper/src/db.py,
    # so .parent.parent.parent is the repo root.
    _DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "scraper.db"

    parser = argparse.ArgumentParser(
        description="Manage the scraper SQLite database schema."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_migrate = sub.add_parser(
        "migrate",
        help="Create the DB if missing and bring its schema current. Idempotent.",
    )
    p_migrate.add_argument(
        "--db", default=str(_DEFAULT_DB_PATH),
        help=f"Path to the SQLite database (default: {_DEFAULT_DB_PATH}).",
    )

    p_status = sub.add_parser(
        "status",
        help="Compare the DB's schema against what migrate() would produce.",
    )
    p_status.add_argument("--db", default=str(_DEFAULT_DB_PATH))

    args = parser.parse_args()

    if args.command == "migrate":
        migrate(args.db)
        print(f"Migrated {args.db}.")
    elif args.command == "status":
        path = Path(args.db)
        if not path.exists():
            print(f"{path}: does not exist")
            raise SystemExit(1)
        with sqlite3.connect(path) as c:
            actual = _schema_signature(c)
        expected = _expected_signature()
        if actual == expected:
            print(f"{path}: schema matches.")
        else:
            print(f"{path}: schema does NOT match.")
            print(_signature_diff(actual, expected))
            raise SystemExit(1)
