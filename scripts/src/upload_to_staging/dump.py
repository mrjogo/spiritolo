"""Dump-file integrity helpers.

`sha256_of_file` reads bytes; `sha256_of_schema_only` shells out to
`pg_restore --schema-only --no-owner --no-privileges -f - <dump>` and hashes
the resulting SQL. The schema-only output is canonical for a given dump
file (just rendering the archive's TOC) so the resulting hash is byte-
stable across runs of pg_restore.

pg_restore >= 17 emits \\restrict / \\unrestrict lines with a random nonce
for psql's RESTRCT-mode security feature. These are stripped before hashing
so the hash is stable across calls and matches the sidecar written by the
backup script.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess


class DumpInspectionError(Exception):
    """Any failure reading or running pg_restore against a dump."""


_BUF_SIZE = 64 * 1024
# pg_restore >= 17 injects \restrict / \unrestrict lines with a random
# nonce into the schema-only output. Strip them so the hash is stable.
_RESTRICT_RE = re.compile(rb"^\\(un)?restrict\b.*$\n?", re.MULTILINE)


def sha256_of_file(path: pathlib.Path) -> str:
    if not path.is_file():
        raise DumpInspectionError(f"Dump file not found: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_BUF_SIZE):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_schema_only(path: pathlib.Path) -> str:
    if not path.is_file():
        raise DumpInspectionError(f"Dump file not found: {path}")
    proc = subprocess.run(
        ["pg_restore", "--schema-only", "--no-owner", "--no-privileges",
         "-f", "-", str(path)],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise DumpInspectionError(
            f"pg_restore --schema-only failed for {path}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    normalized = _RESTRICT_RE.sub(b"", proc.stdout)
    return hashlib.sha256(normalized).hexdigest()
