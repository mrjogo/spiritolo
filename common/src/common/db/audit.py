"""The audit log, written by per-connection triggers from an explicit actor.

Under Supabase the audit trigger had to *infer* who was writing (a JWT, a GUC,
or nothing). Here there is one write path, the application, so the actor is
explicit: every connection carries a one-row TEMP table ``audit_context`` whose
``actor_kind`` / ``actor_id`` / ``source`` the caller sets per unit of work
(``set_actor``). TEMP triggers on each audited table read that row and write
``audit_log`` with the same three shapes the Postgres version used:

- **INSERT**: the event only, no payload (derivable from the current row by
  reverse-applying later UPDATEs, newest → oldest).
- **UPDATE**: ``before`` / ``after`` narrowed to the ``changed_keys`` subset.
- **DELETE**: the whole pre-image in ``before``.

That diff shape is lossless only while a row's chain is unbroken, so do not add
retention or pruning to ``audit_log`` without reinstating full INSERT payloads.

The triggers are TEMP (per connection) because that is the only kind that may
reference a TEMP table, and because it lets a bulk load (the ETL, which copies
an audit log in) open a connection with no triggers at all. Column lists are
generated from ``pragma table_info`` at install time, so adding a column to an
audited table needs no trigger change.
"""

from __future__ import annotations

from .connection import Connection

# Tables whose every mutation is logged. Mirrors the Postgres trigger set.
AUDITED_TABLES = (
    "recipes",
    "recipe_ingredients",
    "recipe_steps",
    "ingredient_resolutions",
    "taxonomy_nodes",
    "human_reviews",
)

ACTOR_KINDS = ("human", "worker", "system")


def set_actor(conn: Connection, kind: str, actor_id: str | None, source: str) -> None:
    """Attribute subsequent writes on this connection to ``(kind, id, source)``.

    ``kind`` is ``human`` (an operator session; ``actor_id`` = operator id),
    ``worker`` (a pipeline run; ``actor_id`` = job id) or ``system`` (CLI,
    migrations, ETL). ``source`` is free text, by convention ``job:<stage>``,
    ``api:<route>`` or ``cli:<command>``.
    """
    if kind not in ACTOR_KINDS:
        raise ValueError(f"unknown actor kind {kind!r}")
    conn.execute(
        "update audit_context set actor_kind = ?, actor_id = ?, source = ?",
        (kind, None if actor_id is None else str(actor_id), source),
    )


def install(conn: Connection, *, actor: tuple[str, str | None, str]) -> None:
    """Create the TEMP context table + triggers on this connection."""
    conn.execute(
        "create temp table if not exists audit_context ("
        "  actor_kind text not null, actor_id text, source text not null)"
    )
    if conn.execute("select count(*) from audit_context").fetchone()[0] == 0:
        conn.execute("insert into audit_context values (?, ?, ?)", actor)
    else:
        set_actor(conn, *actor)
    for table in AUDITED_TABLES:
        for ddl in _trigger_ddl(conn, table):
            conn.execute(ddl)


def _columns(conn: Connection, table: str) -> list[tuple[str, str]]:
    return [
        (r["name"], (r["type"] or "").upper())
        for r in conn.execute(f"pragma table_info({table})").fetchall()
    ]


def _row_json(prefix: str, cols: list[tuple[str, str]]) -> str:
    """``json_object('col', NEW.col, ...)`` for a full row image. JSON text
    columns are wrapped in ``json()`` so they embed as objects, not strings."""
    parts = []
    for name, decl in cols:
        ref = f"{prefix}.\"{name}\""
        if decl == "JSONTEXT":
            ref = f"json({ref})"
        parts.append(f"'{name}', {ref}")
    return "json_object(" + ", ".join(parts) + ")"


def _trigger_ddl(conn: Connection, table: str) -> list[str]:
    cols = _columns(conn, table)
    new_img = _row_json("new", cols)
    old_img = _row_json("old", cols)
    # Changed keys: compare the two images key by key. ``n.value is not o.value``
    # handles NULLs; ``type`` catches 1 vs '1'.
    diff_from = (
        f"from json_each({new_img}) n join json_each({old_img}) o on o.key = n.key "
        "where n.value is not o.value or n.type is not o.type"
    )
    actor_cols = "c.actor_kind, c.actor_id, c.source, " \
        "case when c.actor_kind = 'worker' then cast(c.actor_id as integer) end"
    ins_cols = "table_name, pk, op, actor_kind, actor_id, source, job_id, before, after, changed_keys"
    # A JSON-typed member must be re-wrapped in json() so the aggregate embeds
    # it as an object/array rather than as an escaped string.
    oval = "case when o.type in ('object','array') then json(o.value) else o.value end"
    nval = "case when n.type in ('object','array') then json(n.value) else n.value end"
    return [
        f"""create temp trigger if not exists audit_{table}_ins after insert on main.{table}
begin
  insert into audit_log ({ins_cols})
  select '{table}', new.id, 'I', {actor_cols}, null, null, null from audit_context c;
end""",
        f"""create temp trigger if not exists audit_{table}_upd after update on main.{table}
begin
  insert into audit_log ({ins_cols})
  select '{table}', new.id, 'U', {actor_cols},
         (select json_group_object(n.key, {oval}) {diff_from}),
         (select json_group_object(n.key, {nval}) {diff_from}),
         (select json_group_array(n.key) {diff_from})
  from audit_context c;
end""",
        f"""create temp trigger if not exists audit_{table}_del after delete on main.{table}
begin
  insert into audit_log ({ins_cols})
  select '{table}', old.id, 'D', {actor_cols}, {old_img}, null, null from audit_context c;
end""",
    ]
