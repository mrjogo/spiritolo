"""Staging and applying an uploaded database through /api/ops/import-db."""
from __future__ import annotations

import hashlib
from pathlib import Path

from common.db import open_database

from conftest import seed_recipe
from spiritolo import importdb


def _build_replacement(tmp_path: Path) -> bytes:
    other = open_database(tmp_path / "replacement.db", migrate=True, audit=False)
    seed_recipe(other, "Imported Negroni", url="https://imported/1")
    seed_recipe(other, "Imported Sazerac", url="https://imported/2")
    other.raw.execute("pragma wal_checkpoint(truncate)")
    other.close()
    return (tmp_path / "replacement.db").read_bytes()


def _post(client, body: bytes, sha: str | None = None):
    headers = {"content-type": "application/octet-stream"}
    headers["x-content-sha256"] = sha if sha is not None else hashlib.sha256(body).hexdigest()
    return client.post("/api/ops/import-db", content=body, headers=headers)


def test_import_requires_admin(client, operator):
    assert _post(client, b"x").status_code == 403


def test_stage_rejects_bad_digest_and_non_sqlite(client, admin, tmp_path):
    r = _post(client, b"not a database", "0" * 64)
    assert r.status_code == 422 and "digest mismatch" in r.json()["detail"]
    r = _post(client, b"not a database at all, really" * 100)
    assert r.status_code == 422 and "SQLite" in r.json()["detail"]
    r = client.post("/api/ops/import-db", content=b"x", headers={"content-type": "application/octet-stream"})
    assert r.status_code == 400
    assert client.get("/api/ops/import-db").json()["staged"] is None


def test_stage_then_apply_swaps_the_live_database(client, admin, db, settings, tmp_path):
    seed_recipe(db, "Original")
    body = _build_replacement(tmp_path)

    r = _post(client, body)
    assert r.status_code == 200, r.text
    staged = r.json()["staged"]
    assert staged["counts"]["recipes"] == 2 and staged["bytes"] == len(body)
    assert staged["pending_migrations"] == []
    assert Path(settings.db_path + ".import").is_file()

    status = client.get("/api/ops/import-db").json()
    assert status["staged"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert status["restart_on_apply"] is False

    # Live data is untouched until apply.
    titles = {r["title"] for r in client.post("/api/ops/query", json={"table": "recipes"}).json()["rows"]}
    assert titles == {"Original"}

    r = client.post("/api/ops/import-db/apply")
    assert r.json() == {"applied": True, "restarting": False}
    assert not Path(settings.db_path + ".import").exists()

    titles = {r["title"] for r in client.post("/api/ops/query", json={"table": "recipes"}).json()["rows"]}
    assert titles == {"Imported Negroni", "Imported Sazerac"}
    # The replacement carried no operators, so the live ones were copied in
    # at stage time and the admin session survives the swap.
    assert staged["operators_carried"] == 1
    assert client.get("/api/ops/import-db").status_code == 200


def test_apply_with_nothing_staged_is_a_conflict(client, admin):
    assert client.post("/api/ops/import-db/apply").status_code == 409


def test_discard_removes_the_staged_file(client, admin, tmp_path, settings):
    assert _post(client, _build_replacement(tmp_path)).status_code == 200
    assert client.delete("/api/ops/import-db").json() == {"discarded": True}
    assert not Path(settings.db_path + ".import").exists()
    assert client.delete("/api/ops/import-db").json() == {"discarded": False}


def test_apply_restart_mode_schedules_exit_instead_of_swapping(client, admin, tmp_path, settings, app, monkeypatch):
    assert _post(client, _build_replacement(tmp_path)).status_code == 200
    calls = []
    monkeypatch.setattr(importdb, "schedule_exit", lambda *a, **k: calls.append(1))
    st = app.state.spiritolo
    object.__setattr__(st.settings, "import_restart", True)
    try:
        assert client.post("/api/ops/import-db/apply").json() == {"applied": False, "restarting": True}
    finally:
        object.__setattr__(st.settings, "import_restart", False)
    assert calls == [1]
    assert Path(settings.db_path + ".import").is_file()  # the entrypoint does the swap


def test_inspect_rejects_unknown_migrations(tmp_path):
    other = open_database(tmp_path / "future.db", migrate=True, audit=False)
    other.execute("insert into schema_migrations (filename) values ('9999_future.sql')")
    other.close()
    try:
        importdb.inspect(tmp_path / "future.db")
    except importdb.ImportError_ as exc:
        assert "9999_future.sql" in str(exc)
    else:
        raise AssertionError("expected rejection")


def test_export_requires_admin(client, operator):
    assert client.get("/api/ops/export-db").status_code == 403


def test_export_downloads_a_consistent_copy_and_cleans_up(client, admin, db, settings, tmp_path):
    seed_recipe(db, "Exported Negroni")
    r = client.get("/api/ops/export-db")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith('attachment; filename="spiritolo-')
    out = tmp_path / "downloaded.db"
    out.write_bytes(r.content)
    # The download is a database the import path accepts as-is.
    assert importdb.inspect(out)["counts"]["recipes"] == 1
    assert not list(Path(settings.db_path).parent.glob("*.export-*"))
