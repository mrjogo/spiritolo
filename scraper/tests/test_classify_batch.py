from unittest.mock import MagicMock

import pytest

from common.llm.batch_provider import (
    BatchRequest, BatchResult, BatchStatus, BatchSubmission,
)
from scraper.classify import ingest_classify_batch, submit_classify_batch
from scraper.classify_prompt import PROMPT_VERSION


def _stub_batch_provider(batch_id: str = "batch_cls") -> MagicMock:
    p = MagicMock()
    p.model_id = "gpt-5-mini"
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id="gpt-5-mini", request_count=2,
    )
    p.status.return_value = BatchStatus(
        batch_id=batch_id, state="completed", completed=2, total=2,
    )
    return p


def test_submit_writes_sidecar(tmp_db, tmp_path):
    from scraper.db import Database
    db = Database(tmp_db)
    try:
        # Insert two unclassified pages.
        db.add_url("punch", "https://punch/a")
        db.add_url("punch", "https://punch/b")
        provider = _stub_batch_provider()
        outcome = submit_classify_batch(
            db, provider=provider, batches_dir=tmp_path,
            site="punch", limit=None,
        )
        assert outcome.submission.batch_id == "batch_cls"
        assert (tmp_path / "batch_cls.json").exists()
    finally:
        db.close()


def test_ingest_writes_classify_runs(tmp_db, tmp_path):
    from common.llm.batch_runner import submit_batch
    from scraper.db import Database
    db = Database(tmp_db)
    try:
        db.add_url("punch", "https://punch/a")
        db.add_url("punch", "https://punch/b")

        # Pre-populate sidecar by simulating a submit (use real submit_batch
        # so the request_map matches what ingest will look up).
        rows = [(r["url"], "s", "u") for r in db.get_unclassified(site="punch", limit=2)]
        submit_batch(
            provider=_stub_batch_provider(),
            rows=rows,
            to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
            row_to_id=lambda r: r[0],
            flow="scraper.classify.url",
            version_constant=PROMPT_VERSION,
            batches_dir=tmp_path,
        )

        provider = MagicMock()
        provider.model_id = "gpt-5-mini"
        provider.status.return_value = BatchStatus(
            batch_id="batch_cls", state="completed", completed=2, total=2,
        )
        provider.fetch_results.return_value = iter([
            BatchResult(custom_id="r0", raw_text='{"label":"likely_drink_recipe"}', error=None),
            BatchResult(custom_id="r1", raw_text='{"label":"likely_junk"}', error=None),
        ])

        counts = ingest_classify_batch(
            db=db, provider=provider, batch_id="batch_cls",
            batches_dir=tmp_path,
        )
        # Both rows now have content_type set.
        labels = [
            r["content_type"] for r in db.conn.execute(
                "SELECT content_type FROM pages WHERE site='punch' ORDER BY url"
            ).fetchall()
        ]
        assert labels == ["likely_drink_recipe", "likely_junk"]
        assert counts["ok"] == 2
    finally:
        db.close()
