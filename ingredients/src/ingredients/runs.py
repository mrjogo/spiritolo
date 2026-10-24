"""Run lifecycle: assemble a run in /ops, start it, follow it, retry it.

Port of the ``create_run`` / ``add_run_items`` / ``start_run`` / ... SQL
functions. A **run** is a ``jobs`` row (``draft → queued → running → done |
failed | cancelled``); its membership is the set of ``job_items`` it owns, one
per ``(job, entity)`` in state ``pending → {applied | flagged | failed}``. The
ops API calls these with the operator's connection (audit actor = ``human``);
the executor (``worker.runner``) picks up whatever ``start_run`` queues.

Every function raises :class:`RunError` for the cases the SQL raised (missing
run, wrong state) so the API layer can map them to 404 / 409.
"""

from __future__ import annotations

from typing import Any, Iterable

from common.db import SQL_NOW, Connection, jdump, jlist, jload

# Entity kind each stage's run operates on.
STAGE_ENTITY = {
    "extract-recipe": "page",
    "combine-nodes": "taxonomy_node",
    "connect-nodes": "taxonomy_node",
}
RECIPE_CONTENT_TYPES = ("likely_drink_recipe", "confirmed_drink")
TERMINAL_ITEM_STATES = ("applied", "flagged", "failed")


class RunError(ValueError):
    """A run operation was refused; ``code`` is ``not_found`` or ``conflict``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def entity_type_for(stage: str) -> str:
    return STAGE_ENTITY.get(stage, "recipe")


# --------------------------------------------------------------------- pricing

def estimate_cents(provider: str | None, model: str | None, items: int | None) -> int:
    """Rough per-item cost: (1200 input + 200 output tokens) at list price.
    Local ``ollama`` (and no provider) is free."""
    n = items or 0
    per_item = {
        "deepseek": (1200 * 0.14 + 200 * 0.28) / 10000.0,
        "openai": (1200 * 0.75 + 200 * 4.50) / 10000.0,
        "anthropic": (1200 * 1.00 + 200 * 5.00) / 10000.0,
        "claude": (1200 * 1.00 + 200 * 5.00) / 10000.0,
    }.get(provider or "", 0.0)
    return int(round(n * per_item))


# ------------------------------------------------------------- run assembly

def _job(conn: Connection, job_id: int) -> dict[str, Any]:
    row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
    if row is None:
        raise RunError("not_found", f"run {job_id} not found")
    job = row.asdict()
    job["payload"] = jload(job.get("payload"), {}) or {}
    job["progress"] = jload(job.get("progress"), {}) or {}
    return job


def get_run(conn: Connection, job_id: int) -> dict[str, Any]:
    """The run row as a dict (payload/progress parsed)."""
    return _job(conn, job_id)


def create_run(conn: Connection, stage: str, *, created_by: str | None = None) -> int:
    """A new ``draft`` run for ``stage``; returns its id."""
    return conn.execute(
        "insert into jobs (stage, kind, state, created_by) values (?, 'run', 'draft', ?) returning id",
        (stage, created_by),
    ).fetchone()[0]


def set_run_llm(conn: Connection, job_id: int, provider: str | None, model: str | None) -> None:
    """Choose the run's LLM tier (``None`` = deterministic-only)."""
    _job(conn, job_id)
    conn.execute(
        "update jobs set llm_provider = ?, llm_model = ? where id = ?",
        (provider or None, model or None, job_id),
    )


_LATEST_STATUS_CTE = """
    latest as (
        select entity_id, state as status from (
            select i.entity_id, i.state,
                   row_number() over (partition by i.entity_id order by i.id desc) as rn
            from job_items i
            where i.stage = ? and i.state in ('applied', 'flagged', 'failed')
        ) where rn = 1
    )
"""


def add_run_items(conn: Connection, job_id: int, entity_type: str, entity_ids: Iterable[int]) -> int:
    """Add ``entity_ids`` as ``pending`` members (deduped against existing
    membership), recording each one's current status as ``why_added``.

    (The CTE sits after ``insert into`` on purpose: Python's ``sqlite3`` only
    reports ``rowcount`` for statements that *start* with a DML keyword.)"""
    job = _job(conn, job_id)
    ids = [int(i) for i in entity_ids]
    if not ids:
        return 0
    cur = conn.execute(
        f"""
        insert into job_items (entity_type, entity_id, stage, code_version, outcome, method,
                               state, job_id, outcome_payload)
        with {_LATEST_STATUS_CTE}
        select ?, e.value, ?, '', 'pending', 'deterministic', 'pending', ?,
               json_object('why_added', coalesce(l.status, 'never_run'))
        from json_each(?) e
        left join latest l on l.entity_id = e.value
        where not exists (
            select 1 from job_items m
            where m.job_id = ? and m.entity_id = e.value and m.stage = ?
        )
        """,
        (job["stage"], entity_type, job["stage"], job_id, jlist(ids), job_id, job["stage"]),
    )
    return cur.rowcount


def add_run_items_by_filter(conn: Connection, job_id: int, filt: dict[str, Any] | None) -> int:
    """Add every entity matching the eligible-pool ``filt`` as a member."""
    job = _job(conn, job_id)
    stage = job["stage"]
    sql, params = _eligible_base_sql(stage, filt or {})
    cur = conn.execute(
        f"""
        insert into job_items (entity_type, entity_id, stage, code_version, outcome, method,
                               state, job_id, outcome_payload)
        with b as ({sql})
        select ?, b.entity_id, ?, '', 'pending', 'deterministic', 'pending', ?,
               json_object('why_added', b.status)
        from b
        where not exists (
            select 1 from job_items m
            where m.job_id = ? and m.entity_id = b.entity_id and m.stage = ?
        )
        """,
        (*params, entity_type_for(stage), stage, job_id, job_id, stage),
    )
    return cur.rowcount


def remove_run_items(conn: Connection, job_id: int, item_ids: Iterable[int]) -> int:
    """Drop members from a ``draft`` run (by ``job_items.id``)."""
    job = _job(conn, job_id)
    if job["state"] != "draft":
        raise RunError("conflict", f"run {job_id} is not a draft; cannot remove items")
    ids = [int(i) for i in item_ids]
    if not ids:
        return 0
    cur = conn.execute(
        "delete from job_items where job_id = ? and id in (select value from json_each(?))",
        (job_id, jlist(ids)),
    )
    return cur.rowcount


def start_run(conn: Connection, job_id: int, max_cost_cents: int | None = None) -> None:
    """``draft → queued``: stamp the cost cap + estimate; the executor takes it
    from here."""
    job = _job(conn, job_id)
    if job["state"] != "draft":
        raise RunError("conflict", f"run {job_id} is not a draft (state={job['state']})")
    pending = conn.execute(
        "select count(*) from job_items where job_id = ? and state = 'pending'", (job_id,)
    ).fetchone()[0]
    conn.execute(
        "update jobs set state = 'queued', max_cost_cents = ?, cost_estimate_cents = ? where id = ?",
        (max_cost_cents, estimate_cents(job.get("llm_provider"), job.get("llm_model"), pending), job_id),
    )


def cancel_run(conn: Connection, job_id: int) -> str:
    """Cancel: a ``draft``/``queued`` run goes straight to ``cancelled``; a
    ``running`` one is asked to stop (``cancelling``) and the executor finalizes
    it. Returns the resulting state."""
    job = _job(conn, job_id)
    state = job["state"]
    if state in ("draft", "queued"):
        conn.execute(
            f"update jobs set state = 'cancelled', finished_at = {SQL_NOW} where id = ?", (job_id,)
        )
        return "cancelled"
    if state == "running":
        conn.execute("update jobs set state = 'cancelling' where id = ?", (job_id,))
        return "cancelling"
    return state


def retry_run(conn: Connection, job_id: int) -> None:
    """Requeue a finished run: its ``failed`` items go back to ``pending``
    (applied/flagged ones stay as they are) and the job is queued again."""
    job = _job(conn, job_id)
    if job["state"] not in ("failed", "cancelled", "done"):
        raise RunError("conflict", f"run {job_id} is not finished (state={job['state']})")
    conn.execute(
        "update job_items set state = 'pending' where job_id = ? and state = 'failed'", (job_id,)
    )
    conn.execute(
        "update jobs set state = 'queued', error_code = null, error_detail = null, "
        "cost_actual_cents = null, started_at = null, finished_at = null, worker_id = null "
        "where id = ?",
        (job_id,),
    )


def delete_run(conn: Connection, job_id: int) -> None:
    """Delete a ``draft`` run and its membership."""
    job = _job(conn, job_id)
    if job["state"] != "draft":
        raise RunError("conflict", f"run {job_id} is not a draft; cannot delete")
    conn.execute("delete from job_items where job_id = ?", (job_id,))
    conn.execute("delete from jobs where id = ?", (job_id,))


# ------------------------------------------------------------- eligible pool

def _eligible_base_sql(stage: str, filt: dict[str, Any]) -> tuple[str, list[Any]]:
    """The eligible-entity universe for ``stage`` joined with each entity's
    latest terminal status, filtered by ``filt`` (status / source /
    code_version_before / search). Columns: entity_id, title, source, status,
    code_version, last_run."""
    params: list[Any] = []
    if stage == "extract-recipe":
        universe = (
            "select p.id as entity_id, p.url as title, p.site as source from pages p "
            "where p.content_type in (select value from json_each(?)) and p.corpus_key is not null"
        )
        params.append(jlist(RECIPE_CONTENT_TYPES))
    elif stage in ("combine-nodes", "connect-nodes"):
        universe = "select n.id as entity_id, n.display_name as title, n.status as source from taxonomy_nodes n"
    else:
        universe = (
            "select r.id as entity_id, coalesce(nullif(trim(r.title), ''), r.source_url) as title, "
            "r.site as source from recipes r"
        )
    params.append(stage)
    sql = f"""
        select j.entity_id, j.title, j.source, j.status, j.code_version, j.last_run
        from (
            select u.entity_id, u.title, u.source,
                   coalesce(l.state, 'never_run') as status,
                   coalesce(l.code_version, '') as code_version,
                   coalesce(l.finished_at, l.started_at) as last_run
            from ({universe}) u
            -- Latest terminal item per entity as a correlated lookup on
            -- job_items_latest_idx (stage, entity_id, id desc). A window-function
            -- subquery here gets materialized and then rescanned once per
            -- entity under GROUP BY (the facet counts), which is quadratic.
            left join job_items l on l.id = (
                select i.id from job_items i
                where i.stage = ? and i.entity_id = u.entity_id
                  and i.state in ('applied', 'flagged', 'failed')
                order by i.id desc limit 1
            )
        ) j
        where 1 = 1
    """
    sql, params = _apply_filters(sql, params, filt, status_col="j.status", source_col="j.source",
                                 version_col="j.code_version", title_col="j.title")
    return sql, params


def _apply_filters(sql: str, params: list[Any], filt: dict[str, Any], *,
                   status_col: str, source_col: str, version_col: str, title_col: str) -> tuple[str, list[Any]]:
    status = filt.get("status")
    if status:
        sql += f" and {status_col} in (select value from json_each(?))"
        params.append(jlist(status if isinstance(status, list) else [status]))
    source = filt.get("source")
    if source:
        sql += f" and {source_col} in (select value from json_each(?))"
        params.append(jlist(source if isinstance(source, list) else [source]))
    if filt.get("code_version_before"):
        sql += f" and {version_col} < ?"
        params.append(filt["code_version_before"])
    if filt.get("search"):
        sql += f" and {title_col} like ? escape '\\'"
        params.append("%" + _like_escape(filt["search"]) + "%")
    return sql, params


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sort_clause(sort: str | None, allowed: Iterable[str], default_col: str, alias: str) -> str:
    """``"title:asc,source"`` → ``b.title asc, b.source desc, b.entity_id asc``.
    Unknown columns are skipped; nothing valid falls back to ``default_col``."""
    allowed = set(allowed)
    parts: list[str] = []
    for token in (sort or default_col).split(","):
        token = token.strip()
        if not token:
            continue
        col, _, direction = token.partition(":")
        col = col.lower(); direction = direction.lower()
        if not direction:
            if col.endswith("_asc"):
                col, direction = col[:-4], "asc"
            elif col.endswith("_desc"):
                col, direction = col[:-5], "desc"
            else:
                direction = "desc"
        if col == "status" and "task_state" in allowed:
            col = "task_state"
        if col not in allowed:
            continue
        if direction not in ("asc", "desc"):
            direction = "desc"
        clause = f"{alias}.{col} {direction}"
        if col == "last_run":
            clause += " nulls first" if direction == "asc" else " nulls last"
        parts.append(clause)
    if not parts:
        parts = [f"{alias}.{default_col} desc"]
    parts.append(f"{alias}.entity_id asc")
    return ", ".join(parts)


def eligible_pool(conn: Connection, stage: str, filt: dict[str, Any] | None, sort: str | None,
                  limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """One page of the add-tasks picker: ``{rows, total}`` where each row is
    ``{entity_id, title, source, status, status_detail, last_run_label}``."""
    base, params = _eligible_base_sql(stage, filt or {})
    order = _sort_clause(sort, ["title", "source", "status", "last_run", "code_version", "entity_id"],
                         "last_run", "b")
    rows = conn.execute(
        f"select b.entity_id, b.title, b.source, b.status, b.last_run, count(*) over () as total "
        f"from ({base}) b order by {order} limit ? offset ?",
        (*params, limit, offset),
    ).fetchall()
    total = rows[0]["total"] if rows else conn.execute(f"select count(*) from ({base})", params).fetchone()[0]
    return {
        "rows": [
            {
                "entity_id": str(r["entity_id"]), "title": r["title"], "source": r["source"],
                "status": r["status"], "status_detail": None,
                "last_run_label": r["last_run"][:10] if r["last_run"] else None,
            }
            for r in rows
        ],
        "total": total,
    }


def _facets(conn: Connection, base_fn, key_cols: dict[str, str], filt: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for facet, col in key_cols.items():
        f = {k: v for k, v in filt.items() if k != facet}
        base, params = base_fn(f)
        rows = conn.execute(
            f"select b.{col} as k, count(*) as c from ({base}) b group by b.{col}", params
        ).fetchall()
        out[facet] = {r["k"]: r["c"] for r in rows if r["k"] is not None}
    return out


def eligible_pool_facets(conn: Connection, stage: str, filt: dict[str, Any] | None) -> dict[str, Any]:
    """``{status: {value: count}, source: {value: count}}`` for the picker's
    facet chips (each facet computed with its own filter removed)."""
    return _facets(conn, lambda f: _eligible_base_sql(stage, f),
                   {"status": "status", "source": "source"}, filt or {})


# ----------------------------------------------------------------- run items

def _run_items_base_sql(job_id: int, filt: dict[str, Any]) -> tuple[str, list[Any]]:
    params: list[Any] = [job_id]
    sql = """
        select j.item_id, j.entity_id, j.title, j.source, j.why_added, j.task_state, j.code_version
        from (
            select i.id as item_id, i.entity_id,
                   coalesce(nullif(trim(r.title), ''), r.source_url, pg.url, n.display_name) as title,
                   coalesce(r.site, pg.site, n.status) as source,
                   coalesce(
                     case when i.outcome_payload ->> '$.why_added' = 'failed' then 'retry_failed'
                          else i.outcome_payload ->> '$.why_added' end,
                     'never_run') as why_added,
                   i.state as task_state,
                   i.code_version
            from job_items i
            left join recipes r on i.entity_type = 'recipe' and r.id = i.entity_id
            left join pages pg on i.entity_type = 'page' and pg.id = i.entity_id
            left join taxonomy_nodes n on i.entity_type = 'taxonomy_node' and n.id = i.entity_id
            where i.job_id = ?
        ) j
        where 1 = 1
    """
    return _apply_filters(sql, params, filt, status_col="j.task_state", source_col="j.source",
                          version_col="j.code_version", title_col="j.title")


def run_items(conn: Connection, job_id: int, filt: dict[str, Any] | None, sort: str | None,
              limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """One page of a run's members: ``{rows, total}`` with rows of
    ``{item_id, entity_id, title, source, why_added, task_state}``."""
    base, params = _run_items_base_sql(job_id, filt or {})
    order = _sort_clause(sort, ["title", "source", "task_state", "why_added", "entity_id", "item_id"],
                         "item_id", "b")
    rows = conn.execute(
        f"select b.*, count(*) over () as total from ({base}) b order by {order} limit ? offset ?",
        (*params, limit, offset),
    ).fetchall()
    total = rows[0]["total"] if rows else conn.execute(f"select count(*) from ({base})", params).fetchone()[0]
    return {
        "rows": [
            {
                "item_id": str(r["item_id"]), "entity_id": str(r["entity_id"]), "title": r["title"],
                "source": r["source"], "why_added": r["why_added"], "task_state": r["task_state"],
            }
            for r in rows
        ],
        "total": total,
    }


def run_items_facets(conn: Connection, job_id: int, filt: dict[str, Any] | None) -> dict[str, Any]:
    return _facets(conn, lambda f: _run_items_base_sql(job_id, f),
                   {"status": "task_state", "source": "source"}, filt or {})
