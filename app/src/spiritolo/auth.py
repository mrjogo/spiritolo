"""Passkey (WebAuthn) login and the signed session cookie.

No email, no magic link. An operator registers a passkey; the browser proves
possession of it on each login; the server then sets an HttpOnly cookie
holding a signed ``{operator_id}`` with a timestamp (``itsdangerous``), so
there is no server-side session table. The WebAuthn challenge rides in a
second short-lived signed cookie between the ``options`` and ``verify`` calls.

Bootstrap: while the ``operators`` table is empty, registration is open to
anyone who can reach the app — the first passkey becomes the (admin)
operator. After that only a signed-in operator can add further passkeys to
their own account.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from common.db import SQL_NOW, Connection, jdump, jload

from .settings import Settings

SESSION_COOKIE = "spiritolo_session"
CHALLENGE_COOKIE = "spiritolo_challenge"
CHALLENGE_MAX_AGE = 300


@dataclass(frozen=True)
class Operator:
    id: int
    handle: str
    display_name: str
    is_admin: bool

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "handle": self.handle,
                "display_name": self.display_name, "is_admin": self.is_admin}


class Sessions:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._session = URLSafeTimedSerializer(settings.session_secret, salt="session")
        self._challenge = URLSafeTimedSerializer(settings.session_secret, salt="challenge")

    # -- session cookie -----------------------------------------------------

    def operator_id(self, request: Request) -> int | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        try:
            data = self._session.loads(token, max_age=self._s.session_max_age)
        except (BadSignature, SignatureExpired):
            return None
        return int(data["op"]) if isinstance(data, dict) and "op" in data else None

    def token(self, operator_id: int) -> str:
        """A signed session token for ``operator_id`` (the cookie value)."""
        return self._session.dumps({"op": operator_id})

    def set_session(self, response: Response, operator_id: int) -> None:
        response.set_cookie(
            SESSION_COOKIE, self.token(operator_id),
            max_age=self._s.session_max_age, httponly=True, samesite="lax",
            secure=self._s.secure_cookies, path="/",
        )

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/")

    # -- challenge cookie ---------------------------------------------------

    def set_challenge(self, response: Response, purpose: str, challenge: bytes,
                      extra: dict[str, Any] | None = None) -> None:
        payload = {"p": purpose, "c": bytes_to_base64url(challenge), **(extra or {})}
        response.set_cookie(
            CHALLENGE_COOKIE, self._challenge.dumps(payload), max_age=CHALLENGE_MAX_AGE,
            httponly=True, samesite="lax", secure=self._s.secure_cookies, path="/api/auth",
        )

    def clear_challenge(self, response: Response) -> None:
        response.delete_cookie(CHALLENGE_COOKIE, path="/api/auth")

    def pop_challenge(self, request: Request, purpose: str) -> dict[str, Any]:
        """Read + validate the pending challenge. The caller clears the cookie
        on *every* response (``clear_challenge``) so a challenge is single-use."""
        token = request.cookies.get(CHALLENGE_COOKIE)
        if not token:
            raise HTTPException(400, "no pending challenge")
        try:
            data = self._challenge.loads(token, max_age=CHALLENGE_MAX_AGE)
        except SignatureExpired:
            raise HTTPException(400, "challenge expired") from None
        except BadSignature:
            raise HTTPException(400, "bad challenge") from None
        if data.get("p") != purpose:
            raise HTTPException(400, "challenge mismatch")
        data["challenge"] = base64url_to_bytes(data["c"])
        return data


# ----------------------------------------------------------------- operators

def load_operator(conn: Connection, operator_id: int) -> Operator | None:
    row = conn.execute(
        "select id, handle, display_name, is_admin from operators where id = ?", (operator_id,)
    ).fetchone()
    if row is None:
        return None
    return Operator(row["id"], row["handle"], row["display_name"], bool(row["is_admin"]))


def operator_count(conn: Connection) -> int:
    return conn.execute("select count(*) from operators").fetchone()[0]


def _passkeys_for(conn: Connection, operator_id: int) -> list[PublicKeyCredentialDescriptor]:
    rows = conn.execute(
        "select credential_id, transports from passkeys where operator_id = ?", (operator_id,)
    ).fetchall()
    return [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["credential_id"]))
            for r in rows]


# -------------------------------------------------------------- registration

def registration_options(conn: Connection, settings: Settings, *, handle: str,
                         display_name: str, operator: Operator | None) -> tuple[str, bytes, dict[str, Any]]:
    """Options JSON for ``navigator.credentials.create`` plus the challenge
    and the context to carry to ``verify``. ``operator`` is the signed-in
    account adding a passkey; ``None`` is the bootstrap path."""
    if operator is None:
        if operator_count(conn) > 0:
            raise HTTPException(403, "registration is closed; sign in to add a passkey")
        handle = handle.strip()
        display_name = display_name.strip() or handle
        if not handle:
            raise HTTPException(400, "handle required")
        user_id = secrets.token_bytes(16)
        exclude: list[PublicKeyCredentialDescriptor] = []
        ctx: dict[str, Any] = {"new": True, "handle": handle, "display_name": display_name,
                               "uid": bytes_to_base64url(user_id)}
    else:
        handle, display_name = operator.handle, operator.display_name
        user_id = operator.id.to_bytes(8, "big")
        exclude = _passkeys_for(conn, operator.id)
        ctx = {"new": False, "op": operator.id}
    opts = generate_registration_options(
        rp_id=settings.rp_id, rp_name=settings.rp_name, user_id=user_id,
        user_name=handle, user_display_name=display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude or None,
    )
    return options_to_json(opts), opts.challenge, ctx


def complete_registration(conn: Connection, settings: Settings, *, credential: dict[str, Any],
                          challenge: bytes, ctx: dict[str, Any], label: str | None) -> Operator:
    try:
        verified = verify_registration_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=settings.rp_id, expected_origin=settings.origins,
        )
    except Exception as exc:  # noqa: BLE001 - the library raises many types
        raise HTTPException(400, f"passkey registration failed: {exc}") from None
    transports = (credential.get("response") or {}).get("transports") or []
    with conn.transaction():
        if ctx.get("new"):
            if operator_count(conn) > 0:
                raise HTTPException(403, "registration is closed")
            op_id = conn.execute(
                "insert into operators (handle, display_name, is_admin) values (?, ?, 1) returning id",
                (ctx["handle"], ctx["display_name"]),
            ).fetchone()[0]
        else:
            op_id = int(ctx["op"])
        conn.execute(
            "insert into passkeys (credential_id, operator_id, public_key, sign_count, transports, aaguid, label) "
            "values (?, ?, ?, ?, ?, ?, ?)",
            (bytes_to_base64url(verified.credential_id), op_id, verified.credential_public_key,
             verified.sign_count, jdump(list(transports)), str(verified.aaguid), label),
        )
        conn.execute(f"update operators set last_login_at = {SQL_NOW} where id = ?", (op_id,))
    op = load_operator(conn, op_id)
    assert op is not None
    return op


# ---------------------------------------------------------------------- login

def authentication_options(settings: Settings) -> tuple[str, bytes]:
    opts = generate_authentication_options(
        rp_id=settings.rp_id, user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json(opts), opts.challenge


def complete_authentication(conn: Connection, settings: Settings, *, credential: dict[str, Any],
                            challenge: bytes) -> Operator:
    cred_id = credential.get("id") or credential.get("rawId")
    if not isinstance(cred_id, str):
        raise HTTPException(400, "credential id missing")
    row = conn.execute(
        "select credential_id, operator_id, public_key, sign_count from passkeys where credential_id = ?",
        (cred_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(401, "unknown passkey")
    try:
        verified = verify_authentication_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=settings.rp_id, expected_origin=settings.origins,
            credential_public_key=row["public_key"],
            credential_current_sign_count=row["sign_count"],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, f"passkey login failed: {exc}") from None
    with conn.transaction():
        conn.execute(
            f"update passkeys set sign_count = ?, last_used_at = {SQL_NOW} where credential_id = ?",
            (verified.new_sign_count, cred_id),
        )
        conn.execute(f"update operators set last_login_at = {SQL_NOW} where id = ?", (row["operator_id"],))
    op = load_operator(conn, row["operator_id"])
    if op is None:
        raise HTTPException(401, "operator missing")
    return op


def list_passkeys(conn: Connection, operator_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select credential_id, label, transports, created_at, last_used_at from passkeys "
        "where operator_id = ? order by created_at", (operator_id,)
    ).fetchall()
    return [{**r.asdict(), "transports": jload(r["transports"], [])} for r in rows]


def parse_credential(body: Any) -> dict[str, Any]:
    cred = body.get("credential") if isinstance(body, dict) else None
    if isinstance(cred, str):
        try:
            cred = json.loads(cred)
        except ValueError:
            raise HTTPException(400, "credential is not JSON") from None
    if not isinstance(cred, dict):
        raise HTTPException(400, "credential required")
    return cred
