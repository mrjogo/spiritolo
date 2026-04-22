import threading

from scraper.src.db import Database


def test_init_creates_table(tmp_db):
    db = Database(tmp_db)
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
    ).fetchall()
    assert len(rows) == 1
    db.close()


def test_add_url_inserts_pending(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row is not None
    assert row["site"] == "testsite"
    assert row["status"] == "pending"
    db.close()


def test_add_url_skips_duplicates(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/1")
    count = db.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    assert count == 1
    db.close()


def test_get_pending_returns_pending_only(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.mark_content("https://example.com/recipe/1", "Recipe", "JSON-LD @type: Recipe", html_path="html/testsite/abc123.html")
    pending = db.get_pending()
    assert len(pending) == 1
    assert pending[0]["url"] == "https://example.com/recipe/2"
    db.close()


def test_get_pending_filters_by_site(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/recipe/1")
    db.add_url("site_b", "https://b.com/recipe/1")
    pending = db.get_pending(site="site_a")
    assert len(pending) == 1
    assert pending[0]["site"] == "site_a"
    db.close()


def test_get_pending_respects_limit(tmp_db):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/recipe/{i}")
    pending = db.get_pending(limit=3)
    assert len(pending) == 3
    db.close()


def test_mark_blocked(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_blocked("https://example.com/recipe/1", "cf-challenge detected")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["status"] == "blocked"
    assert row["error"] == "cf-challenge detected"
    db.close()


def test_mark_content(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_content("https://example.com/recipe/1", "Article", "JSON-LD @type: Article")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["status"] == "Article"
    assert row["fetched_at"] is not None
    db.close()


def test_mark_failed_increments_attempts(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_failed("https://example.com/recipe/1", "Connection timeout")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["attempts"] == 1
    assert row["status"] == "pending"  # still pending, under max attempts

    db.mark_failed("https://example.com/recipe/1", "Connection timeout")
    db.mark_failed("https://example.com/recipe/1", "Connection timeout")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["attempts"] == 3
    assert row["status"] == "failed"  # now failed after 3 attempts
    db.close()


def test_get_recent_statuses(tmp_db):
    db = Database(tmp_db)
    for i in range(5):
        db.add_url("testsite", f"https://example.com/recipe/{i}")
        db.mark_content(f"https://example.com/recipe/{i}", "Recipe", "JSON-LD @type: Recipe", html_path=f"html/testsite/{i}.html")
    for i in range(5, 8):
        db.add_url("testsite", f"https://example.com/recipe/{i}")
        db.mark_blocked(f"https://example.com/recipe/{i}", "blocked")
    statuses = db.get_recent_statuses("testsite", count=8)
    assert len(statuses) == 8
    blocked_count = sum(1 for s in statuses if s == "blocked")
    assert blocked_count == 3
    db.close()


def test_get_stats(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_a", "https://a.com/2")
    db.mark_content("https://a.com/1", "Recipe", "JSON-LD @type: Recipe", html_path="html/site_a/1.html")
    db.add_url("site_b", "https://b.com/1")
    stats = db.get_stats()
    assert stats == {"site_a": {"pending": 1, "Recipe": 1}, "site_b": {"pending": 1}}
    db.close()


def test_schema_has_content_type_column(tmp_db):
    db = Database(tmp_db)
    row = db.conn.execute("PRAGMA table_info(pages)").fetchall()
    columns = [r[1] for r in row]
    assert "content_type" in columns
    db.close()


def test_set_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.set_content_type("https://example.com/recipe/1", "likely_drink_recipe")
    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipe/1",),
    ).fetchone()
    assert row["content_type"] == "likely_drink_recipe"
    db.close()


def test_set_content_type_batch(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.add_url("testsite", "https://example.com/recipe/3")
    rows = db.conn.execute("SELECT id FROM pages ORDER BY id").fetchall()
    ids = [rows[0]["id"], rows[1]["id"]]
    db.set_content_type_batch(ids, "likely_food_recipe")
    updated = db.conn.execute(
        "SELECT content_type FROM pages WHERE id IN (?, ?)", tuple(ids)
    ).fetchall()
    assert all(r["content_type"] == "likely_food_recipe" for r in updated)
    third = db.conn.execute(
        "SELECT content_type FROM pages WHERE id = ?", (rows[2]["id"],)
    ).fetchone()
    assert third["content_type"] is None
    db.close()


def test_get_by_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/recipe/1")
    db.add_url("site_a", "https://a.com/recipe/2")
    db.add_url("site_b", "https://b.com/recipe/1")
    db.set_content_type("https://a.com/recipe/1", "likely_drink_recipe")
    db.set_content_type("https://a.com/recipe/2", "likely_drink_recipe")
    db.set_content_type("https://b.com/recipe/1", "likely_drink_recipe")
    all_drinks = db.get_by_content_type("likely_drink_recipe")
    assert len(all_drinks) == 3
    site_a_drinks = db.get_by_content_type("likely_drink_recipe", site="site_a")
    assert len(site_a_drinks) == 2
    limited = db.get_by_content_type("likely_drink_recipe", limit=1)
    assert len(limited) == 1
    db.close()


def test_schema_has_sitemap_source_column(tmp_db):
    db = Database(tmp_db)
    row = db.conn.execute("PRAGMA table_info(pages)").fetchall()
    columns = [r[1] for r in row]
    assert "sitemap_source" in columns
    db.close()


def test_add_urls_batch_stores_sitemap_source(tmp_db):
    db = Database(tmp_db)
    urls = ["https://example.com/recipe/1", "https://example.com/recipe/2"]
    db.add_urls_batch("testsite", urls, sitemap_source="https://example.com/sitemap-recipes.xml")
    rows = db.conn.execute("SELECT sitemap_source FROM pages").fetchall()
    assert all(r["sitemap_source"] == "https://example.com/sitemap-recipes.xml" for r in rows)
    db.close()


def test_get_pending_filters_by_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.add_url("testsite", "https://example.com/recipe/3")
    db.set_content_type("https://example.com/recipe/1", "likely_drink_recipe")
    db.set_content_type("https://example.com/recipe/2", "likely_food_recipe")
    pending = db.get_pending(content_type="likely_drink_recipe")
    assert len(pending) == 1
    assert pending[0]["url"] == "https://example.com/recipe/1"
    db.close()


def test_schema_has_classifications_table(tmp_db):
    db = Database(tmp_db)
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='classifications'"
    ).fetchall()
    assert len(rows) == 1
    cols = db.conn.execute("PRAGMA table_info(classifications)").fetchall()
    col_names = {r[1] for r in cols}
    assert {"id", "page_id", "label", "model", "prompt_version", "raw_response", "latency_ms", "created_at"} <= col_names
    db.close()


def test_record_classification_writes_both_tables(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    page_id = db.conn.execute("SELECT id FROM pages LIMIT 1").fetchone()["id"]

    db.record_classification(
        page_id=page_id,
        label="likely_drink_recipe",
        model="qwen3:14b",
        prompt_version="v1",
        raw_response='{"label": "likely_drink_recipe"}',
        latency_ms=423,
    )

    page = db.conn.execute("SELECT content_type FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert page["content_type"] == "likely_drink_recipe"

    clsf = db.conn.execute("SELECT * FROM classifications WHERE page_id = ?", (page_id,)).fetchone()
    assert clsf["label"] == "likely_drink_recipe"
    assert clsf["model"] == "qwen3:14b"
    assert clsf["prompt_version"] == "v1"
    assert clsf["raw_response"] == '{"label": "likely_drink_recipe"}'
    assert clsf["latency_ms"] == 423
    assert clsf["created_at"] is not None
    db.close()


def test_record_classification_allows_reclassification(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    page_id = db.conn.execute("SELECT id FROM pages LIMIT 1").fetchone()["id"]

    db.record_classification(page_id, "likely_drink_recipe", "qwen3:14b", "v1", "{}", 100)
    db.record_classification(page_id, "likely_food_recipe", "qwen3:14b", "v2", "{}", 100)

    rows = db.conn.execute("SELECT label, prompt_version FROM classifications WHERE page_id = ? ORDER BY id", (page_id,)).fetchall()
    assert [(r["label"], r["prompt_version"]) for r in rows] == [
        ("likely_drink_recipe", "v1"),
        ("likely_food_recipe", "v2"),
    ]
    page = db.conn.execute("SELECT content_type FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert page["content_type"] == "likely_food_recipe"
    db.close()


def test_get_unclassified_returns_null_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_a", "https://a.com/2")
    db.add_url("site_b", "https://b.com/1")
    db.set_content_type("https://a.com/1", "likely_drink_recipe")

    rows = db.get_unclassified()
    urls = sorted(r["url"] for r in rows)
    assert urls == ["https://a.com/2", "https://b.com/1"]
    db.close()


def test_get_unclassified_filters_by_site(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_b", "https://b.com/1")
    rows = db.get_unclassified(site="site_a")
    assert len(rows) == 1
    assert rows[0]["site"] == "site_a"
    db.close()


def test_get_unclassified_respects_limit(tmp_db):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified(limit=3)
    assert len(rows) == 3
    db.close()


def test_get_unclassified_includes_sitemap_source_and_id(tmp_db):
    db = Database(tmp_db)
    db.add_urls_batch("testsite", ["https://example.com/1"], sitemap_source="recipes.xml")
    rows = db.get_unclassified()
    assert rows[0]["sitemap_source"] == "recipes.xml"
    assert isinstance(rows[0]["id"], int)
    db.close()


def test_sample_classifications_returns_joined_rows(tmp_db):
    db = Database(tmp_db)
    for i in range(3):
        db.add_url("site_a", f"https://a.com/{i}")
    page_ids = [r["id"] for r in db.conn.execute("SELECT id FROM pages ORDER BY id").fetchall()]
    for pid in page_ids:
        db.record_classification(pid, "likely_drink_recipe", "qwen3:14b", "v1", '{"label":"likely_drink_recipe"}', 100)

    rows = db.sample_classifications(site="site_a", label="likely_drink_recipe", n=2)
    assert len(rows) == 2
    assert {r["url"] for r in rows} <= {"https://a.com/0", "https://a.com/1", "https://a.com/2"}
    assert rows[0]["label"] == "likely_drink_recipe"
    assert rows[0]["raw_response"] == '{"label":"likely_drink_recipe"}'
    db.close()


def test_sample_classifications_scopes_by_site_and_label(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_b", "https://b.com/1")
    a_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://a.com/1",)).fetchone()["id"]
    b_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://b.com/1",)).fetchone()["id"]
    db.record_classification(a_id, "likely_drink_recipe", "qwen3:14b", "v1", "{}", 100)
    db.record_classification(b_id, "likely_food_recipe", "qwen3:14b", "v1", "{}", 100)

    rows = db.sample_classifications(site="site_a", label="likely_drink_recipe", n=10)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://a.com/1"
    db.close()


def test_sample_classifications_deduplicates_reclassified_pages(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    pid = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://a.com/1",)).fetchone()["id"]
    db.record_classification(pid, "likely_drink_recipe", "qwen3:14b", "v1", "first", 100)
    db.record_classification(pid, "likely_drink_recipe", "qwen3:14b", "v2", "second", 100)

    rows = db.sample_classifications(site="site_a", label="likely_drink_recipe", n=10)
    assert len(rows) == 1
    assert rows[0]["raw_response"] == "second"
    db.close()


def test_schema_has_disabled_reason_column(tmp_db):
    db = Database(tmp_db)
    columns = [r[1] for r in db.conn.execute("PRAGMA table_info(pages)").fetchall()]
    assert "disabled_reason" in columns
    db.close()


def test_get_pending_excludes_disabled(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.conn.execute(
        "UPDATE pages SET disabled_reason = ? WHERE url = ?",
        ("canonical host mismatch", "https://example.com/recipe/1"),
    )
    db.conn.commit()
    pending = db.get_pending()
    assert len(pending) == 1
    assert pending[0]["url"] == "https://example.com/recipe/2"
    db.close()


def test_migrate_adds_disabled_reason_to_existing_db(tmp_db):
    """An existing DB that predates the disabled_reason column should be migrated
    in place on Database() init — verifies _migrate() runs ALTER TABLE."""
    import sqlite3

    conn = sqlite3.connect(tmp_db)
    conn.execute(
        """
        CREATE TABLE pages (
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
        )
        """
    )
    conn.execute(
        "INSERT INTO pages (site, url, discovered_at) VALUES (?, ?, ?)",
        ("testsite", "https://example.com/1", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    db = Database(tmp_db)
    columns = [r[1] for r in db.conn.execute("PRAGMA table_info(pages)").fetchall()]
    assert "disabled_reason" in columns
    row = db.conn.execute("SELECT disabled_reason FROM pages").fetchone()
    assert row["disabled_reason"] is None  # existing rows default to NULL (enabled)
    pending = db.get_pending()
    assert len(pending) == 1  # and still fetchable
    db.close()


def test_db_safe_from_multiple_threads(tmp_db):
    """Regression: Database used to raise 'SQLite objects created in a thread
    can only be used in that same thread' when accessed from worker threads.
    After adding check_same_thread=False + an internal lock, this must work."""
    from scraper.src.db import Database
    db = Database(tmp_db)
    errors: list[Exception] = []

    def worker(i: int):
        try:
            db.add_url("threadsite", f"https://example.com/{i}")
        except Exception as e:  # pragma: no cover - only hit if regression
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    rows = db.conn.execute("SELECT COUNT(*) AS c FROM pages").fetchone()
    assert rows["c"] == 10
    db.close()
