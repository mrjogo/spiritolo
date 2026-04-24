import hashlib
import threading
from unittest.mock import MagicMock

from scraper.src.db import Database
from scraper.src.fetch import (
    url_to_filename,
    save_html,
    check_circuit_breaker,
    fetch_pages,
)


def test_url_to_filename():
    url = "https://example.com/recipes/margarita"
    filename = url_to_filename(url)
    expected = hashlib.sha256(url.encode()).hexdigest()[:16] + ".html"
    assert filename == expected


def test_save_html(tmp_path):
    html = "<html><body>Hello</body></html>"
    rel_path = save_html(tmp_path, "testsite", "abc123def456.html", html)
    assert rel_path == "testsite/abc123def456.html"
    full_path = tmp_path / "testsite" / "abc123def456.html"
    assert full_path.exists()
    assert full_path.read_text() == html


def test_circuit_breaker_not_triggered():
    statuses = ["fetched"] * 15 + ["blocked"] * 5
    assert check_circuit_breaker(statuses) is False


def test_circuit_breaker_triggered():
    statuses = ["blocked"] * 9 + ["fetched"] * 11
    assert check_circuit_breaker(statuses) is True


def test_circuit_breaker_ignores_non_recipe_content():
    statuses = ["Article"] * 5 + ["blocked"] * 4 + ["fetched"] * 11
    assert check_circuit_breaker(statuses) is False


def test_circuit_breaker_not_enough_data():
    statuses = ["blocked"] * 3
    assert check_circuit_breaker(statuses) is False


def test_fetch_pages_marks_recipe(tmp_db, tmp_path, sample_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert results["Recipe"] == 1
    row = db.conn.execute("SELECT status FROM pages WHERE url = ?", ("https://example.com/recipes/margarita",)).fetchone()
    assert row["status"] == "Recipe"
    db.close()


def test_fetch_pages_stamps_validated_at(tmp_db, tmp_path, sample_recipe_html):
    """Successful fetch runs validate+classify_drink synchronously, so it
    should also stamp validated_at — otherwise every freshly-fetched row
    would show up in the validate CLI's work queue for no reason."""
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_recipe_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT validated_at FROM pages WHERE url = ?",
        ("https://example.com/recipes/margarita",),
    ).fetchone()
    assert row["validated_at"] is not None
    db.close()


def test_fetch_pages_stamps_validated_at_on_blocked(tmp_db, tmp_path, sample_blocked_html):
    """Blocked pages never reach classify_drink, but validate still ran on
    the HTML and produced a verdict. Stamping validated_at keeps the
    work-queue invariant simple: every row we've seen through validate is
    stamped, regardless of outcome."""
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/blocked")
    db.set_content_type("https://example.com/recipes/blocked", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_blocked_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT validated_at FROM pages WHERE url = ?",
        ("https://example.com/recipes/blocked",),
    ).fetchone()
    assert row["validated_at"] is not None
    db.close()


def test_fetch_pages_marks_blocked(tmp_db, tmp_path, sample_blocked_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_blocked_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert results["blocked"] == 1
    row = db.conn.execute("SELECT status FROM pages WHERE url = ?", ("https://example.com/recipes/margarita",)).fetchone()
    assert row["status"] == "blocked"
    db.close()


def test_fetch_pages_handles_network_error(tmp_db, tmp_path):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.side_effect = Exception("Connection timeout")

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert results["errors"] == 1
    row = db.conn.execute("SELECT attempts FROM pages WHERE url = ?", ("https://example.com/recipes/margarita",)).fetchone()
    assert row["attempts"] == 1
    db.close()


def test_fetch_pages_respects_limit(tmp_db, tmp_path, sample_recipe_html):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/recipes/{i}")
    for i in range(10):
        db.set_content_type(f"https://example.com/recipes/{i}", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, limit=3, delay=0)

    assert results["Recipe"] == 3
    pending = db.get_pending()
    assert len(pending) == 7
    db.close()


def test_fetch_pages_only_fetches_likely_drink_recipe(tmp_db, tmp_path, sample_drink_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.add_url("testsite", "https://example.com/recipes/salmon")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
    db.set_content_type("https://example.com/recipes/salmon", "likely_food_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_drink_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert mock_client.fetch.call_count == 1
    mock_client.fetch.assert_called_once_with("https://example.com/recipes/margarita")
    db.close()


def test_fetch_pages_circuit_breaker_pauses_site(tmp_db, tmp_path, sample_blocked_html):
    db = Database(tmp_db)
    # Pre-populate with enough blocked pages to trigger circuit breaker
    for i in range(15):
        db.add_url("badsite", f"https://bad.com/recipes/{i}")
        db.mark_blocked(f"https://bad.com/recipes/{i}", "blocked")
    # Add more pending pages for this site
    for i in range(15, 20):
        db.add_url("badsite", f"https://bad.com/recipes/{i}")
    for i in range(15, 20):
        db.set_content_type(f"https://bad.com/recipes/{i}", "likely_drink_recipe")
    # Add pages for a good site
    db.add_url("goodsite", "https://good.com/recipes/1")
    db.set_content_type("https://good.com/recipes/1", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_blocked_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert "badsite" in results.get("paused_sites", [])
    # Good site should still have been attempted
    assert mock_client.fetch.call_count >= 1
    db.close()


def test_fetch_pages_confirms_drink(tmp_db, tmp_path, sample_drink_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_drink_recipe_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/margarita",),
    ).fetchone()
    assert row["content_type"] == "confirmed_drink"
    db.close()


def test_fetch_pages_confirms_food(tmp_db, tmp_path, sample_food_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/salmon")
    db.set_content_type("https://example.com/recipes/salmon", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = sample_food_recipe_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/salmon",),
    ).fetchone()
    assert row["content_type"] == "confirmed_food"
    db.close()


def test_fetch_pages_leaves_likely_drink_when_no_recipe_jsonld(tmp_db, tmp_path):
    """When the page has no Recipe JSON-LD, content_type stays likely_drink_recipe."""
    body = "<p>content</p>\n" * 200
    html_no_recipe = """<!DOCTYPE html>
<html><head><title>Some Page</title></head><body>
""" + body + """<script type="application/ld+json">
{"@type": "Article", "name": "About Cocktails"}
</script></body></html>"""

    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/article")
    db.set_content_type("https://example.com/recipes/article", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "concurrencyLimit": 1, "concurrentRequests": 0,
        "requestCount": 0, "requestLimit": 5000,
        "burst": 0, "failedRequestCount": 0,
    }
    mock_client.fetch.return_value = html_no_recipe

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/article",),
    ).fetchone()
    assert row["content_type"] == "likely_drink_recipe"
    db.close()


def test_fetch_pages_preflight_prints_budget(tmp_db, tmp_path, make_mock_client, capsys):
    db = Database(tmp_db)
    mock_client = make_mock_client(concurrency=5, request_count=2613, request_limit=5000)
    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)
    captured = capsys.readouterr()
    assert "2387/5000 credits remaining" in captured.out
    assert "concurrency=5" in captured.out
    mock_client.get_account.assert_called_once()
    db.close()


def test_fetch_pages_aborts_on_preflight_auth_error(tmp_db, tmp_path, capsys):
    from unittest.mock import MagicMock
    from scraper.src.client import AuthError
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.side_effect = AuthError("Invalid API key")

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    # fetch() should never have been called
    mock_client.fetch.assert_not_called()
    # Page should still be pending
    row = db.conn.execute(
        "SELECT status FROM pages WHERE url = ?",
        ("https://example.com/recipes/margarita",),
    ).fetchone()
    assert row["status"] == "pending"
    captured = capsys.readouterr()
    assert "ABORTED" in captured.out or "AuthError" in captured.out
    assert results == {"blocked": 0, "errors": 0, "paused_sites": []}
    db.close()


def test_fetch_pages_aborts_on_preflight_scraperapi_error(tmp_db, tmp_path, capsys):
    from unittest.mock import MagicMock
    from scraper.src.client import ScraperAPIError
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.side_effect = ScraperAPIError("/account returned 500")

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    mock_client.fetch.assert_not_called()
    captured = capsys.readouterr()
    assert "ABORTED" in captured.out or "500" in captured.out
    assert results == {"blocked": 0, "errors": 0, "paused_sites": []}
    db.close()


def test_fetch_pages_parallel_happy_path(tmp_db, tmp_path, make_mock_client, sample_recipe_html):
    """All 5 URLs get fetched and marked when running with 3 workers."""
    db = Database(tmp_db)
    urls = [f"https://example.com/recipes/{i}" for i in range(5)]
    for url in urls:
        db.add_url("testsite", url)
        db.set_content_type(url, "likely_drink_recipe")

    mock_client = make_mock_client(concurrency=3)
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert mock_client.fetch.call_count == 5
    assert results.get("Recipe", 0) == 5
    for url in urls:
        row = db.conn.execute(
            "SELECT status FROM pages WHERE url = ?", (url,)
        ).fetchone()
        assert row["status"] == "Recipe"
    # No URL should still be pending
    assert db.get_pending() == []
    db.close()


def test_fetch_pages_aborts_on_quota_mid_run(tmp_db, tmp_path, make_mock_client, sample_recipe_html, capsys):
    """After a QuotaExhaustedError, remaining URLs must stay pending (not marked failed)."""
    from scraper.src.client import QuotaExhaustedError
    db = Database(tmp_db)
    urls = [f"https://example.com/recipes/{i}" for i in range(10)]
    for url in urls:
        db.add_url("testsite", url)
        db.set_content_type(url, "likely_drink_recipe")

    # First call succeeds, subsequent calls raise QuotaExhaustedError
    call_count = {"n": 0}
    lock = threading.Lock()
    def fake_fetch(url):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            return sample_recipe_html
        raise QuotaExhaustedError("Credits exhausted: demo")

    mock_client = make_mock_client(concurrency=1)  # sequential to keep ordering deterministic
    mock_client.fetch.side_effect = fake_fetch

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    captured = capsys.readouterr()
    assert "ABORTED" in captured.out
    assert "QuotaExhaustedError" in captured.out

    # At least one URL should have been marked Recipe (the first one).
    recipe_rows = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pages WHERE status = 'Recipe'"
    ).fetchone()
    assert recipe_rows["c"] >= 1

    # At least one URL should remain pending (not marked failed).
    pending = db.get_pending()
    assert len(pending) >= 1
    # No URL should be marked failed due to the quota error.
    failed_rows = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pages WHERE status = 'failed'"
    ).fetchone()
    assert failed_rows["c"] == 0
    db.close()
