import asyncio
from unittest.mock import AsyncMock

import pytest

from scraper.src.classify import classify_one, run_classify_pool
from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult


# ---------------------------------------------------------------------------
# CLI arg parser tests (Task 10)
# ---------------------------------------------------------------------------

from scraper.src.classify import build_arg_parser


def test_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.site is None
    assert args.limit is None
    assert args.concurrency == 4
    assert args.model == "qwen3:14b"
    assert args.review is False
    assert args.sample is False


def test_arg_parser_main_run_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--site", "liquor", "--limit", "100", "--concurrency", "8", "--model", "qwen3:32b"])
    assert args.site == "liquor"
    assert args.limit == 100
    assert args.concurrency == 8
    assert args.model == "qwen3:32b"


def test_arg_parser_sample_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--sample", "--site", "liquor", "--category", "likely_drink_recipe", "--n", "20"])
    assert args.sample is True
    assert args.site == "liquor"
    assert args.category == "likely_drink_recipe"
    assert args.n == 20


def test_arg_parser_review_flag():
    parser = build_arg_parser()
    args = parser.parse_args(["--review"])
    assert args.review is True


def test_arg_parser_batch_size_default():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.batch_size == 1000


async def test_classify_one_records_successful_result(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]
    run_id = db.start_run(stage="classify_url")

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_drink_recipe",
        raw_response='{"label": "likely_drink_recipe"}',
        latency_ms=123,
    ))

    await classify_one(
        row=row,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version="v1",
        run_id=run_id,
    )

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] == "likely_drink_recipe"
    clsf = db.conn.execute(
        "SELECT label, model, prompt_version, raw_response, run_id FROM classify_url_runs"
    ).fetchone()
    assert clsf["label"] == "likely_drink_recipe"
    assert clsf["model"] == "qwen3:14b"
    assert clsf["prompt_version"] == "v1"
    assert clsf["run_id"] == run_id
    db.close()


async def test_classify_one_passes_url_and_sitemap_to_fn(tmp_db):
    db = Database(tmp_db)
    db.add_urls_batch("testsite", ["https://example.com/r"], sitemap_source="recipes.xml")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_food_recipe", raw_response="{}", latency_ms=10,
    ))

    await classify_one(row=row, classify_fn=fake_classify, db=db, model="m", prompt_version="v")

    fake_classify.assert_awaited_once()
    kwargs = fake_classify.await_args.kwargs
    assert kwargs["url"] == "https://example.com/r"
    assert kwargs["sitemap_source"] == "recipes.xml"
    assert kwargs["model"] == "m"
    db.close()


async def test_classify_one_leaves_row_unclassified_on_error(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(side_effect=ValueError("malformed"))

    # Must not raise — errors are swallowed, logged, and the row stays NULL.
    await classify_one(row=row, classify_fn=fake_classify, db=db, model="m", prompt_version="v")

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] is None
    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classify_url_runs").fetchone()[0]
    assert clsf_count == 0
    db.close()


async def test_classify_one_swallows_transport_errors(tmp_db):
    """Network/transport failures (OSError) must be treated like content errors:
    log and leave the row NULL for the next run to retry."""
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(side_effect=OSError("connection refused"))

    await classify_one(row=row, classify_fn=fake_classify, db=db, model="m", prompt_version="v")

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] is None
    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classify_url_runs").fetchone()[0]
    assert clsf_count == 0
    db.close()


async def test_run_classify_pool_processes_all_rows(tmp_db):
    db = Database(tmp_db)
    for i in range(5):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified()

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_drink_recipe", raw_response="{}", latency_ms=10,
    ))

    await run_classify_pool(
        rows=rows,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version="v1",
        concurrency=3,
    )

    count = db.conn.execute(
        "SELECT COUNT(*) FROM pages WHERE content_type = 'likely_drink_recipe'"
    ).fetchone()[0]
    assert count == 5
    assert fake_classify.await_count == 5
    db.close()


# ---------------------------------------------------------------------------
# Batched main loop tests (Task 10 amendment)
# ---------------------------------------------------------------------------

async def test_run_main_processes_in_batches(tmp_db, monkeypatch):
    """run_main should call get_unclassified repeatedly with limit=batch_size,
    not pull the whole queue at once."""
    db = Database(tmp_db)
    for i in range(7):
        db.add_url("testsite", f"https://example.com/{i}")
    db.close()

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_drink_recipe", raw_response="{}", latency_ms=1,
    ))
    monkeypatch.setattr("scraper.src.classify.classify_url", fake_classify)

    parser = build_arg_parser()
    args = parser.parse_args([
        "--db", str(tmp_db),
        "--batch-size", "3",
        "--concurrency", "2",
    ])

    from scraper.src.classify import run_main
    rc = await run_main(args)
    assert rc == 0

    # Verify all 7 rows got classified across multiple batches.
    db2 = Database(tmp_db)
    count = db2.conn.execute(
        "SELECT COUNT(*) FROM pages WHERE content_type = 'likely_drink_recipe'"
    ).fetchone()[0]
    assert count == 7
    assert fake_classify.await_count == 7
    db2.close()


async def test_run_main_respects_overall_limit(tmp_db, monkeypatch):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/{i}")
    db.close()

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_junk", raw_response="{}", latency_ms=1,
    ))
    monkeypatch.setattr("scraper.src.classify.classify_url", fake_classify)

    parser = build_arg_parser()
    args = parser.parse_args([
        "--db", str(tmp_db),
        "--batch-size", "3",
        "--limit", "5",
    ])
    from scraper.src.classify import run_main
    await run_main(args)

    assert fake_classify.await_count == 5


async def test_run_classify_pool_respects_concurrency_limit(tmp_db):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified()

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def tracking_classify(url, sitemap_source, model):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return ClassificationResult(label="likely_junk", raw_response="{}", latency_ms=10)

    await run_classify_pool(
        rows=rows,
        classify_fn=tracking_classify,
        db=db,
        model="m",
        prompt_version="v",
        concurrency=3,
    )

    assert max_in_flight <= 3
    assert max_in_flight >= 2  # should actually parallelize
    db.close()


# ---------------------------------------------------------------------------
# Review mode tests (Task 11)
# ---------------------------------------------------------------------------

from scraper.src.classify import load_eval_set, run_review


def test_load_eval_set_parses_jsonl(tmp_path):
    p = tmp_path / "eval.jsonl"
    p.write_text(
        '{"url": "https://a.com/1", "sitemap_source": "s.xml", "expected": "likely_drink_recipe"}\n'
        '{"url": "https://b.com/1", "sitemap_source": null, "expected": "likely_junk"}\n'
    )
    entries = load_eval_set(p)
    assert len(entries) == 2
    assert entries[0]["url"] == "https://a.com/1"
    assert entries[0]["expected"] == "likely_drink_recipe"
    assert entries[1]["sitemap_source"] is None


async def test_run_review_reports_pass_and_fail_counts(tmp_path, capsys):
    eval_path = tmp_path / "eval.jsonl"
    eval_path.write_text(
        '{"url": "https://a.com/1", "sitemap_source": null, "expected": "likely_drink_recipe"}\n'
        '{"url": "https://b.com/1", "sitemap_source": null, "expected": "likely_junk"}\n'
    )

    async def fake_classify(url, sitemap_source, model):
        if url == "https://a.com/1":
            return ClassificationResult(label="likely_drink_recipe", raw_response="{}", latency_ms=1)
        return ClassificationResult(label="likely_drink_article", raw_response="{}", latency_ms=1)

    rc = await run_review(eval_path=eval_path, classify_fn=fake_classify, model="qwen3:14b")

    out = capsys.readouterr().out
    assert "1/2 correct" in out or "correct: 1" in out
    assert "https://b.com/1" in out  # failing row must be printed
    assert rc in (0, 1)  # 0 if all pass, 1 if any fail — implementation choice


# ---------------------------------------------------------------------------
# Sample mode tests (Task 12)
# ---------------------------------------------------------------------------

from scraper.src.classify import run_sample


def test_run_sample_prints_matching_rows(tmp_db, capsys):
    db = Database(tmp_db)
    db.add_url("liquor", "https://liquor.com/recipes/negroni")
    db.add_url("liquor", "https://liquor.com/recipes/margarita")
    db.add_url("foodnetwork", "https://foodnetwork.com/recipes/salmon")

    ids = {r["url"]: r["id"] for r in db.conn.execute("SELECT id, url FROM pages").fetchall()}
    for url, label in [
        ("https://liquor.com/recipes/negroni", "likely_drink_recipe"),
        ("https://liquor.com/recipes/margarita", "likely_drink_recipe"),
        ("https://foodnetwork.com/recipes/salmon", "likely_food_recipe"),
    ]:
        db.record_classify_url(
            page_id=ids[url], run_id=None, label=label, model="qwen3:14b",
            prompt_version="v1", raw_response="{}", latency_ms=1,
            pages_content_type_before=None,
        )
    db.close()

    rc = run_sample(db_path=tmp_db, site="liquor", category="likely_drink_recipe", n=10)
    out = capsys.readouterr().out

    assert rc == 0
    assert "negroni" in out
    assert "margarita" in out
    assert "salmon" not in out  # different site


# ---------------------------------------------------------------------------
# Task 13: End-to-end smoke test
# ---------------------------------------------------------------------------

from scraper.src.classify_prompt import PROMPT_VERSION


@pytest.mark.asyncio
async def test_end_to_end_classify_run_with_mocked_ollama(tmp_db):
    db = Database(tmp_db)
    # A mix of labels and a pre-classified row that must NOT be revisited.
    db.add_url("liquor", "https://liquor.com/recipes/negroni")
    db.add_url("liquor", "https://liquor.com/tag/gin")
    db.add_url("liquor", "https://liquor.com/articles/home-bar-guide")
    db.set_content_type("https://liquor.com/recipes/negroni", "likely_drink_recipe")

    def fake_label_for(url):
        if "/tag/" in url:
            return "likely_junk"
        if "/articles/" in url:
            return "likely_drink_article"
        return "likely_drink_recipe"

    async def fake_classify(url, sitemap_source, model):
        return ClassificationResult(
            label=fake_label_for(url), raw_response="{}", latency_ms=5,
        )

    rows = db.get_unclassified()
    assert len(rows) == 2  # pre-classified row excluded

    await run_classify_pool(
        rows=rows,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version=PROMPT_VERSION,
        concurrency=2,
    )

    labels = dict(db.conn.execute("SELECT url, content_type FROM pages").fetchall())
    assert labels["https://liquor.com/recipes/negroni"] == "likely_drink_recipe"
    assert labels["https://liquor.com/tag/gin"] == "likely_junk"
    assert labels["https://liquor.com/articles/home-bar-guide"] == "likely_drink_article"

    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classify_url_runs").fetchone()[0]
    assert clsf_count == 2  # only the two new classifications, not the pre-existing row
    db.close()


# ---------------------------------------------------------------------------
# Infinite-loop guard and success-count tests
# ---------------------------------------------------------------------------

async def test_run_main_aborts_when_batch_produces_zero_successes(tmp_db, monkeypatch, capsys):
    """If ollama is down, every classify call fails and every row stays NULL.
    The next batch would return the same rows, so the loop must abort instead
    of spinning forever."""
    db = Database(tmp_db)
    for i in range(3):
        db.add_url("testsite", f"https://example.com/{i}")
    db.close()

    always_fails = AsyncMock(side_effect=OSError("ollama unreachable"))
    monkeypatch.setattr("scraper.src.classify.classify_url", always_fails)

    parser = build_arg_parser()
    args = parser.parse_args(["--db", str(tmp_db), "--batch-size", "3"])

    from scraper.src.classify import run_main
    rc = await run_main(args)

    assert rc == 1
    err = capsys.readouterr().err
    assert "zero classifications" in err

    # No row should have been classified.
    db2 = Database(tmp_db)
    count = db2.conn.execute("SELECT COUNT(*) FROM pages WHERE content_type IS NOT NULL").fetchone()[0]
    assert count == 0
    db2.close()


async def test_run_classify_pool_returns_success_count(tmp_db):
    db = Database(tmp_db)
    for i in range(4):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified()

    # Two succeed, two fail.
    call_count = 0
    async def sometimes(url, sitemap_source, model):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return ClassificationResult(label="likely_junk", raw_response="{}", latency_ms=1)
        raise OSError("boom")

    successes = await run_classify_pool(
        rows=rows, classify_fn=sometimes, db=db,
        model="m", prompt_version="v", concurrency=1,
    )
    assert successes == 2
    db.close()


async def test_run_main_uses_one_shared_ollama_client_across_batches(tmp_db, monkeypatch):
    """run_main must build the AsyncClient once and reuse it, not once per URL."""
    db = Database(tmp_db)
    for i in range(5):
        db.add_url("testsite", f"https://example.com/{i}")
    db.close()

    constructed_count = 0
    class CountingClient:
        def __init__(self, *args, **kwargs):
            nonlocal constructed_count
            constructed_count += 1
        async def chat(self, *args, **kwargs):
            return {"message": {"content": '{"label": "likely_drink_recipe"}'}, "done": True}

    monkeypatch.setattr("scraper.src.classify.AsyncClient", CountingClient)
    monkeypatch.setattr("scraper.src.ollama_client.AsyncClient", CountingClient)

    parser = build_arg_parser()
    args = parser.parse_args(["--db", str(tmp_db), "--batch-size", "2", "--concurrency", "2"])
    from scraper.src.classify import run_main
    rc = await run_main(args)

    assert rc == 0
    # Exactly one AsyncClient constructed, even across 3 batches of 5 URLs total.
    assert constructed_count == 1
