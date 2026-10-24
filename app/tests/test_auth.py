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


# ------------------------------------------------------------- invites

def test_admin_creates_operator_and_registration_link(client, admin):
    r = client.post("/api/ops/operators", json={"handle": "dana", "display_name": "Dana", "is_admin": False})
    assert r.status_code == 200, r.text
    dana = r.json()
    assert dana["is_admin"] is False
    assert client.post("/api/ops/operators", json={"handle": "dana"}).status_code == 409

    inv = client.post(f"/api/ops/operators/{dana['id']}/invites")
    assert inv.status_code == 200, inv.text
    token = inv.json()["token"]
    assert inv.json()["path"] == f"/login?invite={token}"
    listed = {o["handle"]: o for o in client.get("/api/ops/operators").json()}
    assert listed["dana"]["passkeys"] == 0 and listed["dana"]["pending_invites"] == 1

    # A stranger with the link, no session, on this (or any other) origin.
    client.cookies.clear()
    who = client.get(f"/api/auth/invite/{token}")
    assert who.status_code == 200 and who.json()["operator"]["handle"] == "dana"
    key = SoftPasskey("localhost", "http://localhost:5173")
    opts = client.post("/api/auth/register/options", json={"invite": token})
    assert opts.status_code == 200, opts.text
    r = client.post("/api/auth/register/verify", json={"credential": key.create(opts.json()), "label": "new laptop"})
    assert r.status_code == 200, r.text
    assert r.json()["operator"]["handle"] == "dana"
    assert client.get("/api/auth/me").json()["operator"]["handle"] == "dana"

    # Single use: the link is dead now, for the probe and for the ceremony.
    client.cookies.clear()
    assert client.get(f"/api/auth/invite/{token}").status_code == 410
    assert client.post("/api/auth/register/options", json={"invite": token}).status_code == 410


def test_invite_lets_an_existing_operator_reregister_without_a_session(client, admin):
    inv = client.post(f"/api/ops/operators/{admin}/invites").json()
    client.cookies.clear()
    key = SoftPasskey("localhost", "http://localhost:5173")
    opts = client.post("/api/auth/register/options", json={"invite": inv["token"]})
    assert opts.status_code == 200
    r = client.post("/api/auth/register/verify", json={"credential": key.create(opts.json())})
    assert r.status_code == 200, r.text
    assert r.json()["operator"]["handle"] == "ruddick"
    assert len(client.get("/api/auth/passkeys").json()) == 1


def test_invites_are_admin_only_and_revocable(client, admin, db):
    from conftest import make_operator
    guest = make_operator(db, "guest", is_admin=False)
    assert client.post(f"/api/ops/operators/{guest}/invites").status_code == 200
    assert client.post(f"/api/ops/operators/{guest}/invites").status_code == 200
    assert client.delete(f"/api/ops/operators/{guest}/invites").json() == {"revoked": 2}
    assert client.post("/api/ops/operators/999/invites").status_code == 404
    client.cookies.clear()
    assert client.post(f"/api/ops/operators/{guest}/invites").status_code == 401
    assert client.get("/api/auth/invite/not-a-token").status_code == 410


def test_expired_invite_is_rejected(client, admin, db):
    inv = client.post(f"/api/ops/operators/{admin}/invites").json()
    db.execute("update operator_invites set expires_at = '2000-01-01T00:00:00.000Z'")
    client.cookies.clear()
    assert client.get(f"/api/auth/invite/{inv['token']}").status_code == 410
    assert client.post("/api/auth/register/options", json={"invite": inv["token"]}).status_code == 410


def test_operator_removes_an_old_passkey_but_never_the_last(client):
    k1 = SoftPasskey("localhost", "http://localhost:5173")
    register(client, k1)
    only = client.get("/api/auth/passkeys").json()[0]["credential_id"]
    assert client.delete(f"/api/auth/passkeys/{only}").status_code == 409

    k2 = SoftPasskey("localhost", "http://localhost:5173")
    opts = client.post("/api/auth/register/options", json={})
    assert client.post("/api/auth/register/verify", json={"credential": k2.create(opts.json())}).status_code == 200
    assert client.delete("/api/auth/passkeys/nope").status_code == 404
    assert client.delete(f"/api/auth/passkeys/{only}").status_code == 200
    left = client.get("/api/auth/passkeys").json()
    assert len(left) == 1 and left[0]["credential_id"] != only

    # The removed key can no longer sign in; the remaining one can.
    client.post("/api/auth/logout")
    assert client.delete(f"/api/auth/passkeys/{left[0]['credential_id']}").status_code == 401
    opts = client.post("/api/auth/login/options").json()
    assert client.post("/api/auth/login/verify", json={"credential": k1.get(opts)}).status_code == 401
    opts = client.post("/api/auth/login/options").json()
    assert client.post("/api/auth/login/verify", json={"credential": k2.get(opts)}).status_code == 200


def test_cannot_remove_another_operators_passkey(app, client, db):
    key = SoftPasskey("localhost", "http://localhost:5173")
    register(client, key)
    theirs = client.get("/api/auth/passkeys").json()[0]["credential_id"]
    client.post("/api/auth/logout")
    from conftest import make_operator
    other = make_operator(db, "dana", is_admin=False)
    db.execute("insert into passkeys (credential_id, operator_id, public_key) values ('k2', ?, x'00')", (other,))
    db.execute("insert into passkeys (credential_id, operator_id, public_key) values ('k3', ?, x'00')", (other,))
    client.cookies.set(SESSION_COOKIE, app.state.spiritolo.sessions.token(other))
    assert client.delete(f"/api/auth/passkeys/{theirs}").status_code == 404
