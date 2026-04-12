import hashlib
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

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert results["Recipe"] == 1
    row = db.conn.execute("SELECT status FROM pages WHERE url = ?", ("https://example.com/recipes/margarita",)).fetchone()
    assert row["status"] == "Recipe"
    db.close()


def test_fetch_pages_marks_blocked(tmp_db, tmp_path, sample_blocked_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_blocked_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert results["blocked"] == 1
    row = db.conn.execute("SELECT status FROM pages WHERE url = ?", ("https://example.com/recipes/margarita",)).fetchone()
    assert row["status"] == "blocked"
    db.close()


def test_fetch_pages_handles_network_error(tmp_db, tmp_path):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")

    mock_client = MagicMock()
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

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, limit=3, delay=0)

    assert results["Recipe"] == 3
    pending = db.get_pending()
    assert len(pending) == 7
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
    # Add pages for a good site
    db.add_url("goodsite", "https://good.com/recipes/1")

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_blocked_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert "badsite" in results.get("paused_sites", [])
    # Good site should still have been attempted
    assert mock_client.fetch.call_count >= 1
    db.close()
