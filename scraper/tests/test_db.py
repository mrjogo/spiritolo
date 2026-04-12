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
    db.mark_fetched("https://example.com/recipe/1", "html/testsite/abc123.html")
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


def test_mark_fetched(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_fetched("https://example.com/recipe/1", "html/testsite/abc123.html")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["status"] == "fetched"
    assert row["html_path"] == "html/testsite/abc123.html"
    assert row["fetched_at"] is not None
    db.close()


def test_mark_blocked(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_blocked("https://example.com/recipe/1", "cf-challenge detected")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["status"] == "blocked"
    assert row["error"] == "cf-challenge detected"
    db.close()


def test_mark_unverified(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.mark_unverified("https://example.com/recipe/1", "no JSON-LD, content looks plausible")
    row = db.conn.execute("SELECT * FROM pages WHERE url = ?", ("https://example.com/recipe/1",)).fetchone()
    assert row["status"] == "unverified"
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
        db.mark_fetched(f"https://example.com/recipe/{i}", f"html/testsite/{i}.html")
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
    db.mark_fetched("https://a.com/1", "html/site_a/1.html")
    db.add_url("site_b", "https://b.com/1")
    stats = db.get_stats()
    assert stats == {"site_a": {"pending": 1, "fetched": 1}, "site_b": {"pending": 1}}
    db.close()
