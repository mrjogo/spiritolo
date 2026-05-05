import json
from pathlib import Path

import pytest

from common.llm.sidecar import (
    Sidecar, SidecarMismatch, load_sidecar, mark_ingested, write_sidecar,
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
