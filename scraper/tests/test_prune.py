"""Tests for scraper/src/prune.py — the unified pruning CLI for eval tables.

Eval tables are latest-only and regeneratable: deleting rows just schedules
re-evaluation on the next CLI run. The prune command is how we manage disk
usage without touching canonical state in `pages`.

Covers:
  - --stage <name>: scope to a single eval table
  - --older-than <iso>: delete rows evaluated before a timestamp
  - --except-version <v>: delete rows whose evaluator version differs
  - --site <s>: scope to a single site (joined via pages)
  - --all: delete every row in every eval table
  - pipeline_runs rows persist; we never cascade into them
"""

from datetime import datetime, timezone
from pathlib import Path

from scraper.src.db import Database
from scraper.src.prune import STAGE_TABLES, prune_stage, prune_all


def _seed(db, site, url, html_path):
    db.add_url(site, url)
    db.mark_content(url, "Recipe", html_path=html_path)


def _record_validate(db, url, *, version, evaluated_at, run_id=None):
    page_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()["id"]
    db.conn.execute(
        "INSERT OR REPLACE INTO validate_html_runs "
        "(page_id, run_id, status, reason, validator_version, evaluated_at, pages_status_before) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (page_id, run_id, "Recipe", None, version, evaluated_at, "Recipe"),
    )
    db.conn.commit()
    return page_id


def test_stage_tables_registry_covers_all_eval_stages():
    """STAGE_TABLES is the canonical mapping between stage name and table +
    version column. If we add a new stage, we add it here — the prune CLI
    reads from this registry so --stage accepts exactly these names."""
    assert set(STAGE_TABLES) == {
        "classify_url", "validate_html", "classify_drink", "extract",
    }
    for stage, (table, version_col) in STAGE_TABLES.items():
        assert isinstance(table, str)
        assert isinstance(version_col, str)


def test_prune_stage_older_than(tmp_db):
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/a", "a.html")
    _seed(db, "imbibe", "https://imbibe.com/b", "b.html")
    _record_validate(db, "https://imbibe.com/a", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://imbibe.com/b", version="v1", evaluated_at="2026-04-01T00:00:00+00:00")

    deleted = prune_stage(db, "validate_html", older_than="2026-03-01T00:00:00+00:00")

    assert deleted == 1
    rows = db.conn.execute(
        "SELECT p.url FROM validate_html_runs v JOIN pages p ON p.id = v.page_id"
    ).fetchall()
    assert [r["url"] for r in rows] == ["https://imbibe.com/b"]
    db.close()


def test_prune_stage_except_version(tmp_db):
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/a", "a.html")
    _seed(db, "imbibe", "https://imbibe.com/b", "b.html")
    _record_validate(db, "https://imbibe.com/a", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://imbibe.com/b", version="v2", evaluated_at="2026-01-01T00:00:00+00:00")

    deleted = prune_stage(db, "validate_html", except_version="v2")

    assert deleted == 1
    rows = db.conn.execute(
        "SELECT validator_version FROM validate_html_runs"
    ).fetchall()
    assert [r["validator_version"] for r in rows] == ["v2"]
    db.close()


def test_prune_stage_site_scope(tmp_db):
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/a", "a.html")
    _seed(db, "punch", "https://punch.com/b", "b.html")
    _record_validate(db, "https://imbibe.com/a", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://punch.com/b", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")

    deleted = prune_stage(db, "validate_html", site="imbibe")

    assert deleted == 1
    rows = db.conn.execute(
        "SELECT p.site FROM validate_html_runs v JOIN pages p ON p.id = v.page_id"
    ).fetchall()
    assert [r["site"] for r in rows] == ["punch"]
    db.close()


def test_prune_stage_filters_compose(tmp_db):
    """When multiple filters are passed, they AND together: only rows matching
    every filter are deleted."""
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/old-v1", "x.html")
    _seed(db, "imbibe", "https://imbibe.com/old-v2", "y.html")
    _seed(db, "imbibe", "https://imbibe.com/new-v1", "z.html")
    _record_validate(db, "https://imbibe.com/old-v1", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://imbibe.com/old-v2", version="v2", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://imbibe.com/new-v1", version="v1", evaluated_at="2026-06-01T00:00:00+00:00")

    # Delete "older than March AND not v2" → only "old-v1" qualifies.
    deleted = prune_stage(
        db, "validate_html",
        older_than="2026-03-01T00:00:00+00:00",
        except_version="v2",
    )
    assert deleted == 1
    urls = db.conn.execute(
        "SELECT p.url FROM validate_html_runs v JOIN pages p ON p.id = v.page_id ORDER BY p.url"
    ).fetchall()
    assert {r["url"] for r in urls} == {
        "https://imbibe.com/old-v2",
        "https://imbibe.com/new-v1",
    }
    db.close()


def test_prune_stage_without_filters_deletes_everything_in_stage(tmp_db):
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/a", "a.html")
    _seed(db, "imbibe", "https://imbibe.com/b", "b.html")
    _record_validate(db, "https://imbibe.com/a", version="v1", evaluated_at="2026-01-01T00:00:00+00:00")
    _record_validate(db, "https://imbibe.com/b", version="v2", evaluated_at="2026-01-01T00:00:00+00:00")

    deleted = prune_stage(db, "validate_html")

    assert deleted == 2
    assert db.conn.execute("SELECT COUNT(*) c FROM validate_html_runs").fetchone()["c"] == 0
    db.close()


def test_prune_stage_unknown_stage_raises(tmp_db):
    db = Database(tmp_db)
    try:
        prune_stage(db, "bogus_stage")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "bogus_stage" in str(e)
    db.close()


def test_prune_all_wipes_every_eval_table_but_keeps_pipeline_runs(tmp_db):
    """--all empties every *_runs table so next run re-evaluates everything,
    but leaves pipeline_runs alone (those are history for 'what ran when')."""
    db = Database(tmp_db)
    _seed(db, "imbibe", "https://imbibe.com/a", "a.html")
    run_id = db.start_run(stage="validate_html")
    _record_validate(db, "https://imbibe.com/a", version="v1", evaluated_at="2026-01-01T00:00:00+00:00", run_id=run_id)

    counts = prune_all(db)

    assert counts["validate_html_runs"] == 1
    for table in ("classify_url_runs", "validate_html_runs", "classify_drink_runs", "extract_runs"):
        assert db.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0

    # pipeline_runs is untouched — it's audit metadata, not evaluator output.
    assert db.conn.execute("SELECT COUNT(*) c FROM pipeline_runs").fetchone()["c"] == 1
    db.close()
