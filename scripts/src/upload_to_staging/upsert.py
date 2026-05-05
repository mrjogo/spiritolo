"""SQL builders for the per-table UPSERT batches and the post-batch
sequence resync."""
from __future__ import annotations

from psycopg import sql

from .tables import OwnedTable


def build_upsert_sql(
    table: OwnedTable, columns: list[str]
) -> sql.Composed:
    """`INSERT INTO <table> (<cols>) VALUES %s ON CONFLICT (<pk>) DO UPDATE
    SET <non-pk> = EXCLUDED.<non-pk>...` — to be invoked with
    `cursor.executemany` or via parameterized batched INSERT.
    """
    pk_set = set(table.pk_columns)
    non_pk = [c for c in columns if c not in pk_set]

    placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(columns))
    set_clause = sql.SQL(", ").join(
        sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(c))
        for c in non_pk
    )

    return sql.SQL(
        "insert into public.{tbl} ({cols}) values ({vals}) "
        "on conflict ({pk}) do update set {sets}"
    ).format(
        tbl=sql.Identifier(table.name),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        vals=placeholders,
        pk=sql.SQL(", ").join(sql.Identifier(c) for c in table.pk_columns),
        sets=set_clause,
    )


def resync_sequence_sql(table: OwnedTable) -> sql.Composed | None:
    """`select setval(<seq>, max(<pk>)) from <table>` — but safe when
    the table is empty (max returns NULL, which setval rejects) and
    when the sequence has never been called. We coalesce max(pk) to 1
    and take greatest with the sequence's current `last_value` so an
    empty table with a fresh sequence is a no-op.

    Returns None for tables without a sequence (composite PKs).
    """
    if table.sequence is None:
        return None
    if len(table.pk_columns) != 1:
        return None  # belt-and-braces; sequence implies single-column PK

    pk = sql.Identifier(table.pk_columns[0])
    seq = sql.Literal(table.sequence)
    return sql.SQL(
        "select setval({seq}, "
        "  greatest(coalesce(max({pk}), 1), "
        "           (select last_value from {seq_id})), "
        "  true) "
        "from public.{tbl}"
    ).format(
        seq=seq,
        pk=pk,
        tbl=sql.Identifier(table.name),
        seq_id=sql.Identifier(table.sequence),
    )
