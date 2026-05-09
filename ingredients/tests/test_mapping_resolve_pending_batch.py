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


def test_ingest_phase2_batch_abstains_when_chose_node_id_does_not_exist(tmp_path, monkeypatch):
    """LLM hallucinations of the form `chose: {node_id: 1001}` where 1001
    isn't a real taxonomy node would FK-violate on the UPDATE, abort the
    transaction, and (without the cascade fix) poison the rest of the chunk.
    Defense in depth: validate node_id existence at on_result time and
    abstain on miss, so the FK violation never reaches Postgres."""
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest

    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("vodka", "s", "u0"), ("ghost_ingredient", "s", "u1")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=__import__("ingredients.mapping.mapper", fromlist=["MAPPER_VERSION"]).MAPPER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=2, total=2,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "node_id": 7}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "chose", "node_id": 1001}', error=None),
    ])

    # Stub the existence check: node 7 exists, node 1001 does not.
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._node_exists",
        lambda conn, node_id: node_id == 7,
    )

    chose_writes: list[tuple[str, int]] = []
    abstain_writes: list[str] = []
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution",
        lambda conn, normalized_name, taxonomy_node_id, source, mapper_version: chose_writes.append((normalized_name, taxonomy_node_id)),
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_abstain",
        lambda conn, normalized_name, mapper_version: abstain_writes.append(normalized_name),
    )

    counts = ingest_phase2_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_abc",
        batches_dir=tmp_path,
    )
    # Real chose hit write_resolution; hallucinated chose was diverted to abstain.
    assert chose_writes == [("vodka", 7)]
    assert abstain_writes == ["ghost_ingredient"]
    # Both rows count as "ok" (no exception raised, no FK violation).
    assert counts["ok"] == 2
    assert counts.get("writer_error", 0) == 0


def test_ingest_phase2_batch_abstains_when_propose_brand_has_invalid_node_kind(tmp_path, monkeypatch):
    """taxonomy_nodes.node_kind is CHECK-constrained to ('brand','expression').
    An LLM that proposes `node_kind: 'liqueur'` would CHECK-violate on the
    INSERT, abort the txn, and lose the rest of the chunk. We catch it
    pre-INSERT and abstain instead."""
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest

    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("weirdo", "s", "u0")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=__import__("ingredients.mapping.mapper", fromlist=["MAPPER_VERSION"]).MAPPER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=1, total=1,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(
            custom_id="r0",
            raw_text='{"action": "propose_brand", "slug": "weirdo", "display_name": "Weirdo", "parent_slug": "vodka", "node_kind": "liqueur"}',
            error=None,
        ),
    ])

    abstain_writes: list[str] = []
    create_calls: list[str] = []
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_abstain",
        lambda conn, normalized_name, mapper_version: abstain_writes.append(normalized_name),
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._create_brand_node",
        lambda **kwargs: create_calls.append(kwargs["slug"]) or 999,
    )

    counts = ingest_phase2_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_abc",
        batches_dir=tmp_path,
    )
    # Bad node_kind diverted to abstain; _create_brand_node never invoked.
    assert abstain_writes == ["weirdo"]
    assert create_calls == []
    assert counts["ok"] == 1
    assert counts.get("writer_error", 0) == 0


def test_ingest_phase2_batch_rolls_back_on_writer_error(tmp_path, monkeypatch):
    """A failing per-row writer (e.g. FK violation) must call conn.rollback()
    so the next on_result starts on a clean transaction. Otherwise psycopg
    raises InFailedSqlTransaction for every subsequent row in the chunk."""
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest

    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("vodka", "s", "u0"), ("rye", "s", "u1"), ("gin", "s", "u2")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="mapping.resolve_pending",
        version_constant=__import__("ingredients.mapping.mapper", fromlist=["MAPPER_VERSION"]).MAPPER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_abc", state="completed", completed=3, total=3,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "node_id": 1}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "chose", "node_id": 2}', error=None),
        BatchResult(custom_id="r2", raw_text='{"action": "chose", "node_id": 3}', error=None),
    ])

    def _write_resolution(conn, normalized_name, taxonomy_node_id, source, mapper_version):
        if normalized_name == "rye":
            raise RuntimeError("simulated FK violation")
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution", _write_resolution,
    )

    conn = MagicMock()
    counts = ingest_phase2_batch(
        conn=conn, provider=provider, batch_id="batch_abc",
        batches_dir=tmp_path,
    )
    # The middle row failed; the outer loop continued past it and the third
    # row was processed cleanly because rollback() ran in between.
    assert counts["ok"] == 2
    assert counts["writer_error"] == 1
    # The writer that raised must have triggered exactly one rollback so the
    # next on_result didn't inherit an aborted Postgres transaction.
    assert conn.rollback.call_count == 1


def _make_drain_args(chunk_size: int = 2, limit=None) -> argparse.Namespace:
    return argparse.Namespace(
        provider="openai", limit=limit, yes=True, batch=True,
        ingest=None, chunk_size=chunk_size,
        poll_interval=0, model=None,
    )


def test_run_all_drains_queue_in_chunks(tmp_path, monkeypatch):
    """--all loops submit→poll→ingest until the pending queue is empty.

    Stubs the queue + writers so no real DB is needed; the queue shrinks
    by chunk_size per ingest cycle to simulate names being marked llm/abstain
    each pass. Verifies the loop terminates when the queue is empty and
    that aggregate counts roll up across chunks."""
    from ingredients.cli import _drain_mapping_in_chunks
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
    rc = _drain_mapping_in_chunks(
        db, provider, tmp_path,
        chunk_size=2, total_limit=None, poll_interval=0,
    )
    assert rc == 0
    # 5 names, chunks of 2 → 3 chunks (2, 2, 1).
    assert submit_calls == [2, 2, 1]
    assert chose_writes == ["a", "b", "c", "d", "e"]


def test_run_all_retries_on_enqueue_token_limit(tmp_path, monkeypatch):
    """When OpenAI returns the 'Enqueued token limit reached' error,
    --all sleeps and retries instead of aborting."""
    from ingredients.cli import _drain_mapping_in_chunks
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
    rc = _drain_mapping_in_chunks(
        db, provider, tmp_path,
        chunk_size=2, total_limit=None, poll_interval=0,
    )
    assert rc == 0
    assert submit_count["n"] == 2  # one rejection + one success
    # Confirm a 30-min backoff sleep happened.
    assert any(s >= 30 * 60 for s in sleep_calls), \
        f"expected an enqueue-limit backoff sleep, got {sleep_calls}"


def test_drain_respects_total_limit(tmp_path, monkeypatch):
    """`--limit N` caps the total names drained across chunks. With
    chunk_size=2 and total_limit=4, the drain stops after exactly 2
    chunks even though more names remain pending."""
    from ingredients.cli import _drain_mapping_in_chunks
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission

    pending = ["a", "b", "c", "d", "e", "f", "g"]
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
    rc = _drain_mapping_in_chunks(
        db, provider, tmp_path,
        chunk_size=2, total_limit=4, poll_interval=0,
    )
    assert rc == 0
    # 7 names pending, chunk_size=2, limit=4 → 2 chunks of 2 each, then stop.
    assert submit_calls == [2, 2]
    # 4 names drained; 3 remain in the queue (untouched by this run).
    assert len(pending) == 3


def test_drain_chunk_size_capped_by_remaining_limit(tmp_path, monkeypatch):
    """If chunk_size > remaining_limit, the chunk shrinks to fit the cap.
    chunk_size=10 + total_limit=3 → one chunk of 3, not 10."""
    from ingredients.cli import _drain_mapping_in_chunks
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission

    pending = ["a", "b", "c", "d", "e"]
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
    rc = _drain_mapping_in_chunks(
        db, provider, tmp_path,
        chunk_size=10, total_limit=3, poll_interval=0,
    )
    assert rc == 0
    assert submit_calls == [3]  # one chunk of 3, capped by total_limit
