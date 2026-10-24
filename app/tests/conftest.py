"""App test fixtures: a fresh database per test, an app without the executor
thread, and clients signed in as an admin / a plain operator."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from common.db import open_database

from spiritolo.auth import SESSION_COOKIE
from spiritolo.main import create_app
from spiritolo.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "test.db"), session_secret="test-secret",
                    public_origin="http://localhost:5173", run_executor=False)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(settings):
    conn = open_database(settings.db_path, migrate=False, audit=True, actor=("system", None, "test"))
    yield conn
    conn.close()


def make_operator(db, handle="ruddick", *, is_admin=True) -> int:
    return db.execute(
        "insert into operators (handle, display_name, is_admin) values (?, ?, ?) returning id",
        (handle, handle.title(), 1 if is_admin else 0),
    ).fetchone()[0]


@pytest.fixture
def admin(app, client, db) -> int:
    op_id = make_operator(db)
    client.cookies.set(SESSION_COOKIE, app.state.spiritolo.sessions.token(op_id))
    return op_id


@pytest.fixture
def operator(app, client, db) -> int:
    op_id = make_operator(db, "guest", is_admin=False)
    client.cookies.set(SESSION_COOKIE, app.state.spiritolo.sessions.token(op_id))
    return op_id


def seed_recipe(db, title="Negroni", site="punch", url=None, ingredients=("gin", "campari", "sweet vermouth")) -> int:
    import json
    url = url or f"https://{site}.example/{title.lower().replace(' ', '-')}"
    rid = db.execute(
        "insert into recipes (source_url, site, source, title) values (?, ?, ?, ?) returning id",
        (url, site, json.dumps({"@type": "Recipe", "name": title, "recipeIngredient": [f"1 oz {i}" for i in ingredients]}), title),
    ).fetchone()[0]
    for pos, name in enumerate(ingredients):
        db.execute(
            "insert into recipe_ingredients (recipe_id, position, name, amount, unit, raw_text) values (?, ?, ?, 1, 'oz', ?)",
            (rid, pos, name, f"1 oz {name}"),
        )
    return rid
