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
