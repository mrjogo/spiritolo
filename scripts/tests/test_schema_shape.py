"""Sanity checks on the sidecar JSON Schema itself.

These run before any sidecar parsing — if the schema is broken, every
other test breaks downstream. Prefer to learn here.
"""
from __future__ import annotations

import importlib.resources
import json

import jsonschema


def _load_schema() -> dict:
    with importlib.resources.files("upload_to_staging").joinpath(
        "sidecar.schema.json"
    ).open("rb") as f:
        return json.load(f)


def test_schema_is_valid_draft_2020_12():
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_lists_expected_required_fields():
    schema = _load_schema()
    assert set(schema["required"]) == {
        "taken_at",
        "staging_fingerprint",
        "applied_migrations",
        "dump_basename",
        "dump_sha256",
        "dump_schema_sha256",
        "backup_script_version",
    }


def test_minimal_valid_sidecar_passes_validation():
    schema = _load_schema()
    valid = {
        "taken_at": "2026-05-05T14:30:42.117Z",
        "staging_fingerprint": "0" * 64,
        "applied_migrations": ["20260422120000"],
        "dump_basename": "spiritolo-staging-x.dump",
        "dump_sha256": "0" * 64,
        "dump_schema_sha256": "0" * 64,
        "backup_script_version": 1,
    }
    jsonschema.validate(valid, schema)


def test_missing_required_field_fails():
    schema = _load_schema()
    invalid = {
        "taken_at": "2026-05-05T14:30:42.117Z",
        # staging_fingerprint missing
        "applied_migrations": [],
        "dump_basename": "x",
        "dump_sha256": "0" * 64,
        "dump_schema_sha256": "0" * 64,
        "backup_script_version": 1,
    }
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
