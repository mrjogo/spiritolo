"""Dump-file inspection helpers."""
from __future__ import annotations

import hashlib
import pathlib
import subprocess

import pytest

from upload_to_staging.dump import (
    DumpInspectionError,
    sha256_of_file,
    sha256_of_schema_only,
)


def test_sha256_of_file_matches_python_sha256(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello dump\n")
    assert sha256_of_file(p) == hashlib.sha256(b"hello dump\n").hexdigest()


def test_sha256_of_file_missing(tmp_path):
    with pytest.raises(DumpInspectionError, match="not found"):
        sha256_of_file(tmp_path / "nope.dump")


def test_sha256_of_schema_only_runs_pg_restore(tmp_path, monkeypatch):
    """Patch subprocess so we don't need a real dump file."""
    canned = b"-- canned schema-only output\nCREATE TABLE x (...);\n"
    expected = hashlib.sha256(canned).hexdigest()

    class _CompletedProcess:
        returncode = 0
        stdout = canned
        stderr = b""

    captured: dict = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _CompletedProcess()

    monkeypatch.setattr(subprocess, "run", _run)
    p = tmp_path / "fake.dump"
    p.write_bytes(b"")
    got = sha256_of_schema_only(p)
    assert got == expected
    assert captured["cmd"][0] == "pg_restore"
    assert "--schema-only" in captured["cmd"]
    assert str(p) in captured["cmd"]


def test_sha256_of_schema_only_subprocess_failure(tmp_path, monkeypatch):
    class _Failed:
        returncode = 1
        stdout = b""
        stderr = b"pg_restore: error: input file appears to be corrupt"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Failed())
    p = tmp_path / "x.dump"
    p.write_bytes(b"")
    with pytest.raises(DumpInspectionError, match="pg_restore"):
        sha256_of_schema_only(p)
