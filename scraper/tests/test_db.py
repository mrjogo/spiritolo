import threading

from scraper.src.db import Database


def test_init_creates_table(tmp_db):
    db = Database(tmp_db)
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
    ).fetchall()
    assert len(rows) == 1
    db.close()


def test_pages_has_validated_at_column(tmp_db):
    db = Database(tmp_db)
    cols = {row["name"] for row in db.conn.execute("PRAGMA table_info(pages)")}
    assert "validated_at" in cols
    db.close()


def test_mark_validated_sets_timestamp(tmp_db):
    db = Database(tmp_db)
    db.add_url("s", "https://e.com/x")
    db.mark_validated("https://e.com/x")
    row = db.conn.execute(
        "SELECT validated_at FROM pages WHERE url = ?", ("https://e.com/x",)
    ).fetchone()
    assert row["validated_at"] is not None
    db.close()


def _seed_fetched(db, site, url, html_path):
    """Mark a URL as fetched with cached HTML — required before validated_at
    is meaningful (validate only runs on html_path IS NOT NULL rows)."""
    db.add_url(site, url)
    db.mark_content(url, "Recipe", "ok", html_path=html_path)


def test_clear_validated_at_respects_site_scope(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    db.mark_validated("https://imbibe.com/a")
    db.mark_validated("https://punch.com/b")

    cleared = db.clear_validated_at(site="imbibe")
    assert cleared == 1

    rows = {row["url"]: row["validated_at"] for row in db.conn.execute(
        "SELECT url, validated_at FROM pages"
    )}
    assert rows["https://imbibe.com/a"] is None
    assert rows["https://punch.com/b"] is not None
    db.close()


def test_clear_validated_at_without_site_clears_all(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    db.mark_validated("https://imbibe.com/a")
    db.mark_validated("https://punch.com/b")

    assert db.clear_validated_at() == 2

    for row in db.conn.execute("SELECT validated_at FROM pages"):
        assert row["validated_at"] is None
    db.close()


def test_clear_validated_at_skips_rows_without_html_path(tmp_db):
    """Rows that were never fetched shouldn't be touched — their validated_at
    is always NULL, but the reset should report zero and not count them."""
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/pending")  # no html_path
    assert db.clear_validated_at() == 0
    db.close()


def test_count_pending_validation(tmp_db):
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    db.add_url("imbibe", "https://imbibe.com/b")
    db.add_url("punch", "https://punch.com/c")
    # Simulate fetched pages with html_path set.
    db.mark_content("https://imbibe.com/a", "Recipe", "ok", html_path="imbibe/a.html")
    db.mark_content("https://imbibe.com/b", "Recipe", "ok", html_path="imbibe/b.html")
    db.mark_content("https://punch.com/c", "Recipe", "ok", html_path="punch/c.html")
    db.mark_validated("https://imbibe.com/a")

    assert db.count_pending_validation() == 2
    assert db.count_pending_validation(site="imbibe") == 1
    assert db.count_pending_validation(site="punch") == 1
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


def test_get_unextracted_returns_drink_recipe_buckets_with_html(tmp_db):
    """Extractor queue covers both `likely_drink_recipe` (LLM-classified) and
    `confirmed_drink` (validate.py Schema.org Recipe + drink terms). Filters out
    rows without html_path, rows already extracted, and food/other buckets."""
    from scraper.src.db import Database
    db = Database(tmp_db)
    db.add_urls_batch(
        "difs",
        [
            "https://x/a", "https://x/b", "https://x/c", "https://x/d",
            "https://x/e", "https://x/f", "https://x/g",
        ],
    )
    # a: likely_drink_recipe + fetched
    db.set_content_type("https://x/a", "likely_drink_recipe")
    db.mark_content("https://x/a", "valid", "ok", html_path="difs/a.html")
    # b: likely_drink_recipe but no html_path
    db.set_content_type("https://x/b", "likely_drink_recipe")
    # c: fetched but not a drink recipe
    db.set_content_type("https://x/c", "likely_food_recipe")
    db.mark_content("https://x/c", "valid", "ok", html_path="difs/c.html")
    # d: likely_drink_recipe, fetched, already extracted
    db.set_content_type("https://x/d", "likely_drink_recipe")
    db.mark_content("https://x/d", "valid", "ok", html_path="difs/d.html")
    db.mark_extracted("https://x/d")
    # e: confirmed_drink + fetched → should be queued
    db.set_content_type("https://x/e", "confirmed_drink")
    db.mark_content("https://x/e", "Recipe", "ok", html_path="difs/e.html")
    # f: confirmed_drink, already extracted → excluded
    db.set_content_type("https://x/f", "confirmed_drink")
    db.mark_content("https://x/f", "Recipe", "ok", html_path="difs/f.html")
    db.mark_extracted("https://x/f")
    # g: confirmed_food (even with html) → excluded
    db.set_content_type("https://x/g", "confirmed_food")
    db.mark_content("https://x/g", "Recipe", "ok", html_path="difs/g.html")

    rows = db.get_unextracted()
    urls = sorted(r["url"] for r in rows)
    assert urls == ["https://x/a", "https://x/e"]
    db.close()


def test_reset_extract_state_covers_drink_recipe_buckets(tmp_db):
    """reset_extract_state must clear extracted_at/extract_error on both
    likely_drink_recipe and confirmed_drink — same scope as the extractor queue.
    Must NOT touch food/other buckets."""
    from scraper.src.db import Database
    db = Database(tmp_db)
    db.add_urls_batch("difs", ["https://x/a", "https://x/b", "https://x/c"])
    db.set_content_type("https://x/a", "likely_drink_recipe")
    db.set_content_type("https://x/b", "confirmed_drink")
    db.set_content_type("https://x/c", "confirmed_food")
    db.mark_content("https://x/a", "valid", "ok", html_path="difs/a.html")
    db.mark_content("https://x/b", "Recipe", "ok", html_path="difs/b.html")
    db.mark_content("https://x/c", "Recipe", "ok", html_path="difs/c.html")
    db.mark_extracted("https://x/a")
    db.mark_extract_error("https://x/b", "no_recipe")
    db.mark_extracted("https://x/c")

    n = db.reset_extract_state()
    assert n == 2  # only the two drink-bucket rows

    import sqlite3
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    rows = {r["url"]: r for r in conn.execute(
        "SELECT url, extracted_at, extract_error FROM pages"
    ).fetchall()}
    assert rows["https://x/a"]["extracted_at"] is None
    assert rows["https://x/a"]["extract_error"] is None
    assert rows["https://x/b"]["extracted_at"] is None
    assert rows["https://x/b"]["extract_error"] is None
    # confirmed_food row untouched
    assert rows["https://x/c"]["extracted_at"] is not None
    db.close()


def test_reset_extract_state_scoped_by_site(tmp_db):
    from scraper.src.db import Database
    db = Database(tmp_db)
    db.add_url("site_a", "https://a/1")
    db.add_url("site_b", "https://b/1")
    db.set_content_type("https://a/1", "confirmed_drink")
    db.set_content_type("https://b/1", "confirmed_drink")
    db.mark_content("https://a/1", "Recipe", "ok", html_path="a/1.html")
    db.mark_content("https://b/1", "Recipe", "ok", html_path="b/1.html")
    db.mark_extracted("https://a/1")
    db.mark_extracted("https://b/1")

    n = db.reset_extract_state(site="site_a")
    assert n == 1
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    rows = {r["url"]: r for r in conn.execute("SELECT url, extracted_at FROM pages").fetchall()}
    assert rows["https://a/1"]["extracted_at"] is None
    assert rows["https://b/1"]["extracted_at"] is not None
    db.close()


def test_mark_extract_error_blocks_reprocessing(tmp_db):
    from scraper.src.db import Database
    db = Database(tmp_db)
    db.add_urls_batch("difs", ["https://x/a"])
    db.set_content_type("https://x/a", "likely_drink_recipe")
    db.mark_content("https://x/a", "valid", "ok", html_path="difs/a.html")

    assert len(db.get_unextracted()) == 1
    db.mark_extract_error("https://x/a", "no_jsonld_recipe")
    assert db.get_unextracted() == []
    db.close()


def test_mark_extracted_clears_extract_error(tmp_db):
    from scraper.src.db import Database
    db = Database(tmp_db)
    db.add_urls_batch("difs", ["https://x/a"])
    db.set_content_type("https://x/a", "likely_drink_recipe")
    db.mark_content("https://x/a", "valid", "ok", html_path="difs/a.html")
    db.mark_extract_error("https://x/a", "no_jsonld_recipe")

    db.mark_extracted("https://x/a")
    # extract_error should be cleared on success
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("select extracted_at, extract_error from pages where url = ?", ("https://x/a",)).fetchone()
    assert row[0] is not None
    assert row[1] is None
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


# ---------------------------------------------------------------------------
# Pipeline runs + per-stage eval tables
#
# Each evaluator (classify_url, validate_html, classify_drink, extract) gets
# its own `*_runs` table keyed by page_id PK. Latest-only: re-running an
# evaluator UPSERTs, overwriting the previous row for that page. The design
# note: dropping any `*_runs` table is a safe operation — pages still works,
# the stage just needs to re-evaluate on the next run.
# ---------------------------------------------------------------------------


def test_pipeline_runs_table_exists(tmp_db):
    db = Database(tmp_db)
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(pipeline_runs)")}
    assert cols == {"id", "stage", "started_at", "finished_at", "site", "args", "summary"}
    db.close()


def test_classify_url_runs_table_exists(tmp_db):
    db = Database(tmp_db)
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(classify_url_runs)")}
    assert cols == {
        "page_id", "run_id", "label", "model", "prompt_version",
        "raw_response", "latency_ms", "evaluated_at", "pages_content_type_before",
    }
    # page_id is the PK, enforcing one row per page (latest-only).
    pk_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(classify_url_runs)") if r[5]]
    assert pk_cols == ["page_id"]
    db.close()


def test_validate_html_runs_table_exists(tmp_db):
    db = Database(tmp_db)
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(validate_html_runs)")}
    assert cols == {
        "page_id", "run_id", "status", "reason",
        "validator_version", "evaluated_at", "pages_status_before",
    }
    pk_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(validate_html_runs)") if r[5]]
    assert pk_cols == ["page_id"]
    db.close()


def test_classify_drink_runs_table_exists(tmp_db):
    db = Database(tmp_db)
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(classify_drink_runs)")}
    assert cols == {
        "page_id", "run_id", "label", "score", "score_detail",
        "scorer_version", "evaluated_at", "pages_content_type_before",
    }
    pk_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(classify_drink_runs)") if r[5]]
    assert pk_cols == ["page_id"]
    db.close()


def test_extract_runs_table_exists(tmp_db):
    db = Database(tmp_db)
    cols = {row[1] for row in db.conn.execute("PRAGMA table_info(extract_runs)")}
    assert cols == {
        "page_id", "run_id", "outcome", "error",
        "extractor_version", "evaluated_at",
    }
    pk_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(extract_runs)") if r[5]]
    assert pk_cols == ["page_id"]
    db.close()


def test_backfill_classify_url_runs_from_legacy_classifications(tmp_db):
    """Opening a DB that has legacy `classifications` rows but an empty
    `classify_url_runs` table should backfill one row per page using the
    most-recent classification for that page. Older rows are dropped (we keep
    latest-only). Subsequent re-opens are idempotent."""
    # Seed via a first open, then inject legacy rows directly so we can replay
    # the "existing-DB upgrade" path on the second open.
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    db.add_url("imbibe", "https://imbibe.com/b")
    page_a = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://imbibe.com/a",)).fetchone()["id"]
    page_b = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://imbibe.com/b",)).fetchone()["id"]
    db.conn.executemany(
        "INSERT INTO classifications (page_id, label, model, prompt_version, raw_response, latency_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (page_a, "likely_food_recipe", "qwen3:14b", "v1", "raw-old", 100, "2026-01-01T00:00:00+00:00"),
            (page_a, "likely_drink_recipe", "qwen3:14b", "v2", "raw-new", 120, "2026-02-01T00:00:00+00:00"),
            (page_b, "likely_junk", "qwen3:14b", "v2", None, 80, "2026-02-01T00:00:00+00:00"),
        ],
    )
    # Wipe out the backfill that the first open already did, simulating a
    # pre-migration DB.
    db.conn.execute("DELETE FROM classify_url_runs")
    db.conn.commit()
    db.close()

    # Second open triggers the migration.
    db = Database(tmp_db)
    rows = {r["page_id"]: dict(r) for r in db.conn.execute(
        "SELECT page_id, label, model, prompt_version, raw_response, latency_ms, evaluated_at "
        "FROM classify_url_runs"
    )}
    assert set(rows) == {page_a, page_b}
    # Latest-per-page: page_a should have the v2 row, not v1.
    assert rows[page_a]["label"] == "likely_drink_recipe"
    assert rows[page_a]["prompt_version"] == "v2"
    assert rows[page_a]["raw_response"] == "raw-new"
    assert rows[page_a]["latency_ms"] == 120
    assert rows[page_a]["evaluated_at"] == "2026-02-01T00:00:00+00:00"
    assert rows[page_b]["label"] == "likely_junk"

    # Opening again is idempotent — no duplicate rows, no overwrite.
    db.close()
    db = Database(tmp_db)
    count = db.conn.execute("SELECT COUNT(*) c FROM classify_url_runs").fetchone()["c"]
    assert count == 2
    db.close()


def test_backfill_skips_when_classify_url_runs_already_has_rows(tmp_db):
    """If classify_url_runs already has data, the migration must not re-copy
    from classifications — user may have already pruned old classifications,
    and we shouldn't resurrect them."""
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    db.conn.execute(
        "INSERT INTO classify_url_runs "
        "(page_id, label, model, prompt_version, raw_response, latency_ms, evaluated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (page_id, "likely_drink_recipe", "qwen3:14b", "v3", None, 100, "2026-03-01T00:00:00+00:00"),
    )
    # Legacy row that should NOT be copied (because the runs table already has data).
    db.conn.execute(
        "INSERT INTO classifications (page_id, label, model, prompt_version, raw_response, latency_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (page_id, "likely_food_recipe", "qwen3:14b", "v1", None, 80, "2026-01-01T00:00:00+00:00"),
    )
    db.conn.commit()
    db.close()

    db = Database(tmp_db)
    row = db.conn.execute("SELECT label, prompt_version FROM classify_url_runs").fetchone()
    assert row["label"] == "likely_drink_recipe"
    assert row["prompt_version"] == "v3"
    db.close()


# ---------------------------------------------------------------------------
# Database API: pipeline_runs + validate-stage eval writes
# ---------------------------------------------------------------------------


def test_start_run_returns_id_and_persists_row(tmp_db):
    db = Database(tmp_db)
    run_id = db.start_run(stage="validate_html", site="imbibe", args={"limit": 10})
    row = db.conn.execute(
        "SELECT stage, site, args, started_at, finished_at, summary FROM pipeline_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert row["stage"] == "validate_html"
    assert row["site"] == "imbibe"
    # args is stored as JSON text so queries aren't tied to the Python repr.
    import json
    assert json.loads(row["args"]) == {"limit": 10}
    assert row["started_at"] is not None
    assert row["finished_at"] is None
    assert row["summary"] is None
    db.close()


def test_finish_run_stamps_finished_at_and_summary(tmp_db):
    db = Database(tmp_db)
    run_id = db.start_run(stage="validate_html")
    db.finish_run(run_id, summary={"transitions": 3})
    row = db.conn.execute(
        "SELECT finished_at, summary FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row["finished_at"] is not None
    import json
    assert json.loads(row["summary"]) == {"transitions": 3}
    db.close()


def test_record_validate_html_inserts_one_row(tmp_db):
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    run_id = db.start_run(stage="validate_html")

    db.record_validate_html(
        page_id=page_id,
        run_id=run_id,
        status="Recipe",
        reason="JSON-LD @type: Recipe",
        validator_version="v1",
        pages_status_before="fetched",
    )
    row = db.conn.execute("SELECT * FROM validate_html_runs").fetchone()
    assert row["page_id"] == page_id
    assert row["run_id"] == run_id
    assert row["status"] == "Recipe"
    assert row["reason"] == "JSON-LD @type: Recipe"
    assert row["validator_version"] == "v1"
    assert row["pages_status_before"] == "fetched"
    assert row["evaluated_at"] is not None
    db.close()


def test_record_validate_html_is_upsert_on_page_id(tmp_db):
    """Re-running the validator for the same page overwrites the prior row
    (latest-only). The before-snapshot updates to reflect what pages.status
    was RIGHT BEFORE the new evaluation — not the original value. That's by
    design: we only answer 'what flipped on the last run'."""
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    run1 = db.start_run(stage="validate_html")
    db.record_validate_html(
        page_id=page_id, run_id=run1, status="Recipe", reason=None,
        validator_version="v1", pages_status_before="fetched",
    )
    run2 = db.start_run(stage="validate_html")
    db.record_validate_html(
        page_id=page_id, run_id=run2, status="unverified", reason="lost structured data",
        validator_version="v2", pages_status_before="Recipe",
    )
    rows = db.conn.execute("SELECT * FROM validate_html_runs").fetchall()
    assert len(rows) == 1
    assert rows[0]["run_id"] == run2
    assert rows[0]["status"] == "unverified"
    assert rows[0]["validator_version"] == "v2"
    assert rows[0]["pages_status_before"] == "Recipe"
    db.close()


def test_record_classify_drink_inserts_one_row(tmp_db):
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    run_id = db.start_run(stage="classify_drink")

    db.record_classify_drink(
        page_id=page_id,
        run_id=run_id,
        label="confirmed_drink",
        score=7,
        score_detail={"rules": [["name_cocktail_family", 3], ["instructions_shake_ice", 3]]},
        scorer_version="v1",
        pages_content_type_before="confirmed_food",
    )
    row = db.conn.execute("SELECT * FROM classify_drink_runs").fetchone()
    assert row["label"] == "confirmed_drink"
    assert row["score"] == 7
    import json
    assert json.loads(row["score_detail"])["rules"][0] == ["name_cocktail_family", 3]
    assert row["pages_content_type_before"] == "confirmed_food"
    db.close()


def test_record_classify_drink_accepts_null_label_for_abstain(tmp_db):
    """Abstain is the common case (score between -2 and 2) — the row still
    gets written so we know the evaluator ran, just with label=NULL."""
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/a")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    run_id = db.start_run(stage="classify_drink")

    db.record_classify_drink(
        page_id=page_id, run_id=run_id, label=None, score=0,
        score_detail={"rules": []}, scorer_version="v1",
        pages_content_type_before="likely_drink_recipe",
    )
    row = db.conn.execute("SELECT label FROM classify_drink_runs").fetchone()
    assert row["label"] is None
    db.close()


def test_get_pending_validate_html_returns_rows_without_eval(tmp_db):
    """Work queue: pages with cached HTML that don't have a validate_html_runs
    row yet. Replaces the old `validated_at IS NULL` work queue."""
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "imbibe", "https://imbibe.com/b", "imbibe/b.html")
    _seed_fetched(db, "punch", "https://punch.com/c", "punch/c.html")
    # Seed one validate_html_runs row for /a — it should be skipped.
    page_a = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://imbibe.com/a",)).fetchone()["id"]
    run_id = db.start_run(stage="validate_html")
    db.record_validate_html(
        page_id=page_a, run_id=run_id, status="Recipe", reason=None,
        validator_version="v1", pages_status_before="Recipe",
    )

    pending = db.get_pending_validate_html()
    urls = {row["url"] for row in pending}
    assert urls == {"https://imbibe.com/b", "https://punch.com/c"}
    db.close()


def test_get_pending_validate_html_site_filter(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    pending = db.get_pending_validate_html(site="imbibe")
    assert [row["url"] for row in pending] == ["https://imbibe.com/a"]
    db.close()


def test_get_pending_validate_html_skips_rows_without_html(tmp_db):
    db = Database(tmp_db)
    db.add_url("imbibe", "https://imbibe.com/never-fetched")
    assert db.get_pending_validate_html() == []
    db.close()


def test_clear_validate_html_runs_all(tmp_db):
    """Prune all validate_html_runs rows → everything is back in the work queue."""
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    run_id = db.start_run(stage="validate_html")
    for url in ("https://imbibe.com/a", "https://punch.com/b"):
        page_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()["id"]
        db.record_validate_html(
            page_id=page_id, run_id=run_id, status="Recipe", reason=None,
            validator_version="v1", pages_status_before="Recipe",
        )

    assert db.clear_validate_html_runs() == 2
    assert db.conn.execute("SELECT COUNT(*) c FROM validate_html_runs").fetchone()["c"] == 0
    # Classify_drink_runs is a separate table, untouched.
    db.close()


def test_clear_validate_html_runs_site_scoped(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    run_id = db.start_run(stage="validate_html")
    for url in ("https://imbibe.com/a", "https://punch.com/b"):
        page_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()["id"]
        db.record_validate_html(
            page_id=page_id, run_id=run_id, status="Recipe", reason=None,
            validator_version="v1", pages_status_before="Recipe",
        )

    assert db.clear_validate_html_runs(site="imbibe") == 1
    remaining = db.conn.execute(
        "SELECT p.url FROM validate_html_runs v JOIN pages p ON p.id = v.page_id"
    ).fetchall()
    assert [r["url"] for r in remaining] == ["https://punch.com/b"]
    db.close()


def test_clear_classify_drink_runs_site_scoped(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "punch", "https://punch.com/b", "punch/b.html")
    run_id = db.start_run(stage="classify_drink")
    for url in ("https://imbibe.com/a", "https://punch.com/b"):
        page_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()["id"]
        db.record_classify_drink(
            page_id=page_id, run_id=run_id, label="confirmed_drink", score=3,
            score_detail={}, scorer_version="v1",
            pages_content_type_before="likely_drink_recipe",
        )

    assert db.clear_classify_drink_runs(site="punch") == 1
    remaining = db.conn.execute(
        "SELECT p.url FROM classify_drink_runs d JOIN pages p ON p.id = d.page_id"
    ).fetchall()
    assert [r["url"] for r in remaining] == ["https://imbibe.com/a"]
    db.close()


def test_count_pending_validate_html(tmp_db):
    db = Database(tmp_db)
    _seed_fetched(db, "imbibe", "https://imbibe.com/a", "imbibe/a.html")
    _seed_fetched(db, "imbibe", "https://imbibe.com/b", "imbibe/b.html")
    _seed_fetched(db, "punch", "https://punch.com/c", "punch/c.html")
    assert db.count_pending_validate_html() == 3
    assert db.count_pending_validate_html(site="imbibe") == 2

    # Record one and re-check.
    page_a = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://imbibe.com/a",)).fetchone()["id"]
    run_id = db.start_run(stage="validate_html")
    db.record_validate_html(
        page_id=page_a, run_id=run_id, status="Recipe", reason=None,
        validator_version="v1", pages_status_before="Recipe",
    )
    assert db.count_pending_validate_html() == 2
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
