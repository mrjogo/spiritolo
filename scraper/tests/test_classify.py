import asyncio
from unittest.mock import AsyncMock

import pytest

from scraper.src.classify import classify_one, run_classify_pool
from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult


async def test_classify_one_records_successful_result(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]

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
    )

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] == "likely_drink_recipe"
    clsf = db.conn.execute("SELECT label, model, prompt_version, raw_response FROM classifications").fetchone()
    assert clsf["label"] == "likely_drink_recipe"
    assert clsf["model"] == "qwen3:14b"
    assert clsf["prompt_version"] == "v1"
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
    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
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
    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
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
