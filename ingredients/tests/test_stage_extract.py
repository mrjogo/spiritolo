"""extract stage_fn: cached HTML (JSON-LD) -> a recipes row + page ledger."""

from __future__ import annotations

import gzip
import hashlib

import psycopg
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
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "pages", "job_items"):
            c.execute(f"truncate {t} restart identity cascade")
        yield c
        extract.set_corpus_reader(None)
        for t in ("recipes", "pages", "job_items"):
            c.execute(f"truncate {t} restart identity cascade")


def _page(conn, url, content_type="likely_drink_recipe", key=None):
    if key is None:
        key = hashlib.sha256(url.encode()).hexdigest()
    conn.execute(
        "insert into pages (url, site, corpus_key, content_type) values (%s, 'ex', %s, %s)",
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
        "select site, title, author, image_url, source from recipes where source_url=%s", (url,)
    ).fetchone()
    assert row[0] == "ex" and row[1] == "Daiquiri" and row[2] == "Bar"
    assert row[3] == "https://i/x.jpg"
    assert row[4]["recipeIngredient"] == ["2 oz rum", "1 oz lime juice"]

    run = conn.execute(
        "select outcome, code_version from job_items where entity_type='page' and stage='extract'"
    ).fetchone()
    assert run == ("resolved", EXTRACTOR_VERSION)


def test_extract_abstains_when_no_recipe_jsonld(conn):
    url = "https://ex.test/article"
    key = _page(conn, url)
    extract.set_corpus_reader(_FakeCorpus({key: "<html>no recipe here</html>"}))
    counts = extract_stage_fn(_job(), conn, None)
    assert counts["no_recipe"] == 1
    assert conn.execute("select count(*) from recipes").fetchone()[0] == 0


def test_extract_records_html_missing(conn):
    _page(conn, "https://ex.test/gone")
    extract.set_corpus_reader(_FakeCorpus({}))  # key absent -> CorpusMiss
    counts = extract_stage_fn(_job(), conn, None)
    assert counts["html_missing"] == 1
    outcome = conn.execute(
        "select outcome, error_code from job_items where stage='extract'"
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
        "select count(*) from job_items where stage='extract' and outcome='resolved'"
    ).fetchone()[0]
    assert resolved == 5
