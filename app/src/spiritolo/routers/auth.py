"""Passkey registration / login / logout and the ``me`` probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

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
