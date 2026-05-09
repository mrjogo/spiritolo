from unittest.mock import MagicMock

from common.llm.batch_provider import BatchRequest, BatchResult, BatchStatus, BatchSubmission
from ingredients.dedup.normalizer_llm import (
    submit_normalize_names_batch, ingest_normalize_names_batch,
)
from ingredients.dedup.version import NORMALIZER_VERSION


def _stub_batch_provider(batch_id="batch_xyz"):
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


def test_submit_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.fetch_pending_canonical_names",
        lambda c, normalizer_version, limit=None: ["The Pegu Club", "negroni sbagliato"],
    )
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.lexical_candidates",
        lambda c, n, limit=20: [],
    )

    provider = _stub_batch_provider()
    outcome = submit_normalize_names_batch(
        MagicMock(), provider=provider, batches_dir=tmp_path,
    )
    assert outcome.submission.batch_id == "batch_xyz"
    assert (tmp_path / "batch_xyz.json").exists()


def test_ingest_dispatches_chose_and_propose(tmp_path, monkeypatch):
    from common.llm.batch_runner import submit_batch
    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("Pegu Club", "s", "u0"), ("Negroni Sbagliato", "s", "u1")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_xyz", state="completed", completed=2, total=2,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "canonical_name": "Pegu Club"}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "propose", "canonical_name": "Negroni Sbagliato"}', error=None),
    ])

    writes_norm: list[tuple[str, str]] = []
    writes_alias: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.write_normalization",
        lambda conn, raw_name, normalized, canonical_name, source, normalizer_version: writes_norm.append((raw_name, canonical_name)),
    )
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.add_cocktail_alias",
        lambda conn, alias, canonical_name, source: writes_alias.append((alias, canonical_name)),
    )

    counts = ingest_normalize_names_batch(
        conn=MagicMock(), provider=provider, batch_id="batch_xyz",
        batches_dir=tmp_path,
    )
    assert ("Pegu Club", "Pegu Club") in writes_norm
    assert ("Negroni Sbagliato", "Negroni Sbagliato") in writes_norm
    assert any(a == "negroni sbagliato" for a, _ in writes_alias)
    assert counts["ok"] == 2


def test_ingest_rolls_back_on_writer_error(tmp_path, monkeypatch):
    """A failing per-row writer must call conn.rollback() so the next
    on_result starts on a clean Postgres transaction. Without rollback,
    a single bad row poisons every subsequent row in the chunk with
    InFailedSqlTransaction."""
    from common.llm.batch_runner import submit_batch
    submit_batch(
        provider=_stub_batch_provider(),
        rows=[("Pegu Club", "s", "u0"), ("Negroni Sbagliato", "s", "u1"), ("Last Word", "s", "u2")],
        to_request=lambda i, r: BatchRequest(custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2]),
        row_to_id=lambda r: r[0],
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        batches_dir=tmp_path,
    )

    provider = MagicMock()
    provider.status.return_value = BatchStatus(
        batch_id="batch_xyz", state="completed", completed=3, total=3,
    )
    provider.fetch_results.return_value = iter([
        BatchResult(custom_id="r0", raw_text='{"action": "chose", "canonical_name": "Pegu Club"}', error=None),
        BatchResult(custom_id="r1", raw_text='{"action": "chose", "canonical_name": "Negroni Sbagliato"}', error=None),
        BatchResult(custom_id="r2", raw_text='{"action": "chose", "canonical_name": "Last Word"}', error=None),
    ])

    def _write_normalization(conn, raw_name, normalized, canonical_name, source, normalizer_version):
        if raw_name == "Negroni Sbagliato":
            raise RuntimeError("simulated FK violation")
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.write_normalization", _write_normalization,
    )

    conn = MagicMock()
    counts = ingest_normalize_names_batch(
        conn=conn, provider=provider, batch_id="batch_xyz",
        batches_dir=tmp_path,
    )
    assert counts["ok"] == 2
    assert counts["writer_error"] == 1
    assert conn.rollback.call_count == 1
