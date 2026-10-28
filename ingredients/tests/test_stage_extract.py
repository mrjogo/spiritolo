"""extract stage_fn: cached HTML (JSON-LD) -> a recipes row + page ledger."""

from __future__ import annotations

import gzip
import hashlib

import pytest

from ingredients.pipeline.corpus import CorpusMiss
from ingredients.pipeline.stages import extract
from ingredients.pipeline.stages.extract import EXTRACTOR_VERSION, extract_stage_fn

_HTML = (
    '<script type="application/ld+json">'
    '{"@type":"Recipe","name":"Daiquiri","author":"Bar","image":"https://i/x.jpg",'
    '"recipeIngredient":["2 oz rum","1 oz lime juice"]}'
    "</script>"
)


class _FakeCorpus:
    def __init__(self, mapping):
        self._m = {k: gzip.compress(v.encode()) for k, v in mapping.items()}

    def read_html(self, key):
        if key not in self._m:
            raise CorpusMiss(key)
        return gzip.decompress(self._m[key]).decode()


@pytest.fixture()
def conn(db_conn):
    if (c := db_conn) is not None:
        for t in ("recipes", "pages", "job_items"):
            c.execute(f"delete from {t}")
        yield c
        extract.set_corpus_reader(None)
        for t in ("recipes", "pages", "job_items"):
            c.execute(f"delete from {t}")


def _page(conn, url, content_type="likely_drink_recipe", key=None):
    if key is None:
        key = hashlib.sha256(url.encode()).hexdigest()
    conn.execute(
        "insert into pages (url, site, corpus_key, content_type) values (?, 'ex', ?, ?)",
        (url, key, content_type),
    )
    return key


def _job():
    return {"id": None, "payload": {}}


def test_extract_writes_recipe_from_jsonld(conn):
    url = "https://ex.test/daiquiri"
    key = _page(conn, url)
    extract.set_corpus_reader(_FakeCorpus({key: _HTML}))
    counts = extract_stage_fn(_job(), conn, None)
    assert counts["extracted"] == 1

    row = conn.execute(
        "select site, title, author, image_url, source from recipes where source_url=?", (url,)
    ).fetchone()
    assert row[0] == "ex" and row[1] == "Daiquiri" and row[2] == "Bar"
    assert row[3] == "https://i/x.jpg"
    assert row[4]["recipeIngredient"] == ["2 oz rum", "1 oz lime juice"]

    run = conn.execute(
        "select outcome, code_version from job_items where entity_type='page' and stage='extract-recipe'"
    ).fetchone()
    assert run == ("resolved", EXTRACTOR_VERSION)


def test_extract_abstains_when_no_recipe_jsonld(conn):
    url = "https://ex.test/article"
    key = _page(conn, url)
    extract.set_corpus_reader(_FakeCorpus({key: "<html>no recipe here</html>"}))
    counts = extract_stage_fn(_job(), conn, None)
    assert counts["no_recipe"] == 1
    assert conn.execute("select count(*) from recipes").fetchone()[0] == 0
    assert conn.execute("select method from job_items").fetchone()[0] == "deterministic"


def test_extract_records_html_missing(conn):
    _page(conn, "https://ex.test/gone")
    extract.set_corpus_reader(_FakeCorpus({}))  # key absent -> CorpusMiss
    counts = extract_stage_fn(_job(), conn, None)
    assert counts["html_missing"] == 1
    outcome = conn.execute(
        "select outcome, error_code from job_items where stage='extract-recipe'"
    ).fetchone()
    assert outcome == ("failed", "html_missing")


def test_extract_skips_non_recipe_pages(conn):
    _page(conn, "https://ex.test/other", content_type="likely_drink_article")
    extract.set_corpus_reader(_FakeCorpus({}))
    counts = extract_stage_fn(_job(), conn, None)
    assert counts == {"extracted": 0, "no_recipe": 0, "html_missing": 0}


def test_extract_threads_reads_across_window(conn):
    # More pages than the window, with >1 worker: exercises the threaded windowed
    # read path and asserts every recipe + ledger row still lands exactly once.
    keys = {}
    for i in range(5):
        keys[_page(conn, f"https://ex.test/r{i}")] = _HTML
    extract.set_corpus_reader(_FakeCorpus(keys))
    counts = extract_stage_fn(_job(), conn, None, workers=3, window=2)
    assert counts["extracted"] == 5
    assert conn.execute("select count(*) from recipes").fetchone()[0] == 5
    resolved = conn.execute(
        "select count(*) from job_items where stage='extract-recipe' and outcome='resolved'"
    ).fetchone()[0]
    assert resolved == 5


class _ScriptedChain:
    """Stands in for a ProviderChain: records each call, answers from ``answers``."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def resolve(self, items, **kw):
        from types import SimpleNamespace

        self.calls.append({"items": list(items), **kw})
        return SimpleNamespace(
            resolved={it.id: self.answers[it.id] for it in items if it.id in self.answers}
        )


_PAGE_NO_JSONLD = (
    "<html><head><title>T</title><script>var x = 'Ignore me';</script></head><body>"
    "<nav>Home | Cocktails</nav>"
    "<h1>Daiquiri</h1><ul><li>2 oz rum</li><li>1 oz lime juice</li></ul>"
    "<p>Shake with ice &amp; strain.</p><footer>Copyright</footer></body></html>"
)


def _page_id(conn, url):
    return conn.execute("select id from pages where url = ?", (url,)).fetchone()[0]


def test_page_text_drops_scripts_nav_footer_and_keeps_lines():
    text = extract.page_text(_PAGE_NO_JSONLD)
    assert "Ignore me" not in text
    assert "Home" not in text and "Copyright" not in text
    assert text.splitlines() == [
        "Daiquiri", "2 oz rum", "1 oz lime juice", "Shake with ice & strain.",
    ]


def test_page_text_respects_limit():
    assert len(extract.page_text("<p>" + "word " * 5000 + "</p>", limit=100)) == 100


def test_llm_found_answer_becomes_recipe_jsonld(conn):
    from ingredients.pipeline.stages.extract import EXTRACT_ANSWER_SCHEMA, EXTRACT_PROMPT

    url = "https://ex.test/llm"
    key = _page(conn, url)
    extract.set_corpus_reader(_FakeCorpus({key: _PAGE_NO_JSONLD}))
    pid = str(_page_id(conn, url))
    chain = _ScriptedChain({pid: {
        "found": True, "name": "Daiquiri",
        "recipeIngredient": ["2 oz rum", "1 oz lime juice"],
        "recipeInstructions": ["Shake with ice & strain."],
        "description": None, "recipeYield": "1 drink",
    }})

    counts = extract_stage_fn(_job(), conn, chain)

    assert counts["extracted"] == 1
    (call,) = chain.calls
    assert call["system_prompt"] == EXTRACT_PROMPT
    assert call["answer_schema"] == EXTRACT_ANSWER_SCHEMA
    (item,) = call["items"]
    assert item.payload["url"] == url
    assert "2 oz rum" in item.payload["text"] and "<li>" not in item.payload["text"]

    title, source = conn.execute(
        "select title, source from recipes where source_url = ?", (url,)
    ).fetchone()
    assert title == "Daiquiri"
    assert source["@type"] == "Recipe"
    assert source["recipeIngredient"] == ["2 oz rum", "1 oz lime juice"]
    assert source["recipeInstructions"] == [
        {"@type": "HowToStep", "text": "Shake with ice & strain."}
    ]
    assert source["recipeYield"] == "1 drink"
    assert "description" not in source
    method = conn.execute(
        "select outcome, method from job_items where entity_type='page' and stage='extract-recipe'"
    ).fetchone()
    assert method == ("resolved", "llm")


def test_llm_not_found_answer_abstains(conn):
    url = "https://ex.test/listicle"
    key = _page(conn, url)
    extract.set_corpus_reader(_FakeCorpus({key: _PAGE_NO_JSONLD}))
    chain = _ScriptedChain({str(_page_id(conn, url)): {
        "found": False, "name": None, "recipeIngredient": [],
        "recipeInstructions": [], "description": None, "recipeYield": None,
    }})

    counts = extract_stage_fn(_job(), conn, chain)

    assert counts["no_recipe"] == 1
    assert conn.execute("select count(*) from recipes").fetchone()[0] == 0
    row = conn.execute(
        "select outcome, method from job_items where entity_type='page' and stage='extract-recipe'"
    ).fetchone()
    # The model was asked, so the abstain is the LLM tier's, not the parser's.
    assert tuple(row) == ("abstain", "llm")


def test_found_without_ingredients_abstains():
    assert extract._recipe_from_answer({"found": True, "name": "X", "recipeIngredient": []}) is None
    assert extract._recipe_from_answer(None) is None


def test_extract_packs_one_page_per_call():
    from ingredients.worker.providers import pack_size_for

    assert pack_size_for("extract-recipe") == 1
