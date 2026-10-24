"""One-time ETL: a staging Supabase ``pg_dump`` → the SQLite schema.

The input is the custom-format archive the (since removed)
``scripts/backup-supabase.sh`` / *Backup staging database* GitHub Action wrote. The ETL never
connects to Postgres: ``pg_restore --data-only -f -`` turns the archive into
plain SQL whose ``COPY … FROM stdin`` blocks are parsed here, each row is
coerced from Postgres' COPY text encoding into the SQLite column shapes
(``jsonb``/``text[]`` → JSON text, ``bool`` → 0/1, ``timestamptz`` → ISO-8601
UTC), and the rows are inserted into a fresh database built by the bundled
``common.db`` migrations. So the whole path is secrets-blind: whoever holds the
dump can produce the SQLite file, nobody needs the staging password.

Schema deltas handled here (everything else carries over column-for-column):

- ``jobs``: the approval columns (``requires_approval``/``approved*``) are
  dropped and the retired ``job_state`` values are folded
  (``awaiting_approval``/``claimed`` → ``queued``, ``succeeded`` → ``done``).
- ``audit.log`` → ``audit_log`` (``changed_keys text[]`` → JSON).
- ``profiles`` and ``worker_status`` are not migrated (passkey operators
  replace profiles; there is no worker daemon any more).
- ``created_by``/``reviewed_by``/``approved_by`` uuids become opaque text.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from common.db import Connection, open_database

Conv = Callable[[str], Any]

# ------------------------------------------------------------------ converters


def text(v: str) -> str:
    return v


def integer(v: str) -> int:
    return int(v)


def number(v: str) -> float:
    return float(v)


def boolean(v: str) -> int:
    if v in ("t", "true", "1"):
        return 1
    if v in ("f", "false", "0"):
        return 0
    raise ValueError(f"not a boolean: {v!r}")


def timestamp(v: str) -> str:
    """Postgres ``timestamptz`` text → ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC),
    the shape ``strftime('%Y-%m-%dT%H:%M:%fZ','now')`` writes."""
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def jsonb(v: str) -> str:
    # Re-serialise so the stored text is canonical JSON (and so a malformed
    # value fails here, loudly, instead of at read time).
    return json.dumps(json.loads(v), ensure_ascii=False, separators=(",", ":"))


def parse_pg_array(v: str) -> list[Any]:
    """Parse a one-dimensional Postgres array literal (``{a,"b c",NULL}``)."""
    s = v.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError(f"not an array literal: {v!r}")
    body = s[1:-1]
    out: list[Any] = []
    if body == "":
        return out
    i, n = 0, len(body)
    while i <= n:
        if i < n and body[i] == '"':
            i += 1
            buf: list[str] = []
            while True:
                c = body[i]
                if c == "\\":
                    buf.append(body[i + 1]); i += 2
                elif c == '"':
                    i += 1; break
                else:
                    buf.append(c); i += 1
            out.append("".join(buf))
        else:
            j = body.find(",", i)
            if j == -1:
                j = n
            tok = body[i:j]
            out.append(None if tok == "NULL" else tok)
            i = j
        if i < n and body[i] == ",":
            i += 1
            continue
        break
    return out


def text_array(v: str) -> str:
    return json.dumps(parse_pg_array(v), ensure_ascii=False, separators=(",", ":"))


def int_array(v: str) -> str:
    return json.dumps([None if x is None else int(x) for x in parse_pg_array(v)])


def char(v: str) -> str:
    return v.strip()


# --------------------------------------------------------------- table mapping


@dataclass(frozen=True)
class Col:
    name: str                 # SQLite column
    conv: Conv = text
    source: str | None = None # Postgres column (defaults to ``name``)

    @property
    def pg(self) -> str:
        return self.source or self.name


@dataclass(frozen=True)
class Table:
    pg_name: str              # ``schema.table`` as it appears in COPY
    sqlite_name: str
    cols: tuple[Col, ...]
    fixup: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _jobs_fixup(row: dict[str, Any]) -> dict[str, Any]:
    folded = {"awaiting_approval": "queued", "claimed": "queued", "succeeded": "done"}
    row["state"] = folded.get(row["state"], row["state"])
    return row


TS = timestamp
TABLES: tuple[Table, ...] = (
    Table("public.pages", "pages", (
        Col("id", integer), Col("url"), Col("site"), Col("corpus_key"), Col("content_type"),
        Col("denylist", boolean), Col("denylist_reason"), Col("fetch_status"),
        Col("discovered_at", TS), Col("fetched_at", TS),
    )),
    Table("public.taxonomy_nodes", "taxonomy_nodes", (
        Col("id", integer), Col("slug"), Col("display_name"), Col("node_kind"), Col("default_role"),
        Col("is_cluster_node", boolean), Col("is_defining_garnish", boolean), Col("status"),
        Col("created_at", TS), Col("updated_at", TS),
    )),
    Table("public.taxonomy_edges", "taxonomy_edges", (
        Col("parent_id", integer), Col("child_id", integer), Col("created_at", TS),
    )),
    Table("public.taxonomy_aliases", "taxonomy_aliases", (
        Col("alias"), Col("node_id", integer), Col("created_at", TS),
    )),
    Table("public.taxonomy_provenance", "taxonomy_provenance", (
        Col("node_id", integer), Col("source"), Col("mapper_version"), Col("raw_string"),
        Col("prompt_hash"), Col("model_id"), Col("created_at", TS),
    )),
    Table("public.cocktail_aliases", "cocktail_aliases", (
        Col("alias"), Col("canonical_name"), Col("source"), Col("created_at", TS),
    )),
    Table("public.recipe_clusters", "recipe_clusters", (
        Col("cluster_key"), Col("canonical_name"), Col("ingredient_set", jsonb),
        Col("representative_recipe_id", integer), Col("recipe_count", integer),
        Col("source_count", integer), Col("version"), Col("created_at", TS),
    )),
    Table("public.recipes", "recipes", (
        Col("id", integer), Col("source_url"), Col("site"), Col("source", jsonb), Col("title"),
        Col("author"), Col("image_url"), Col("equipment", text_array), Col("canonical_name"),
        Col("cluster_id"), Col("variant_key"), Col("recipe_slug"),
        Col("created_at", TS), Col("updated_at", TS),
    )),
    Table("public.recipe_ingredients", "recipe_ingredients", (
        Col("id", integer), Col("recipe_id", integer), Col("position", integer), Col("name"),
        Col("amount", number), Col("amount_max", number), Col("unit"),
        Col("modifiers", text_array), Col("raw_text"),
    )),
    Table("public.recipe_steps", "recipe_steps", (
        Col("id", integer), Col("recipe_id", integer), Col("step_index", integer), Col("verb"),
        Col("roles", jsonb), Col("modifiers", text_array), Col("result"),
    )),
    Table("public.ingredient_resolutions", "ingredient_resolutions", (
        Col("id", integer), Col("normalized_name"), Col("taxonomy_slug"), Col("method"),
        Col("confidence", number), Col("model_id"), Col("version"),
        Col("created_at", TS), Col("updated_at", TS),
    )),
    Table("public.recipe_exports", "recipe_exports", (
        Col("id", integer), Col("recipe_id", integer), Col("recipe_slug"), Col("recipe_ref"),
        Col("converter_version"), Col("bundle", jsonb), Col("exported_at", TS),
    )),
    Table("public.jobs", "jobs", (
        Col("id", integer), Col("stage"), Col("version"), Col("kind"), Col("payload", jsonb),
        Col("state"), Col("llm_provider"), Col("llm_model"),
        Col("cost_estimate_cents", integer), Col("cost_actual_cents", integer),
        Col("max_cost_cents", integer), Col("progress", jsonb), Col("error_code"),
        Col("error_detail"), Col("worker_id"), Col("last_heartbeat", TS), Col("created_by"),
        Col("created_at", TS), Col("started_at", TS), Col("finished_at", TS),
    ), fixup=_jobs_fixup),
    Table("public.job_items", "job_items", (
        Col("id", integer), Col("entity_type"), Col("entity_id", integer), Col("stage"),
        Col("code_version"), Col("outcome"), Col("method"), Col("confidence", number),
        Col("model_id"), Col("cost_cents", number), Col("error_code"), Col("job_id", integer),
        Col("payload", jsonb), Col("state"), Col("outcome_payload", jsonb),
        Col("started_at", TS), Col("finished_at", TS),
    )),
    Table("public.human_reviews", "human_reviews", (
        Col("id", integer), Col("entity_kind"), Col("entity_id"), Col("stage"), Col("state"),
        Col("origin"), Col("payload", jsonb), Col("note"), Col("origin_version"),
        Col("created_by"), Col("reviewed_by"), Col("reviewed_at", TS),
        Col("created_at", TS), Col("updated_at", TS),
    )),
    Table("audit.log", "audit_log", (
        Col("id", integer), Col("ts", TS), Col("table_name"), Col("pk"), Col("op", char),
        Col("actor_kind"), Col("actor_id"), Col("source"), Col("before", jsonb),
        Col("after", jsonb), Col("changed_keys", text_array), Col("job_id", integer),
    )),
)
BY_PG_NAME = {t.pg_name: t for t in TABLES}

# Present in the dump, deliberately left behind.
IGNORED = frozenset({"public.profiles", "public.worker_status"})


# ------------------------------------------------------------- COPY text parse

_COPY_RE = re.compile(
    r"^COPY\s+(?P<table>[\w\".]+)\s*\((?P<cols>[^)]*)\)\s+FROM\s+stdin;\s*$"
)
_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}


def unescape_field(raw: str) -> str | None:
    r"""Decode one COPY text field: ``\N`` is NULL, backslash escapes apply."""
    if raw == "\\N":
        return None
    if "\\" not in raw:
        return raw
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= n:
            out.append("\\"); break
        e = raw[i]
        if e in _ESCAPES:
            out.append(_ESCAPES[e]); i += 1
        elif e in "01234567":
            j = i
            while j < n and j < i + 3 and raw[j] in "01234567":
                j += 1
            out.append(chr(int(raw[i:j], 8))); i = j
        elif e == "x":
            j = i + 1
            while j < n and j < i + 3 and raw[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(chr(int(raw[i + 1:j], 16)) if j > i + 1 else "x"); i = j
        else:
            out.append(e); i += 1
    return "".join(out)


def _unquote_ident(s: str) -> str:
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('""', '"')
    return s


@dataclass
class CopyBlock:
    table: str                # ``schema.table``
    columns: list[str]
    rows: Iterator[list[str | None]]


def iter_copy_blocks(lines: Iterable[str]) -> Iterator[CopyBlock]:
    """Yield each ``COPY … FROM stdin;`` block of a plain-SQL dump. The
    ``rows`` iterator of a block must be exhausted before the next block is
    requested (the input is streamed once)."""
    it = iter(lines)
    for line in it:
        m = _COPY_RE.match(line)
        if not m:
            continue
        table = ".".join(_unquote_ident(p) for p in m.group("table").split("."))
        if "." not in table:
            table = "public." + table
        cols = [_unquote_ident(c) for c in m.group("cols").split(",")]

        def rows(_it: Iterator[str] = it) -> Iterator[list[str | None]]:
            for data in _it:
                if data.rstrip("\n") == "\\.":
                    return
                yield [unescape_field(f) for f in data.rstrip("\n").split("\t")]
            raise ValueError(f"COPY block for {table} not terminated")

        yield CopyBlock(table, cols, rows())


# --------------------------------------------------------------------- loading


@dataclass
class Report:
    loaded: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    unknown: dict[str, int] = field(default_factory=dict)
    fk_violations: list[tuple[str, int | None, str, int]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{t}={n}" for t, n in self.loaded.items()]
        for t, n in self.skipped.items():
            parts.append(f"skipped:{t}={n}")
        for t, n in self.unknown.items():
            parts.append(f"UNKNOWN:{t}={n}")
        if self.fk_violations:
            parts.append(f"fk_violations={len(self.fk_violations)}")
        return " ".join(parts)


def convert_row(table: Table, columns: list[str], fields: list[str | None]) -> dict[str, Any] | None:
    present = dict(zip(columns, fields))
    row: dict[str, Any] = {}
    for col in table.cols:
        raw = present.get(col.pg)
        row[col.name] = None if raw is None else col.conv(raw)
    return table.fixup(row) if table.fixup else row


def load_blocks(conn: Connection, blocks: Iterable[CopyBlock], report: Report, batch: int = 1000) -> None:
    for block in blocks:
        if block.table in IGNORED:
            report.skipped[block.table] = sum(1 for _ in block.rows)
            continue
        table = BY_PG_NAME.get(block.table)
        if table is None:
            report.unknown[block.table] = sum(1 for _ in block.rows)
            continue
        names = [c.name for c in table.cols]
        sql = (
            f"insert into {table.sqlite_name} ({', '.join(names)}) "
            f"values ({', '.join('?' for _ in names)})"
        )
        count = 0
        pending: list[tuple[Any, ...]] = []
        with conn.transaction():
            for fields in block.rows:
                row = convert_row(table, block.columns, fields)
                if row is None:
                    continue
                pending.append(tuple(row[n] for n in names))
                if len(pending) >= batch:
                    conn.executemany(sql, pending); count += len(pending); pending = []
            if pending:
                conn.executemany(sql, pending); count += len(pending)
        report.loaded[table.sqlite_name] = report.loaded.get(table.sqlite_name, 0) + count


def load_sql(conn: Connection, lines: Iterable[str], report: Report | None = None) -> Report:
    """Load every COPY block of a plain-SQL data dump into ``conn``."""
    report = report or Report()
    conn.raw.execute("pragma foreign_keys = off")
    try:
        load_blocks(conn, iter_copy_blocks(lines), report)
    finally:
        conn.raw.execute("pragma foreign_keys = on")
    report.fk_violations = [
        (r[0], r[1], r[2], r[3]) for r in conn.raw.execute("pragma foreign_key_check").fetchall()
    ]
    return report


def pg_restore_lines(dump: Path, pg_restore: str = "pg_restore") -> Iterator[str]:
    """Stream ``pg_restore --data-only`` of a custom-format archive as lines."""
    exe = shutil.which(pg_restore)
    if exe is None:
        raise SystemExit(f"{pg_restore} not found on PATH (install postgresql-client)")
    proc = subprocess.Popen(
        [exe, "--data-only", "--no-owner", "--no-privileges", "-f", "-", str(dump)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    assert proc.stdout is not None
    try:
        yield from proc.stdout
    finally:
        proc.stdout.close()
        rc = proc.wait()
        if rc != 0:
            err = proc.stderr.read() if proc.stderr else ""
            raise SystemExit(f"pg_restore exited {rc}: {err.strip()}")


def finish(conn: Connection) -> None:
    conn.raw.execute("pragma wal_checkpoint(truncate)")
    conn.raw.execute("vacuum")
    conn.raw.execute("pragma optimize")


def etl(dump: Path, out: Path, *, force: bool = False, lines: Iterable[str] | None = None,
        log: TextIO = sys.stderr) -> Report:
    """Build ``out`` (a new SQLite file) from ``dump`` (a pg_dump custom archive).

    ``lines`` overrides the pg_restore stream (tests feed plain SQL directly).
    """
    if out.exists():
        if not force:
            raise SystemExit(f"{out} exists; pass --force to replace it")
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(out) + suffix)
            if p.exists():
                p.unlink()
    conn = open_database(out, migrate=True, audit=False)
    try:
        report = load_sql(conn, lines if lines is not None else pg_restore_lines(dump))
        finish(conn)
    finally:
        conn.close()
    print(report.summary(), file=log)
    for table, rowid, parent, _fkid in report.fk_violations[:20]:
        print(f"  fk violation: {table} rowid={rowid} -> {parent}", file=log)
    return report
