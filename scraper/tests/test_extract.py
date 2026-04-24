import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from scraper.src.db import Database

# Load .env from repo root so SUPABASE_DB_URL is available.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

requires_supabase = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="SUPABASE_DB_URL not set; skipping integration test",
)

FIXTURES = Path(__file__).parent / "fixtures" / "jsonld"


@pytest.fixture
def isolated_supabase():
    from scraper.src.supabase_client import SupabaseClient
    c = SupabaseClient()
    c.truncate_recipes()
    yield c
    c.truncate_recipes()
    c.close()


@pytest.fixture
def seeded_scraper_db(tmp_db, tmp_path):
    """A scraper.db with two drink-recipe rows pointing at real fixture HTML."""
    html_dir = tmp_path / "html"
    site_dir = html_dir / "difs"
    site_dir.mkdir(parents=True)
    (site_dir / "negroni.html").write_text((FIXTURES / "standard.html").read_text())
    (site_dir / "nojsonld.html").write_text((FIXTURES / "no_jsonld.html").read_text())

    db = Database(tmp_db)
    db.add_urls_batch("difs", ["https://example.com/negroni", "https://example.com/noop"])
    db.set_content_type("https://example.com/negroni", "likely_drink_recipe")
    db.mark_content("https://example.com/negroni", "valid", html_path="difs/negroni.html")
    db.set_content_type("https://example.com/noop", "likely_drink_recipe")
    db.mark_content("https://example.com/noop", "valid", html_path="difs/nojsonld.html")
    yield db, html_dir
    db.close()


@requires_supabase
def test_extract_writes_recipe_and_marks_rows(seeded_scraper_db, isolated_supabase):
    from scraper.src.extract import extract_pages
    db, html_dir = seeded_scraper_db
    changes = extract_pages(db=db, sb=isolated_supabase, html_dir=html_dir)

    assert changes["difs"]["extracted"] == 1
    assert changes["difs"]["no_recipe"] == 1
    assert changes["difs"].get("missing", 0) == 0
    assert isolated_supabase.count_recipes() == 1

    # Re-running is a no-op: both rows are either extracted or errored, so
    # the work queue is empty and changes comes back as {}.
    second = extract_pages(db=db, sb=isolated_supabase, html_dir=html_dir)
    assert second == {}
    assert isolated_supabase.count_recipes() == 1


@requires_supabase
def test_extract_upsert_is_idempotent(seeded_scraper_db, isolated_supabase):
    from scraper.src.extract import extract_pages
    db, html_dir = seeded_scraper_db
    extract_pages(db=db, sb=isolated_supabase, html_dir=html_dir)

    # Force re-extraction of the one successful row.
    import sqlite3
    conn = sqlite3.connect(db.conn.execute("PRAGMA database_list").fetchone()[2])
    conn.execute("UPDATE pages SET extracted_at = NULL WHERE url = ?", ("https://example.com/negroni",))
    conn.commit()
    conn.close()

    changes = extract_pages(db=db, sb=isolated_supabase, html_dir=html_dir)
    assert changes["difs"]["extracted"] == 1
    assert isolated_supabase.count_recipes() == 1  # still one, UPSERT on source_url
