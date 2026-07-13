"""extract stage — cached HTML (JSON-LD) -> a `recipes` row.

For each queued page (classified as a recipe, with a corpus key) it reads the
cached HTML from the R2 corpus, finds the Schema.org Recipe JSON-LD, and UPSERTs
a `recipes` row (raw `source` jsonb verbatim + derived title/author/image;
equipment stays empty until the convert stage). A page with no Recipe JSON-LD
falls through to the LLM tier (provider chain) which synthesizes the recipe
source from the page; with no provider it abstains. One `stage_runs` row per
page records the outcome at `EXTRACTOR_VERSION` (the page is the entity here —
extract consumes pages and produces recipes).

The corpus reader is injected via `set_corpus_reader` (tests pass a fake); at
runtime it defaults to the env-configured R2 reader.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from common.providers.packing import Item
from ingredients.pipeline import corpus, ledger
from ingredients.pipeline.stages import base

from . import jsonld

STAGE = "extract"
EXTRACTOR_VERSION = "v1"

# Page classification labels the extract queue accepts.
RECIPE_CONTENT_TYPES = ("drink_recipe",)

_corpus_reader: corpus.CorpusReader | None = None


def set_corpus_reader(reader: corpus.CorpusReader | None) -> None:
    """Inject the corpus reader the stage reads HTML through (tests use a fake)."""
    global _corpus_reader
    _corpus_reader = reader


def _reader() -> corpus.CorpusReader:
    return _corpus_reader if _corpus_reader is not None else corpus.default_reader()


def _page_queue(
    conn: psycopg.Connection, site: str | None, limit: int | None
) -> list[dict[str, Any]]:
    """Pages classified as recipes with a corpus key and no extract run at
    EXTRACTOR_VERSION."""
    clauses = [
        "p.content_type = any(%s)",
        "p.r2_key is not null",
        """not exists (
            select 1 from stage_runs r
            where r.entity_type = 'page' and r.entity_id = p.id
              and r.stage = 'extract' and r.version = %s
        )""",
    ]
    params: list[Any] = [list(RECIPE_CONTENT_TYPES), EXTRACTOR_VERSION]
    if site is not None:
        clauses.append("p.site = %s")
        params.append(site)
    sql = "select p.id, p.url, p.site, p.r2_key from pages p where " + " and ".join(clauses)
    sql += " order by p.id"
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [
        {"id": r[0], "url": r[1], "site": r[2], "r2_key": r[3]}
        for r in conn.execute(sql, params).fetchall()
    ]


def _upsert_recipe(conn: psycopg.Connection, page: dict[str, Any], recipe: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into recipes (source_url, site, source, title, author, image_url)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (source_url) do update set
            site      = excluded.site,
            source    = excluded.source,
            title     = excluded.title,
            author    = excluded.author,
            image_url = excluded.image_url
        """,
        (
            page["url"], page["site"], Json(recipe),
            jsonld.derive_name(recipe), jsonld.derive_author(recipe),
            jsonld.derive_image_url(recipe),
        ),
    )


def _record(conn, page_id, *, outcome, method, job, error_code=None):
    ledger.record_run(
        conn,
        entity_type="page",
        entity_id=page_id,
        stage=STAGE,
        version=EXTRACTOR_VERSION,
        outcome=outcome,
        method=method,
        job_id=job.get("id"),
        error_code=error_code,
    )


def extract_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Extract a `recipes` row from each queued page's cached HTML."""
    site, limit = base.scope(job)
    pages = _page_queue(conn, site, limit)
    counts = {"extracted": 0, "no_recipe": 0, "html_missing": 0}
    reader = _reader() if pages else None

    for page in pages:
        try:
            html = reader.read_html(page["r2_key"])
        except corpus.CorpusMiss:
            counts["html_missing"] += 1
            _record(conn, page["id"], outcome="failed", method="deterministic",
                    job=job, error_code="html_missing")
            continue

        recipe = jsonld.find_recipe_jsonld(html)
        method = "deterministic"
        if recipe is None and providers is not None:
            recipe = _llm_synthesize(providers, page, html)
            method = "llm"

        if recipe is None:
            counts["no_recipe"] += 1
            _record(conn, page["id"], outcome="abstain", method="deterministic", job=job)
            continue

        _upsert_recipe(conn, page, recipe)
        counts["extracted"] += 1
        _record(conn, page["id"], outcome="resolved", method=method, job=job)
    return counts


def _llm_synthesize(providers: Any, page: dict[str, Any], html: str) -> dict[str, Any] | None:
    """Route a page with no Recipe JSON-LD through the provider chain; the tier
    returns a recipe-source dict or abstains."""
    result = providers.resolve([Item(id=str(page["id"]), payload=html)])
    return result.resolved.get(str(page["id"]))
