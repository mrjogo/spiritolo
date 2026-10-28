"""Passkey registration / login / logout and the ``me`` probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from common.db import Connection

from .. import auth as A
from ..deps import AppState, conn, current_operator, state

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(c: Connection = Depends(conn), op: A.Operator | None = Depends(current_operator)) -> dict[str, Any]:
    return {"operator": op.public() if op else None,
            "setup_required": A.operator_count(c) == 0}


@router.post("/register/options")
def register_options(body: dict[str, Any], request: Request, c: Connection = Depends(conn),
                     op: A.Operator | None = Depends(current_operator)) -> Response:
    st: AppState = state(request)
    options_json, challenge, ctx = A.registration_options(
        c, st.settings, handle=str(body.get("handle") or ""),
        display_name=str(body.get("display_name") or ""), operator=op,
        invite=(str(body["invite"]) if body.get("invite") else None),
    )
    resp = Response(content=options_json, media_type="application/json")
    st.sessions.set_challenge(resp, "register", challenge, ctx)
    return resp


def _signed_in(st: AppState, op: A.Operator) -> Response:
    resp = JSONResponse({"operator": op.public()})
    st.sessions.set_session(resp, op.id)
    st.sessions.clear_challenge(resp)
    return resp


def _failed(st: AppState, exc: HTTPException) -> Response:
    # A failed verify still burns the challenge: the error response carries the
    # cookie deletion the exception path would otherwise drop.
    resp = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    st.sessions.clear_challenge(resp)
    return resp


@router.get("/invite/{token}")
def invite(token: str, c: Connection = Depends(conn)) -> dict[str, Any]:
    """Who a registration link is for, so the login page can say so before
    the passkey prompt. Unknown, used or expired links are 410."""
    inv = A.load_invite(c, token)
    if inv is None:
        raise HTTPException(410, "this registration link is no longer valid")
    return {"operator": inv["operator"], "expires_at": inv["expires_at"]}


@router.post("/register/verify")
def register_verify(body: dict[str, Any], request: Request, c: Connection = Depends(conn)) -> Response:
    st: AppState = state(request)
    try:
        ctx = st.sessions.pop_challenge(request, "register")
        op = A.complete_registration(
            c, st.settings, credential=A.parse_credential(body), challenge=ctx["challenge"],
            ctx=ctx, label=(body.get("label") or None),
        )
    except HTTPException as exc:
        return _failed(st, exc)
    return _signed_in(st, op)


@router.post("/login/options")
def login_options(request: Request) -> Response:
    st: AppState = state(request)
    options_json, challenge = A.authentication_options(st.settings)
    resp = Response(content=options_json, media_type="application/json")
    st.sessions.set_challenge(resp, "login", challenge)
    return resp


@router.post("/login/verify")
def login_verify(body: dict[str, Any], request: Request, c: Connection = Depends(conn)) -> Response:
    st: AppState = state(request)
    try:
        ctx = st.sessions.pop_challenge(request, "login")
        op = A.complete_authentication(c, st.settings, credential=A.parse_credential(body),
                                       challenge=ctx["challenge"])
    except HTTPException as exc:
        return _failed(st, exc)
    return _signed_in(st, op)


@router.get("/dev-login")
def dev_login(request: Request, c: Connection = Depends(conn)) -> Response:
    """Local previews only (``Settings.dev_login``): sign in as the first admin
    without a passkey — a preview runs on a copy of the live database, whose
    passkeys are bound to the live hostname — creating a ``preview`` admin when
    the copy has none. Everywhere else this route does not exist (404)."""
    st: AppState = state(request)
    if not st.settings.dev_login:
        raise HTTPException(404, "not found")
    row = c.execute(
        "select id from operators where is_admin order by id limit 1"
    ).fetchone()
    op_id = row[0] if row else c.execute(
        "insert into operators (handle, display_name, is_admin) "
        "values ('preview', 'Preview', 1) returning id"
    ).fetchone()[0]
    resp = RedirectResponse("/ops", status_code=303)
    st.sessions.set_session(resp, op_id)
    return resp


@router.post("/logout")
def logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True})
    state(request).sessions.clear_session(resp)
    return resp


@router.get("/passkeys")
def passkeys(c: Connection = Depends(conn), op: A.Operator | None = Depends(current_operator)) -> list[dict[str, Any]]:
    if op is None:
        return []
    return A.list_passkeys(c, op.id)


@router.delete("/passkeys/{credential_id}")
def delete_passkey(credential_id: str, c: Connection = Depends(conn),
                   op: A.Operator | None = Depends(current_operator)) -> dict[str, Any]:
    if op is None:
        raise HTTPException(401, "sign in first")
    A.delete_passkey(c, op.id, credential_id)
    return {"ok": True}
