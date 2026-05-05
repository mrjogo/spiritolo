"""End-to-end batch tests for `map resolve-pending --batch`.

These tests stub the batch provider (no live OpenAI calls) and exercise
the orchestrator's submit + ingest paths via the CLI handler. DB layer is
mocked at the resolver-call boundary."""

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
