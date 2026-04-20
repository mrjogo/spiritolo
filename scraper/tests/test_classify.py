from unittest.mock import AsyncMock

import pytest

from scraper.src.classify import classify_one
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
