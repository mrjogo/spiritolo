import os
from pathlib import Path
from unittest.mock import MagicMock

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
    from spiritolo_common.supabase_client import SupabaseClient
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

    # Force re-extraction of the one successful row by deleting its
    # extract_runs row — the CLI's work queue picks it back up.
    db.clear_extract_runs()

    changes = extract_pages(db=db, sb=isolated_supabase, html_dir=html_dir)
    # Re-run picks up BOTH the successful row (Supabase already has it but
    # we've deleted the local extract_runs row, and the supabase check
    # excludes it) and... wait — the successful row IS in Supabase, so it
    # should be skipped. Only the no_recipe row re-runs.
    assert changes.get("difs", {}).get("extracted", 0) == 0
    assert changes["difs"]["no_recipe"] == 1
    assert isolated_supabase.count_recipes() == 1


# ---------------------------------------------------------------------------
# Supabase-as-source-of-truth behavior (unit-level, no real Supabase needed)
# ---------------------------------------------------------------------------


def _mock_sb(*, extracted_urls: set[str]):
    """Build a Supabase-client double that reports the given URLs as extracted
    and silently absorbs upserts (recording them so tests can assert)."""
    sb = MagicMock()
    sb.get_extracted_source_urls.return_value = set(extracted_urls)
    sb.upsert_recipe = MagicMock()
    return sb


def test_extract_skips_rows_already_in_supabase(tmp_db, tmp_path):
    """A page with an extract_runs row marked 'extracted' that is ALSO
    present in Supabase must not be re-uploaded. Supabase membership is the
    skip gate, not the local audit row."""
    from scraper.src.extract import extract_pages

    (tmp_path / "difs").mkdir(parents=True)
    (tmp_path / "difs" / "x.html").write_text((FIXTURES / "standard.html").read_text())

    db = Database(tmp_db)
    db.add_url("difs", "https://example.com/already")
    db.set_content_type("https://example.com/already", "likely_drink_recipe")
    db.mark_content("https://example.com/already", "valid", html_path="difs/x.html")
    # Local audit says we extracted this before.
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    db.record_extract(
        page_id=page_id, run_id=None, outcome="extracted",
        error=None, extractor_version="legacy",
    )

    sb = _mock_sb(extracted_urls={"https://example.com/already"})
    changes = extract_pages(db=db, sb=sb, html_dir=tmp_path)

    assert changes == {}
    sb.upsert_recipe.assert_not_called()
    db.close()


def test_extract_reuploads_when_supabase_has_been_wiped(tmp_db, tmp_path):
    """Canonical wipe scenario: local extract_runs still says 'extracted'
    but Supabase's recipes table has been reset. The page must be
    re-extracted and re-uploaded; Supabase is the source of truth, not
    extract_runs."""
    from scraper.src.extract import extract_pages

    (tmp_path / "difs").mkdir(parents=True)
    (tmp_path / "difs" / "x.html").write_text((FIXTURES / "standard.html").read_text())

    db = Database(tmp_db)
    db.add_url("difs", "https://example.com/wiped")
    db.set_content_type("https://example.com/wiped", "likely_drink_recipe")
    db.mark_content("https://example.com/wiped", "valid", html_path="difs/x.html")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    db.record_extract(
        page_id=page_id, run_id=None, outcome="extracted",
        error=None, extractor_version="legacy",
    )

    sb = _mock_sb(extracted_urls=set())  # Supabase is empty after wipe
    changes = extract_pages(db=db, sb=sb, html_dir=tmp_path)

    assert changes["difs"]["extracted"] == 1
    sb.upsert_recipe.assert_called_once()
    # Local audit row is updated to the new run.
    row = db.conn.execute("SELECT extractor_version FROM extract_runs").fetchone()
    assert row["extractor_version"] != "legacy"
    db.close()


def test_extract_skips_known_failures_even_when_not_in_supabase(tmp_db, tmp_path):
    """A page marked 'no_recipe' locally stays skipped across runs — the
    HTML hasn't changed, so the outcome won't change either. To retry it
    (e.g. after bumping EXTRACTOR_VERSION), delete the extract_runs row."""
    from scraper.src.extract import extract_pages

    (tmp_path / "difs").mkdir(parents=True)
    (tmp_path / "difs" / "x.html").write_text((FIXTURES / "no_jsonld.html").read_text())

    db = Database(tmp_db)
    db.add_url("difs", "https://example.com/norecipe")
    db.set_content_type("https://example.com/norecipe", "likely_drink_recipe")
    db.mark_content("https://example.com/norecipe", "valid", html_path="difs/x.html")
    page_id = db.conn.execute("SELECT id FROM pages").fetchone()["id"]
    db.record_extract(
        page_id=page_id, run_id=None, outcome="no_recipe",
        error=None, extractor_version="v1",
    )

    sb = _mock_sb(extracted_urls=set())
    changes = extract_pages(db=db, sb=sb, html_dir=tmp_path)

    assert changes == {}
    sb.upsert_recipe.assert_not_called()
    db.close()


def test_extract_processes_fresh_page(tmp_db, tmp_path):
    """A page with no extract_runs row and not in Supabase is the baseline
    'new work' case."""
    from scraper.src.extract import extract_pages

    (tmp_path / "difs").mkdir(parents=True)
    (tmp_path / "difs" / "x.html").write_text((FIXTURES / "standard.html").read_text())

    db = Database(tmp_db)
    db.add_url("difs", "https://example.com/fresh")
    db.set_content_type("https://example.com/fresh", "likely_drink_recipe")
    db.mark_content("https://example.com/fresh", "valid", html_path="difs/x.html")

    sb = _mock_sb(extracted_urls=set())
    changes = extract_pages(db=db, sb=sb, html_dir=tmp_path)

    assert changes["difs"]["extracted"] == 1
    sb.upsert_recipe.assert_called_once()
    row = db.conn.execute("SELECT outcome FROM extract_runs").fetchone()
    assert row["outcome"] == "extracted"
    db.close()
