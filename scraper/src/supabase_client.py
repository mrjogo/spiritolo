import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def _env_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        # Lazy-load .env at the repo root; the extractor normally does this itself, but
        # allow direct use of this module for smoke checks.
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not set. Run `supabase status` and add it to .env.")
    return url


class SupabaseClient:
    """Thin psycopg wrapper. One connection, UPSERT by source_url."""

    def __init__(self, db_url: str | None = None):
        self.conn = psycopg.connect(db_url or _env_url())

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

    def truncate_recipes(self):
        """Test-only helper."""
        self.conn.execute("truncate table recipes")
        self.conn.commit()
