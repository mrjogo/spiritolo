"""Sidecar load + validation."""
from __future__ import annotations

import json

import jsonschema
import pytest

from upload_to_staging.sidecar import (
    Sidecar,
    SidecarError,
    load_sidecar,
    strip_jsonc_comments,
)


def _valid_dict() -> dict:
    return {
        "taken_at": "2026-05-05T14:30:42.117Z",
        "staging_fingerprint": "0" * 64,
        "applied_migrations": ["20260422120000", "20260424054315"],
        "dump_basename": "spiritolo-staging-x.dump",
        "dump_sha256": "a" * 64,
        "dump_schema_sha256": "b" * 64,
        "backup_script_version": 1,
    }


def test_strip_line_comments():
    raw = '{\n  // hi\n  "x": 1\n}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": 1}


def test_strip_block_comments():
    raw = '{\n  /* hi\n     and bye */\n  "x": 1\n}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": 1}


def test_does_not_eat_comment_like_substrings_in_strings():
    raw = '{"x": "// not a comment"}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": "// not a comment"}


def test_load_sidecar_happy_path(tmp_path):
    p = tmp_path / "x.dump.meta.json"
    p.write_text(json.dumps(_valid_dict()))
    s = load_sidecar(p)
    assert isinstance(s, Sidecar)
    assert s.taken_at == "2026-05-05T14:30:42.117Z"
    assert s.applied_migrations == ("20260422120000", "20260424054315")


def test_load_sidecar_missing_file(tmp_path):
    with pytest.raises(SidecarError, match="not found"):
        load_sidecar(tmp_path / "nope.meta.json")


def test_load_sidecar_invalid_json(tmp_path):
    p = tmp_path / "x.meta.json"
    p.write_text('{ this is not json')
    with pytest.raises(SidecarError, match="parse"):
        load_sidecar(p)


def test_load_sidecar_schema_violation(tmp_path):
    bad = _valid_dict()
    del bad["staging_fingerprint"]
    p = tmp_path / "x.meta.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SidecarError) as exc:
        load_sidecar(p)
    assert "schema" in str(exc.value).lower()


def test_load_sidecar_with_jsonc_comments(tmp_path):
    raw = (
        '{\n'
        '  // taken_at is captured after pg_dump returns\n'
        '  "taken_at": "2026-05-05T14:30:42.117Z",\n'
        '  "staging_fingerprint": "' + "0" * 64 + '",\n'
        '  "applied_migrations": [],\n'
        '  "dump_basename": "x.dump",\n'
        '  "dump_sha256": "' + "a" * 64 + '",\n'
        '  "dump_schema_sha256": "' + "b" * 64 + '",\n'
        '  "backup_script_version": 1\n'
        '}'
    )
    p = tmp_path / "x.dump.meta.json"
    p.write_text(raw)
    s = load_sidecar(p)
    assert s.backup_script_version == 1
