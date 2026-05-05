import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv


def _env_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        # Lazy-load .env at the repo root; the extractor normally does this itself, but
        # allow direct use of this module for smoke checks.
        load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
        url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not set. Run `supabase status` and add it to .env.")
    return url


def looks_like_supabase_pooler(db_url: str) -> bool:
    """True if the URL's host is a Supabase Supavisor pooler.

    Both session-mode (`aws-0-<region>.pooler.supabase.com:5432`) and
    transaction-mode (port 6543) live on the same hostname suffix."""
    try:
        host = urlparse(db_url).hostname or ""
    except ValueError:
        return False
    return host.endswith(".pooler.supabase.com")


def warn_if_staging_url(db_url: str, *, logger: logging.Logger | None = None) -> None:
    """Log a warning if `db_url` looks like the Supabase pooler.

    Pipelines are expected to run against a local restore of staging and
    push the diff back through `scripts/upload-to-staging` (see
    docs/upload.md). A pooler hostname almost always means the operator
    forgot to switch SUPABASE_DB_URL back to local — bulk writes would
    bypass every uploader protection. Warning, not refusal: occasional
    direct-to-staging runs are still legitimate."""
    if looks_like_supabase_pooler(db_url):
        (logger or logging.getLogger("spiritolo_common")).warning(
            "SUPABASE_DB_URL points at a Supabase pooler — about to write directly to "
            "staging, bypassing the upload-to-staging protections. If this is a bulk "
            "pipeline run, switch to local and follow docs/upload.md."
        )


class SupabaseClient:
    """Thin psycopg wrapper. One connection, UPSERT by source_url."""

    def __init__(self, db_url: str | None = None):
        url = db_url or _env_url()
        warn_if_staging_url(url)
        self.conn = psycopg.connect(url)

    def close(self):
        self.conn.close()

    def upsert_recipe(
        self,
        *,
        source_url: str,
        site: str,
        name: str | None,
        author: str | None,
        image_url: str | None,
        jsonld: dict,
        fetched_at: str,
    ):
        """Insert or update a recipe keyed by source_url. `fetched_at` is ISO-8601 UTC."""
        self.conn.execute(
            """
            INSERT INTO recipes (source_url, site, name, author, image_url, jsonld, fetched_at, extracted_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::timestamptz, now())
            ON CONFLICT (source_url) DO UPDATE SET
                site = EXCLUDED.site,
                name = EXCLUDED.name,
                author = EXCLUDED.author,
                image_url = EXCLUDED.image_url,
                jsonld = EXCLUDED.jsonld,
                fetched_at = EXCLUDED.fetched_at,
                extracted_at = now()
            """,
            (source_url, site, name, author, image_url, json.dumps(jsonld), fetched_at),
        )
        self.conn.commit()

    def count_recipes(self) -> int:
        return self.conn.execute("select count(*) from recipes").fetchone()[0]

    def get_extracted_source_urls(self, site: str | None = None) -> set[str]:
        """Return every source_url currently present in `recipes`, optionally
        scoped to a site. This is the canonical 'has been extracted' signal —
        the extract CLI uses it to decide what to skip. Supabase can be wiped
        independently of scraper.db (e.g. local `supabase db reset`), so
        trusting the local extract_runs table alone would cause the wipe
        scenario to silently skip re-uploads."""
        if site is None:
            rows = self.conn.execute("SELECT source_url FROM recipes").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT source_url FROM recipes WHERE site = %s", (site,),
            ).fetchall()
        return {r[0] for r in rows}

    def truncate_recipes(self):
        """Test-only helper. CASCADE drops recipe_ingredients rows that FK
        back to the truncated recipes."""
        self.conn.execute("truncate table recipes cascade")
        self.conn.commit()
