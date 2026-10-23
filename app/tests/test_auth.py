from spiritolo.auth import SESSION_COOKIE

from softauth import SoftPasskey


def register(client, key, handle="ruddick"):
    opts = client.post("/api/auth/register/options", json={"handle": handle, "display_name": "Ruddick"})
    assert opts.status_code == 200, opts.text
    verify = client.post("/api/auth/register/verify", json={"credential": key.create(opts.json()), "label": "test"})
    return verify


def test_bootstrap_registration_creates_admin_and_signs_in(client):
    assert client.get("/api/auth/me").json() == {"operator": None, "setup_required": True}
    key = SoftPasskey("localhost", "http://localhost:5173")
    r = register(client, key)
    assert r.status_code == 200, r.text
    assert r.json()["operator"]["handle"] == "ruddick"
    assert r.json()["operator"]["is_admin"] is True
    me = client.get("/api/auth/me").json()
    assert me["operator"]["handle"] == "ruddick" and me["setup_required"] is False
    assert len(client.get("/api/auth/passkeys").json()) == 1


def test_registration_closed_once_an_operator_exists(client):
    key = SoftPasskey("localhost", "http://localhost:5173")
    assert register(client, key).status_code == 200
    client.cookies.clear()
    r = client.post("/api/auth/register/options", json={"handle": "intruder", "display_name": "x"})
    assert r.status_code == 403


def test_signed_in_operator_can_add_a_second_passkey(client):
    k1 = SoftPasskey("localhost", "http://localhost:5173")
    register(client, k1)
    k2 = SoftPasskey("localhost", "http://localhost:5173")
    opts = client.post("/api/auth/register/options", json={})
    assert opts.status_code == 200
    assert len(opts.json()["excludeCredentials"]) == 1
    r = client.post("/api/auth/register/verify", json={"credential": k2.create(opts.json())})
    assert r.status_code == 200, r.text
    assert len(client.get("/api/auth/passkeys").json()) == 2


def test_login_with_registered_passkey(client):
    key = SoftPasskey("localhost", "http://localhost:5173")
    register(client, key)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["operator"] is None
    opts = client.post("/api/auth/login/options")
    assert opts.status_code == 200
    r = client.post("/api/auth/login/verify", json={"credential": key.get(opts.json())})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me").json()["operator"]["handle"] == "ruddick"


def test_login_rejects_unknown_passkey_and_replayed_challenge(client):
    key = SoftPasskey("localhost", "http://localhost:5173")
    register(client, key)
    client.post("/api/auth/logout")
    stranger = SoftPasskey("localhost", "http://localhost:5173")
    opts = client.post("/api/auth/login/options").json()
    assert client.post("/api/auth/login/verify", json={"credential": stranger.get(opts)}).status_code == 401
    # The challenge cookie was consumed by the failed attempt.
    assert client.post("/api/auth/login/verify", json={"credential": key.get(opts)}).status_code == 400


def test_login_rejects_wrong_origin(client):
    key = SoftPasskey("localhost", "http://evil.example")
    opts = client.post("/api/auth/register/options", json={"handle": "a", "display_name": "a"}).json()
    r = client.post("/api/auth/register/verify", json={"credential": key.create(opts)})
    assert r.status_code == 400


def test_tampered_session_cookie_is_anonymous(client, admin):
    assert client.get("/api/auth/me").json()["operator"]["handle"] == "ruddick"
    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/api/auth/me").json()["operator"] is None
