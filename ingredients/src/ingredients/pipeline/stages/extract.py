"""extract stage — cached HTML (JSON-LD) -> a `recipes` row.

For each queued page (classified as a recipe, with a corpus key) it reads the
cached HTML from the object store, finds the Schema.org Recipe JSON-LD, and
UPSERTs a `recipes` row (raw `source` jsonb verbatim + derived
title/author/image; equipment stays empty until the convert stage). A page
with no Recipe JSON-LD falls through to the LLM tier (provider chain): the page
is reduced to bounded readable text (``page_text``) and the tier answers with
the recipe it finds there (``EXTRACT_PROMPT``), which becomes a Schema.org
Recipe source; ``found: false``, no answer, or no provider abstains. One
`job_items` row per page records the outcome at `EXTRACTOR_VERSION` (the page
is the entity here — extract consumes pages and produces recipes).

The corpus reader is injected via `set_corpus_reader` (tests pass a fake); at
runtime it defaults to the env-configured object-store reader.
"""

from __future__ import annotations

import functools
import itertools
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from typing import Any

from common.db import Connection, jdump, jlist
from common.providers.packing import Item
from ingredients.pipeline import corpus, ledger
from ingredients.pipeline.stages import base

from . import jsonld

STAGE = "extract-recipe"
# v2: the LLM tier gets a real synthesis prompt over bounded page text.
EXTRACTOR_VERSION = "v2"

# Readable page text sent to the LLM tier is cut at this many characters
# (~3K tokens), which holds a recipe block on every site we crawl.
PAGE_TEXT_LIMIT = 12_000

EXTRACT_PROMPT = """\
You extract a cocktail recipe from the readable text of a web page.

Each item's `input` is {"url": "<page url>", "text": "<the page's visible text>"}.
Each item's `answer` is ONE of these two JSON objects:

1. FOUND — the page presents exactly one drink recipe:
   {"found": true,
    "name": "<the drink's name>",
    "recipeIngredient": ["<one ingredient line, with its amount>", ...],
    "recipeInstructions": ["<one step>", ...],
    "description": "<a one-sentence description from the page>" or null,
    "recipeYield": "<the yield as the page states it>" or null}

2. NOT FOUND — the page is not a single drink recipe (an article, a list of
   many drinks, a product page, or the recipe is missing from the text):
   {"found": false, "name": null, "recipeIngredient": [],
    "recipeInstructions": [], "description": null, "recipeYield": null}

Rules:
- Copy ingredient lines and steps as they appear in the text; keep amounts and
  units exactly. Never invent an ingredient, amount, or step.
- One ingredient per recipeIngredient entry, in the page's order.
- recipeIngredient must be non-empty when found is true; otherwise answer not found.
- Prefer not found over guessing.
"""

EXTRACT_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "name": {"type": ["string", "null"]},
        "recipeIngredient": {"type": "array", "items": {"type": "string"}},
        "recipeInstructions": {"type": "array", "items": {"type": "string"}},
        "description": {"type": ["string", "null"]},
        "recipeYield": {"type": ["string", "null"]},
    },
    "required": [
        "found", "name", "recipeIngredient", "recipeInstructions",
        "description", "recipeYield",
    ],
    "additionalProperties": False,
}

# Elements whose content is never part of the readable page.
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "iframe", "nav", "footer", "head"}
)
# Elements that start a new line of text.
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
     "header", "main", "aside", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
     "figcaption", "dd", "dt", "pre"}
)
_WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def page_text(html: str, limit: int = PAGE_TEXT_LIMIT) -> str:
    """The page's visible text: scripts, styles, navigation and footers
    dropped, whitespace collapsed to one space per run and one line per block,
    a line repeating the one before it dropped (Punch renders each ingredient
    twice, and the model copied both), cut at ``limit`` characters. Stdlib only
    (no new HTML dependency)."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    lines = (_WS_RE.sub(" ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line, _ in itertools.groupby(filter(None, lines)))[:limit]

# Page classification labels the extract queue accepts — the Zone-1 classifier's
# recipe verdicts. Duplicated here rather than imported: ingredients doesn't
# depend on scraper.
RECIPE_CONTENT_TYPES = ("likely_drink_recipe", "confirmed_drink")

# Corpus GETs are the extract bottleneck (one network round-trip per page), so
# they run across a thread pool, `_READ_WINDOW` pages at a time — the window
# bounds how much HTML is buffered at once. Only the reads are threaded; parsing,
# the LLM tier, and every DB write run on the calling thread, so `conn` and
# `providers` are never shared across threads.
_READ_WORKERS = 24
_READ_WINDOW = 256

_corpus_reader: corpus.CorpusReader | None = None


def set_corpus_reader(reader: corpus.CorpusReader | None) -> None:
    """Inject the corpus reader the stage reads HTML through (tests use a fake)."""
    global _corpus_reader
    _corpus_reader = reader


def _reader() -> corpus.CorpusReader:
    return _corpus_reader if _corpus_reader is not None else corpus.default_reader()


def _page_queue(
    conn: Connection, site: str | None, limit: int | None
) -> list[dict[str, Any]]:
    """Pages classified as recipes with a corpus key and no extract run at
    EXTRACTOR_VERSION."""
    clauses = [
        "p.content_type in (select value from json_each(?))",
        "p.corpus_key is not null",
        """not exists (
            select 1 from job_items r
            where r.entity_type = 'page' and r.entity_id = p.id
              and r.stage = ? and r.code_version = ?
        )""",
    ]
    params: list[Any] = [jlist(RECIPE_CONTENT_TYPES), STAGE, EXTRACTOR_VERSION]
    if site is not None:
        clauses.append("p.site = ?")
        params.append(site)
    sql = "select p.id, p.url, p.site, p.corpus_key from pages p where " + " and ".join(clauses)
    sql += " order by p.id"
    if limit is not None:
        sql += " limit ?"
        params.append(limit)
    return [
        {"id": r[0], "url": r[1], "site": r[2], "corpus_key": r[3]}
        for r in conn.execute(sql, params).fetchall()
    ]


def _upsert_recipe(conn: Connection, page: dict[str, Any], recipe: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into recipes (source_url, site, source, title, author, image_url)
        values (?, ?, ?, ?, ?, ?)
        on conflict (source_url) do update set
            site       = excluded.site,
            source     = excluded.source,
            title      = excluded.title,
            author     = excluded.author,
            image_url  = excluded.image_url,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            page["url"], page["site"], jdump(recipe),
            jsonld.derive_name(recipe), jsonld.derive_author(recipe),
            jsonld.derive_image_url(recipe),
        ),
    )


def _pages_by_ids(conn: Connection, page_ids: list[int]) -> list[dict[str, Any]]:
    """Load the explicit page members of a run (same row shape as _page_queue)."""
    if not page_ids:
        return []
    rows = conn.execute(
        "select p.id, p.url, p.site, p.corpus_key from pages p "
        "where p.id in (select value from json_each(?)) order by p.id",
        (jlist(page_ids),),
    ).fetchall()
    return [
        {"id": r[0], "url": r[1], "site": r[2], "corpus_key": r[3]} for r in rows
    ]


def _record(conn, page_id, *, outcome, method, job, error_code=None):
    ledger.record_run(
        conn,
        entity_type="page",
        entity_id=page_id,
        stage=STAGE,
        version=EXTRACTOR_VERSION,
        outcome=outcome,
        method=method,
        state=base.item_state(outcome),
        job_id=job.get("id"),
        error_code=error_code,
    )


def _read_html(
    reader: corpus.CorpusReader, page: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Fetch one page's HTML in a worker thread: (page, html), or (page, None)
    on CorpusMiss. Only the thread-safe reader is touched here — never `conn`.
    Any other read error propagates and fails the stage, as before."""
    try:
        return page, reader.read_html(page["corpus_key"])
    except corpus.CorpusMiss:
        return page, None


def _windows(seq: list[Any], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def extract_stage_fn(
    job: dict[str, Any],
    conn: Connection,
    providers: Any,
    *,
    workers: int = _READ_WORKERS,
    window: int = _READ_WINDOW,
) -> dict[str, Any]:
    """Extract a `recipes` row from each queued page's cached HTML.

    Corpus GETs — the bottleneck — run across a `workers`-wide thread pool, a
    `window` of pages at a time so buffered HTML stays bounded. Parsing, the LLM
    tier, and every DB write run on the calling thread in queue order.
    """
    site, limit = base.scope(job)
    if job.get("id"):
        pages = _pages_by_ids(conn, base.run_item_ids(conn, job_id=job["id"], stage=STAGE))
    else:
        pages = _page_queue(conn, site, limit)
    counts = {"extracted": 0, "no_recipe": 0, "html_missing": 0}
    if not pages:
        return counts

    should_stop = job.get("should_stop")
    fetch = functools.partial(_read_html, _reader())
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in _windows(pages, window):
            if should_stop is not None and should_stop():
                break  # cancel requested: leave the rest pending for a re-run
            for page, html in pool.map(fetch, chunk):
                if should_stop is not None and should_stop():
                    break
                if html is None:
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
                    _record(conn, page["id"], outcome="abstain", method=method, job=job)
                    continue

                _upsert_recipe(conn, page, recipe)
                counts["extracted"] += 1
                _record(conn, page["id"], outcome="resolved", method=method, job=job)

    return counts


def _llm_synthesize(providers: Any, page: dict[str, Any], html: str) -> dict[str, Any] | None:
    """Route a page with no Recipe JSON-LD through the provider chain (one page
    per call) and turn a ``found`` answer into a Schema.org Recipe source dict;
    anything else abstains (None)."""
    text = page_text(html)
    if not text:
        return None
    result = providers.resolve(
        [Item(id=str(page["id"]), payload={"url": page["url"], "text": text})],
        system_prompt=EXTRACT_PROMPT,
        answer_schema=EXTRACT_ANSWER_SCHEMA,
    )
    return _recipe_from_answer(result.resolved.get(str(page["id"])))


def _recipe_from_answer(answer: Any) -> dict[str, Any] | None:
    """A Schema.org Recipe JSON-LD dict from the tier's answer, or None."""
    if not isinstance(answer, dict) or answer.get("found") is not True:
        return None
    ingredients = [
        s.strip() for s in answer.get("recipeIngredient") or []
        if isinstance(s, str) and s.strip()
    ]
    name = answer.get("name")
    if not ingredients or not isinstance(name, str) or not name.strip():
        return None
    recipe: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": name.strip(),
        "recipeIngredient": ingredients,
        "recipeInstructions": [
            {"@type": "HowToStep", "text": s.strip()}
            for s in answer.get("recipeInstructions") or []
            if isinstance(s, str) and s.strip()
        ],
    }
    for key in ("description", "recipeYield"):
        value = answer.get(key)
        if isinstance(value, str) and value.strip():
            recipe[key] = value.strip()
    return recipe
