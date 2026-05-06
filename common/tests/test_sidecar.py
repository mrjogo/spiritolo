import json
from pathlib import Path

import pytest

from common.llm.sidecar import (
    Sidecar, SidecarMismatch, find_ingestable_batch_ids,
    force_unmark_ingested, load_sidecar, mark_failed, mark_ingested,
    write_sidecar,
)


def test_write_then_load_roundtrips(tmp_path):
    sc = Sidecar(
        batch_id="batch_abc",
        provider="openai",
        flow="mapping.resolve_pending",
        model_id="gpt-5-mini",
        version_constant="v3",
        submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka", "r1": "rye"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    assert path == tmp_path / "batch_abc.json"
    assert path.exists()

    loaded = load_sidecar("batch_abc", batches_dir=tmp_path)
    assert loaded == sc


def test_load_refuses_on_flow_mismatch(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    write_sidecar(sc, batches_dir=tmp_path)
    with pytest.raises(SidecarMismatch, match="flow mismatch"):
        load_sidecar("b1", batches_dir=tmp_path,
                     expected_flow="dedup.normalize_names.resolve_pending")


def test_load_refuses_on_version_mismatch(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    write_sidecar(sc, batches_dir=tmp_path)
    with pytest.raises(SidecarMismatch, match="version mismatch"):
        load_sidecar("b1", batches_dir=tmp_path,
                     expected_flow="mapping.resolve_pending",
                     expected_version="v4")


def test_load_raises_filenotfound_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sidecar("nope", batches_dir=tmp_path)


def test_mark_ingested_renames_file(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    new_path = mark_ingested(path)
    assert new_path == tmp_path / "b1.json.ingested"
    assert new_path.exists()
    assert not path.exists()


def test_load_refuses_already_ingested(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    mark_ingested(path)
    with pytest.raises(SidecarMismatch, match="already ingested"):
        load_sidecar("b1", batches_dir=tmp_path)


@pytest.mark.parametrize("state", ["failed", "expired", "cancelled"])
def test_mark_failed_renames_file(tmp_path, state):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    new_path = mark_failed(path, state=state)
    assert new_path == tmp_path / f"b1.json.{state}"
    assert new_path.exists()
    assert not path.exists()


def test_mark_failed_rejects_unknown_state(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    with pytest.raises(ValueError, match="unknown terminal state"):
        mark_failed(path, state="completed")


@pytest.mark.parametrize("state", ["failed", "expired", "cancelled"])
def test_load_refuses_after_mark_failed(tmp_path, state):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    mark_failed(path, state=state)
    with pytest.raises(SidecarMismatch, match=state):
        load_sidecar("b1", batches_dir=tmp_path)


def test_force_unmark_ingested_renames_back(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={"r0": "vodka"},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    mark_ingested(path)
    assert (tmp_path / "b1.json.ingested").exists()
    assert not (tmp_path / "b1.json").exists()

    new_path = force_unmark_ingested("b1", batches_dir=tmp_path)
    assert new_path == tmp_path / "b1.json"
    assert new_path.exists()
    assert not (tmp_path / "b1.json.ingested").exists()

    # And load_sidecar accepts it again.
    loaded = load_sidecar("b1", batches_dir=tmp_path)
    assert loaded == sc


def test_force_unmark_ingested_is_noop_when_already_unsuffixed(tmp_path):
    sc = Sidecar(
        batch_id="b1", provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    write_sidecar(sc, batches_dir=tmp_path)
    new_path = force_unmark_ingested("b1", batches_dir=tmp_path)
    assert new_path == tmp_path / "b1.json"
    assert new_path.exists()


def test_force_unmark_ingested_raises_when_neither_exists(tmp_path):
    with pytest.raises(FileNotFoundError):
        force_unmark_ingested("nope", batches_dir=tmp_path)


def _seed(tmp_path, batch_id, *, suffix=None):
    sc = Sidecar(
        batch_id=batch_id, provider="openai",
        flow="mapping.resolve_pending", model_id="gpt-5-mini",
        version_constant="v3", submitted_at="2026-05-05T12:00:00Z",
        request_map={},
    )
    path = write_sidecar(sc, batches_dir=tmp_path)
    if suffix:
        path.rename(path.with_suffix(path.suffix + f".{suffix}"))


def test_find_ingestable_batch_ids_default(tmp_path):
    _seed(tmp_path, "live_a")
    _seed(tmp_path, "live_b")
    _seed(tmp_path, "drained", suffix="ingested")
    _seed(tmp_path, "broken", suffix="failed")

    assert find_ingestable_batch_ids(tmp_path) == ["live_a", "live_b"]


def test_find_ingestable_batch_ids_with_include_ingested(tmp_path):
    _seed(tmp_path, "live")
    _seed(tmp_path, "drained_a", suffix="ingested")
    _seed(tmp_path, "drained_b", suffix="ingested")
    _seed(tmp_path, "broken", suffix="cancelled")

    assert find_ingestable_batch_ids(
        tmp_path, include_ingested=True,
    ) == ["drained_a", "drained_b", "live"]


def test_find_ingestable_batch_ids_skips_terminal_failed(tmp_path):
    """`.failed`/`.expired`/`.cancelled` are never returned, even with
    include_ingested=True — those batches have no provider-side results
    to drain, so re-running ingest is meaningless."""
    _seed(tmp_path, "f", suffix="failed")
    _seed(tmp_path, "e", suffix="expired")
    _seed(tmp_path, "c", suffix="cancelled")
    assert find_ingestable_batch_ids(tmp_path) == []
    assert find_ingestable_batch_ids(tmp_path, include_ingested=True) == []


def test_find_ingestable_batch_ids_empty_dir(tmp_path):
    assert find_ingestable_batch_ids(tmp_path) == []
