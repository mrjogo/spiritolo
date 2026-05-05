"""Sidecar load + JSON-Schema validation.

The .meta.json file is JSONC: comments allowed (line `//`, block `/* */`).
Comments are stripped with a regex pre-pass that ignores comment-like
substrings inside string literals.
"""
from __future__ import annotations

import dataclasses
import importlib.resources
import json
import pathlib
import re

import jsonschema


class SidecarError(Exception):
    """Any failure loading or validating a sidecar."""


@dataclasses.dataclass(frozen=True)
class Sidecar:
    taken_at: str
    staging_fingerprint: str
    applied_migrations: tuple[str, ...]
    dump_basename: str
    dump_sha256: str
    dump_schema_sha256: str
    backup_script_version: int


# Matches: line comments (//... to EOL), block comments (/* ... */),
# and string literals (so we can pass them through untouched).
_JSONC_PATTERN = re.compile(
    r'"(?:\\.|[^"\\])*"'      # string literal — preserved
    r'|//[^\n]*'              # line comment — replaced with empty
    r'|/\*.*?\*/',            # block comment — replaced with empty
    re.DOTALL,
)


def strip_jsonc_comments(text: str) -> str:
    """Strip `//` and `/* */` comments without eating comment-like
    substrings inside string literals."""
    def _replace(m: re.Match[str]) -> str:
        s = m.group(0)
        if s.startswith('"'):
            return s          # preserve strings
        return ""             # drop comments
    return _JSONC_PATTERN.sub(_replace, text)


def _schema() -> dict:
    with importlib.resources.files("upload_to_staging").joinpath(
        "sidecar.schema.json"
    ).open("rb") as f:
        return json.load(f)


def load_sidecar(path: pathlib.Path) -> Sidecar:
    """Read, parse, schema-validate, and return a Sidecar.

    Raises SidecarError on any failure with a message that names the
    specific problem (file missing, JSON parse failure, schema
    violation).
    """
    if not path.is_file():
        raise SidecarError(f"Sidecar not found at {path}")

    try:
        raw = path.read_text()
    except OSError as e:
        raise SidecarError(f"Could not read sidecar {path}: {e}") from e

    stripped = strip_jsonc_comments(raw)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise SidecarError(f"Could not parse sidecar JSON {path}: {e}") from e

    try:
        jsonschema.validate(data, _schema())
    except jsonschema.ValidationError as e:
        raise SidecarError(
            f"Sidecar {path.name} fails schema validation: {e.message}"
        ) from e

    return Sidecar(
        taken_at=data["taken_at"],
        staging_fingerprint=data["staging_fingerprint"],
        applied_migrations=tuple(data["applied_migrations"]),
        dump_basename=data["dump_basename"],
        dump_sha256=data["dump_sha256"],
        dump_schema_sha256=data["dump_schema_sha256"],
        backup_script_version=data["backup_script_version"],
    )
