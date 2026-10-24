"""The operator API behind ``/ops``: generic reads, runs, reviews, taxonomy
curation, executor health. Every route requires an admin session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from common.db import Connection, IntegrityError

from ingredients import runs as R
from ingredients.reviews import ops as reviews
from ingredients.taxonomy import curate
from ingredients.taxonomy.ops import TaxonomyError

from .. import importdb
from ..auth import Operator
from ..deps import AppState, conn, require_admin, state
from ..query import columns, decode_row, run_query

router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(require_admin)])


def _run_error(exc: R.RunError) -> HTTPException:
    return HTTPException(404 if exc.code == "not_found" else 409, str(exc))


# ------------------------------------------------------------------ reads

@router.post("/query")
def query(spec: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    return run_query(c, spec)


# ------------------------------------------------------------------- runs

@router.post("/runs")
def create_run(body: dict[str, Any], c: Connection = Depends(conn), op: Operator = Depends(require_admin)) -> dict[str, Any]:
    stage = body.get("stage")
    if not isinstance(stage, str) or not stage:
        raise HTTPException(400, "stage required")
    return {"id": R.create_run(c, stage, created_by=op.handle)}


@router.get("/runs/{job_id}")
def get_run(job_id: int, c: Connection = Depends(conn)) -> dict[str, Any]:
    row = c.execute("select * from runs where id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "run not found")
    return decode_row(row, columns(c, "runs"))


@router.post("/runs/{job_id}/llm")
def set_llm(job_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        R.set_run_llm(c, job_id, body.get("provider"), body.get("model"))
    except R.RunError as exc:
        raise _run_error(exc) from None
    return {"ok": True}


@router.post("/runs/{job_id}/items")
def add_items(job_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    ids = body.get("entity_ids") or []
    try:
        if body.get("filter") is not None and not ids:
            n = R.add_run_items_by_filter(c, job_id, body["filter"])
        else:
            n = R.add_run_items(c, job_id, body.get("entity_type") or "recipe", [int(i) for i in ids])
    except R.RunError as exc:
        raise _run_error(exc) from None
    return {"added": n}


@router.post("/runs/{job_id}/items/remove")
def remove_items(job_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        n = R.remove_run_items(c, job_id, [int(i) for i in body.get("item_ids") or []])
    except R.RunError as exc:
        raise _run_error(exc) from None
    return {"removed": n}


@router.post("/runs/{job_id}/items/query")
def items(job_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    return R.run_items(c, job_id, body.get("filter"), body.get("sort"),
                       limit=int(body.get("limit") or 50), offset=int(body.get("offset") or 0))


@router.post("/runs/{job_id}/items/facets")
def items_facets(job_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    return R.run_items_facets(c, job_id, body.get("filter"))


@router.post("/runs/{job_id}/start")
def start(job_id: int, body: dict[str, Any], request: Request, c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        R.start_run(c, job_id, body.get("max_cost_cents"))
    except R.RunError as exc:
        raise _run_error(exc) from None
    st: AppState = state(request)
    if st.executor is not None:
        st.executor.wake()
    return {"ok": True}


@router.post("/runs/{job_id}/cancel")
def cancel(job_id: int, request: Request, c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        new_state = R.cancel_run(c, job_id)
    except R.RunError as exc:
        raise _run_error(exc) from None
    st: AppState = state(request)
    if st.executor is not None:
        st.executor.cancel(job_id)
    return {"state": new_state}


@router.post("/runs/{job_id}/retry")
def retry(job_id: int, request: Request, c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        R.retry_run(c, job_id)
    except R.RunError as exc:
        raise _run_error(exc) from None
    st: AppState = state(request)
    if st.executor is not None:
        st.executor.wake()
    return {"ok": True}


@router.delete("/runs/{job_id}")
def delete(job_id: int, c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        R.delete_run(c, job_id)
    except R.RunError as exc:
        raise _run_error(exc) from None
    return {"ok": True}


@router.post("/eligible-pool")
def eligible_pool(body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    stage = body.get("stage")
    if not isinstance(stage, str):
        raise HTTPException(400, "stage required")
    return R.eligible_pool(c, stage, body.get("filter"), body.get("sort"),
                           limit=int(body.get("limit") or 50), offset=int(body.get("offset") or 0))


@router.post("/eligible-pool/facets")
def eligible_pool_facets(body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    stage = body.get("stage")
    if not isinstance(stage, str):
        raise HTTPException(400, "stage required")
    return R.eligible_pool_facets(c, stage, body.get("filter"))


@router.get("/estimate")
def estimate(provider: str | None = None, model: str | None = None, items: int = 0) -> dict[str, Any]:
    return {"cents": R.estimate_cents(provider, model, items)}


# ---------------------------------------------------------------- reviews

@router.post("/reviews/flag")
def flag(body: dict[str, Any], c: Connection = Depends(conn), op: Operator = Depends(require_admin)) -> dict[str, Any]:
    for k in ("entity_kind", "entity_id", "stage"):
        if not body.get(k):
            raise HTTPException(400, f"{k} required")
    rid = reviews.flag_review(c, entity_kind=str(body["entity_kind"]), entity_id=str(body["entity_id"]),
                              stage=str(body["stage"]), note=body.get("note"), created_by=op.handle)
    return {"id": rid}


@router.post("/reviews/{review_id}/resolve")
def resolve(review_id: int, body: dict[str, Any], c: Connection = Depends(conn),
            op: Operator = Depends(require_admin)) -> dict[str, Any]:
    _review_exists(c, review_id)
    try:
        reviews.resolve_review(c, review_id, payload=body.get("payload"), reviewed_by=op.handle)
    except (TaxonomyError, IntegrityError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True}


@router.post("/reviews/{review_id}/dismiss")
def dismiss(review_id: int, c: Connection = Depends(conn), op: Operator = Depends(require_admin)) -> dict[str, Any]:
    _review_exists(c, review_id)
    reviews.resolve_review(c, review_id, dismiss=True, reviewed_by=op.handle)
    return {"ok": True}


def _review_exists(c: Connection, review_id: int) -> None:
    if c.execute("select 1 from human_reviews where id = ?", (review_id,)).fetchone() is None:
        raise HTTPException(404, "review not found")


# --------------------------------------------------------------- taxonomy

@router.post("/taxonomy/nodes")
def create_node(body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        nid = curate.create_node(
            c, slug=str(body.get("slug") or ""), display_name=str(body.get("display_name") or ""),
            parent_id=body.get("parent_id"), node_kind=body.get("node_kind"),
            default_role=body.get("default_role"), is_cluster_node=bool(body.get("is_cluster_node")),
            is_defining_garnish=bool(body.get("is_defining_garnish")), aliases=body.get("aliases") or (),
        )
    except (TaxonomyError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from None
    return {"id": nid}


@router.patch("/taxonomy/nodes/{node_id}")
def update_node(node_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        curate.update_node(c, node_id, body.get("patch") if "patch" in body else body)
    except (TaxonomyError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True}


@router.put("/taxonomy/nodes/{node_id}/parents")
def set_parents(node_id: int, body: dict[str, Any], c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        curate.set_parents(c, node_id, body.get("parent_ids"))
    except (TaxonomyError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True}


@router.get("/taxonomy/nodes/{node_id}/blockers")
def node_blockers(node_id: int, c: Connection = Depends(conn)) -> dict[str, Any]:
    if c.execute("select 1 from taxonomy_nodes where id = ?", (node_id,)).fetchone() is None:
        raise HTTPException(404, "node not found")
    return curate.blockers(c, node_id)


@router.delete("/taxonomy/nodes/{node_id}")
def delete_node(node_id: int, c: Connection = Depends(conn)) -> dict[str, Any]:
    try:
        curate.delete_node(c, node_id)
    except (TaxonomyError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True}


# --------------------------------------------------------------- executor

@router.get("/executor")
def executor_health(request: Request) -> dict[str, Any]:
    st: AppState = state(request)
    if st.executor is None:
        return {"alive": False, "disabled": True}
    return st.executor.health()


# -------------------------------------------------------------- import-db
# Replace the live database with an uploaded SQLite file (the staging data
# migration). See spiritolo.importdb for the stage → apply protocol.

def _paths(st: AppState) -> importdb.Paths:
    return importdb.Paths(Path(st.settings.db_path))


@router.get("/import-db")
def import_status(request: Request) -> dict[str, Any]:
    st: AppState = state(request)
    return {"staged": importdb.staged_info(_paths(st)), "restart_on_apply": st.settings.import_restart}


@router.post("/import-db")
async def import_stage(request: Request) -> dict[str, Any]:
    st: AppState = state(request)
    expected = request.headers.get("x-content-sha256")
    if not expected:
        raise HTTPException(400, "X-Content-SHA256 header required")
    paths = _paths(st)
    try:
        importdb.check_digest_header(expected)
        # Stream the body straight to the .part file: the database is hundreds
        # of MB and must never be buffered in process memory.
        sink = importdb.open_partial(paths)
        try:
            async for chunk in request.stream():
                sink.write(chunk)
        except BaseException:
            sink.abort()
            raise
        info = await run_in_threadpool(importdb.finish_stage, paths, sink, expected)
    except importdb.ImportError_ as exc:
        raise HTTPException(422, str(exc)) from None
    return {"staged": info}


@router.delete("/import-db")
def import_discard(request: Request) -> dict[str, Any]:
    st: AppState = state(request)
    return {"discarded": importdb.discard(_paths(st))}


@router.post("/import-db/apply")
def import_apply(request: Request) -> dict[str, Any]:
    st: AppState = state(request)
    paths = _paths(st)
    if importdb.staged_info(paths) is None:
        raise HTTPException(409, "nothing staged")
    if st.settings.import_restart:
        # The entrypoint swaps the staged file in before Litestream and the
        # app start again; the response goes out before the exit.
        importdb.schedule_exit()
        return {"applied": False, "restarting": True}
    if st.executor is not None:
        st.executor.stop()
    st.db.close_all()
    try:
        importdb.swap_files(paths)
    except importdb.ImportError_ as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        st.db.reopen()
        if st.executor is not None:
            st.executor.start()
    return {"applied": True, "restarting": False}
