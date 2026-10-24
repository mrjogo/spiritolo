"""FastAPI dependencies: the per-thread connection, the signed-in operator,
and the admin gate."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from common.db import Connection

from .auth import Operator, Sessions, load_operator
from .db import Database, as_actor
from .executor import Executor
from .settings import Settings


@dataclass
class AppState:
    settings: Settings
    db: Database
    sessions: Sessions
    executor: Executor | None


def state(request: Request) -> AppState:
    return request.app.state.spiritolo


def conn(request: Request) -> Connection:
    """The request thread's connection, with the audit actor set to the
    caller (operator id when signed in) and the route as source."""
    st = state(request)
    c = st.db.connection()
    op_id = st.sessions.operator_id(request)
    as_actor(c, op_id, f"api:{request.url.path}")
    return c


def current_operator(request: Request, c: Connection = Depends(conn)) -> Operator | None:
    op_id = state(request).sessions.operator_id(request)
    if op_id is None:
        return None
    return load_operator(c, op_id)


def require_operator(op: Operator | None = Depends(current_operator)) -> Operator:
    if op is None:
        raise HTTPException(401, "sign in required")
    return op


def require_admin(op: Operator = Depends(require_operator)) -> Operator:
    if not op.is_admin:
        raise HTTPException(403, "admin required")
    return op
