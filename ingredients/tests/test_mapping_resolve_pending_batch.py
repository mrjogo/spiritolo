"""End-to-end batch tests for `map resolve-pending --batch`.

These tests stub the batch provider (no live OpenAI calls) and exercise
the orchestrator's submit + ingest paths via the CLI handler. DB layer is
mocked at the resolver-call boundary."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingredients.mapping.llm_resolver import (
    submit_phase2_batch, ingest_phase2_batch,
)
from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission


def _stub_batch_provider(batch_id="batch_abc"):
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


def test_submit_phase2_batch_writes_sidecar(tmp_path, monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.fetch_pending_llm_names",
        lambda c, mapper_version, limit=None: ["vodka", "rye"],
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._candidates_with_parents",
        lambda c, n: [],
    )

    provider = _stub_batch_provider()
    outcome = submit_phase2_batch(
        conn, provider=provider, batches_dir=tmp_path, limit=None,
    )
    assert outcome.submission.batch_id == "batch_abc"
    assert (tmp_path / "batch_abc.json").exists()


def test_ingest_phase2_batch_dispatches_writes_per_action(tmp_path, monkeypatch):
    # Pre-populate the sidecar by simulating a submit.
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest

    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("vodka", "s", "u0"), ("rye", "s", "u1")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=__import__("ingredients.mapping.mapper", fromlist=["MAPPER_VERSION"]).MAPPER_VERSION,
        batches_dir=tmp_path,
    )

    # Wire ingest with a chose result + an abstain result.
    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=2, total=2,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "node_id": 7}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "abstain"}', error=None),
    ])

    writes_chose: list[tuple[str, int]] = []
    writes_abstain: list[str] = []
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution",
        lambda conn, normalized_name, taxonomy_node_id, source, mapper_version: writes_chose.append((normalized_name, taxonomy_node_id)),
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_abstain",
        lambda conn, normalized_name, mapper_version: writes_abstain.append(normalized_name),
    )

    counts = ingest_phase2_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_abc",
        batches_dir=tmp_path,
    )
    assert ("vodka", 7) in writes_chose
    assert "rye" in writes_abstain
    assert counts["ok"] == 2


def _make_run_all_args(chunk_size: int = 2) -> argparse.Namespace:
    return argparse.Namespace(
        provider="openai", limit=None, yes=True, batch=True,
        ingest=None, wait=False, run_all=True, chunk_size=chunk_size,
        poll_interval=0, model=None,
    )


def test_run_all_drains_queue_in_chunks(tmp_path, monkeypatch):
    """--all loops submit→poll→ingest until the pending queue is empty.

    Stubs the queue + writers so no real DB is needed; the queue shrinks
    by chunk_size per ingest cycle to simulate names being marked llm/abstain
    each pass. Verifies the loop terminates when the queue is empty and
    that aggregate counts roll up across chunks."""
    from ingredients.cli import _run_all_mapping
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission

    # Queue starts at 5 names; each ingest cycle removes 2 (chunk_size).
    pending = ["a", "b", "c", "d", "e"]
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.fetch_pending_llm_names",
        lambda conn, mapper_version, limit=None: pending[:limit] if limit else list(pending),
    )
    # CLI helper also imports fetch_pending_llm_names directly.
    monkeypatch.setattr(
        "ingredients.mapping.db.fetch_pending_llm_names",
        lambda conn, mapper_version, limit=None: pending[:limit] if limit else list(pending),
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._candidates_with_parents",
        lambda c, n: [],
    )
    monkeypatch.setattr(
        "ingredients.mapping.lexical_layer.bulk_lexical_candidates",
        lambda conn, names, limit=20: {n: [] for n in names},
    )

    chose_writes: list[str] = []
    def _write_resolution(conn, normalized_name, taxonomy_node_id, source, mapper_version):
        chose_writes.append(normalized_name)
        # Simulate the row leaving the pending_llm queue.
        if normalized_name in pending:
            pending.remove(normalized_name)
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution", _write_resolution,
    )

    # Provider stub: each submit returns a fresh batch_id; status always
    # 'completed'; fetch_results yields one chose action per request_map entry.
    submit_calls: list[int] = []
    def _submit(requests):
        reqs = list(requests)
        submit_calls.append(len(reqs))
        return BatchSubmission(
            batch_id=f"batch_{len(submit_calls)}", provider="openai",
            model_id="gpt-5-mini", request_count=len(reqs),
        )
    provider = MagicMock()
    provider.model_id = "gpt-5-mini"
    provider.submit.side_effect = _submit

    def _status(batch_id):
        return BatchStatus(batch_id=batch_id, state="completed",
                           completed=submit_calls[-1], total=submit_calls[-1])
    provider.status.side_effect = _status

    # Per-batch fetch_results: yield one 'chose' action per request_map entry
    # in this batch's sidecar.
    from common.llm.sidecar import load_sidecar
    def _fetch_results(batch_id):
        sc = load_sidecar(batch_id, batches_dir=tmp_path)
        return iter([
            BatchResult(
                custom_id=cid,
                raw_text='{"action": "chose", "node_id": 1}',
                error=None,
            )
            for cid in sc.request_map.keys()
        ])
    provider.fetch_results.side_effect = _fetch_results

    # Run the loop.
    db = MagicMock()
    db.conn = MagicMock()
    rc = _run_all_mapping(
        db, provider, tmp_path,
        chunk_size=2, poll_interval=0,
    )
    assert rc == 0
    # 5 names, chunks of 2 → 3 chunks (2, 2, 1).
    assert submit_calls == [2, 2, 1]
    assert chose_writes == ["a", "b", "c", "d", "e"]


def test_run_all_retries_on_enqueue_token_limit(tmp_path, monkeypatch):
    """When OpenAI returns the 'Enqueued token limit reached' error,
    --all sleeps and retries instead of aborting."""
    from ingredients.cli import _run_all_mapping
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission

    pending = ["x", "y"]
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.fetch_pending_llm_names",
        lambda conn, mapper_version, limit=None: pending[:limit] if limit else list(pending),
    )
    monkeypatch.setattr(
        "ingredients.mapping.db.fetch_pending_llm_names",
        lambda conn, mapper_version, limit=None: pending[:limit] if limit else list(pending),
    )
    monkeypatch.setattr(
        "ingredients.mapping.lexical_layer.bulk_lexical_candidates",
        lambda conn, names, limit=20: {n: [] for n in names},
    )

    def _write_resolution(conn, normalized_name, taxonomy_node_id, source, mapper_version):
        if normalized_name in pending:
            pending.remove(normalized_name)
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution", _write_resolution,
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    # First submit raises the enqueue-limit error, second succeeds.
    submit_count = {"n": 0}
    def _submit(requests):
        submit_count["n"] += 1
        if submit_count["n"] == 1:
            raise RuntimeError(
                "Error code: 429 - Enqueued token limit reached for gpt-5-mini "
                "in organization org-XYZ. Limit: 5,000,000 enqueued tokens."
            )
        reqs = list(requests)
        return BatchSubmission(
            batch_id="batch_ok", provider="openai",
            model_id="gpt-5-mini", request_count=len(reqs),
        )
    provider = MagicMock()
    provider.model_id = "gpt-5-mini"
    provider.submit.side_effect = _submit
    provider.status.return_value = BatchStatus(
        batch_id="batch_ok", state="completed", completed=2, total=2,
    )

    from common.llm.sidecar import load_sidecar
    def _fetch_results(batch_id):
        sc = load_sidecar(batch_id, batches_dir=tmp_path)
        return iter([
            BatchResult(custom_id=cid, raw_text='{"action": "chose", "node_id": 1}',
                        error=None)
            for cid in sc.request_map.keys()
        ])
    provider.fetch_results.side_effect = _fetch_results

    db = MagicMock()
    db.conn = MagicMock()
    rc = _run_all_mapping(
        db, provider, tmp_path,
        chunk_size=2, poll_interval=0,
    )
    assert rc == 0
    assert submit_count["n"] == 2  # one rejection + one success
    # Confirm a 30-min backoff sleep happened.
    assert any(s >= 30 * 60 for s in sleep_calls), \
        f"expected an enqueue-limit backoff sleep, got {sleep_calls}"
