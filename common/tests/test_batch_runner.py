import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)
from common.llm.sidecar import load_sidecar


def _stub_provider(batch_id="batch_abc", model_id="gpt-5-mini"):
    p = MagicMock()
    p.model_id = model_id
    p.submit.return_value = BatchSubmission(
        batch_id=batch_id, provider="openai",
        model_id=model_id, request_count=2,
    )
    return p


def test_submit_writes_sidecar_with_request_map(tmp_path):
    provider = _stub_provider()
    rows = [("vodka", "system_prompt", "user_prompt 0"),
            ("rye",   "system_prompt", "user_prompt 1")]

    def to_request(idx, row):
        _, sys_p, user_p = row
        return BatchRequest(custom_id=f"r{idx}", system_prompt=sys_p, user_prompt=user_p)

    def row_to_id(row):
        return row[0]    # the normalized name

    outcome = submit_batch(
        provider=provider, rows=rows,
        to_request=to_request, row_to_id=row_to_id,
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )
    assert isinstance(outcome, BatchSubmitOutcome)
    assert outcome.submission.batch_id == "batch_abc"
    assert outcome.sidecar_path == tmp_path / "batch_abc.json"

    sc = load_sidecar("batch_abc", batches_dir=tmp_path,
                      expected_flow="mapping.resolve_pending",
                      expected_version="v3")
    assert sc.request_map == {"r0": "vodka", "r1": "rye"}
    assert sc.model_id == "gpt-5-mini"
    assert sc.flow == "mapping.resolve_pending"


def test_ingest_dispatches_to_callbacks_and_marks_sidecar(tmp_path):
    # Set up a sidecar from a prior submit.
    provider = _stub_provider()
    rows = [("vodka", "s", "u0"), ("rye", "s", "u1")]

    submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )

    # Now ingest with a stub provider returning two results.
    ingest_provider = MagicMock()
    ingest_provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=2, total=2,
    )
    ingest_provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action":"chose"}', error=None),
        BatchResult(custom_id="r1", raw_text=None, error="rate limited"),
    ])

    seen = []
    def on_result(row_id, raw_text, error):
        seen.append((row_id, raw_text, error))

    counts = ingest_batch(
        provider=ingest_provider, batch_id="batch_abc",
        flow="mapping.resolve_pending", version_constant="v3",
        on_result=on_result, batches_dir=tmp_path,
    )
    assert seen == [
        ("vodka", '{"action":"chose"}', None),
        ("rye",   None,                 "rate limited"),
    ]
    assert counts["ok"] == 1
    assert counts["error"] == 1

    # Sidecar renamed to .ingested.
    assert (tmp_path / "batch_abc.json.ingested").exists()
    assert not (tmp_path / "batch_abc.json").exists()


def test_ingest_continues_when_on_result_raises(tmp_path):
    """A single bad row in a batch (e.g. DB integrity violation) must not
    abort ingest — otherwise a 25k-result batch loses everything after the
    first failure and the sidecar never gets marked .ingested."""
    submit_batch(
        provider=_stub_provider(),
        rows=[("vodka", "s", "u0"), ("rye", "s", "u1"), ("gin", "s", "u2")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )

    ingest_provider = MagicMock()
    ingest_provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=3, total=3,
    )
    ingest_provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action":"chose"}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action":"chose"}', error=None),  # blows up in writer
        BatchResult(custom_id="r2", raw_text='{"action":"chose"}', error=None),
    ])

    seen = []
    def on_result(row_id, raw_text, error):
        if row_id == "rye":
            raise RuntimeError("simulated DB integrity error")
        seen.append(row_id)

    counts = ingest_batch(
        provider=ingest_provider, batch_id="batch_abc",
        flow="mapping.resolve_pending", version_constant="v3",
        on_result=on_result, batches_dir=tmp_path,
    )

    # Loop continued past the failure.
    assert seen == ["vodka", "gin"]
    assert counts["ok"] == 2
    assert counts["writer_error"] == 1

    # Sidecar still got marked .ingested so re-runs noisily skip.
    assert (tmp_path / "batch_abc.json.ingested").exists()
    assert not (tmp_path / "batch_abc.json").exists()


def test_ingest_refuses_when_status_not_completed(tmp_path):
    provider = _stub_provider()
    submit_batch(
        provider=provider, rows=[("v", "s", "u")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending", version_constant="v3",
        batches_dir=tmp_path,
    )

    ingest_provider = MagicMock()
    ingest_provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="in_progress", completed=0, total=1,
    )

    with pytest.raises(RuntimeError, match="not yet completed"):
        ingest_batch(
            provider=ingest_provider, batch_id="batch_abc",
            flow="mapping.resolve_pending", version_constant="v3",
            on_result=lambda *a: None, batches_dir=tmp_path,
        )
