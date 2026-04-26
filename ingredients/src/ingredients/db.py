"""Postgres data-access layer for the ingredient parser worker.

All queries are written against Supabase Postgres (the local one in dev).
Connection credentials come from SUPABASE_DB_URL via spiritolo_common.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import psycopg
from dotenv import load_dotenv


def _env_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
        url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Run `supabase status` and add it to .env."
        )
    return url


class IngredientsDatabase:
    """Connection + queries for recipes -> recipe_ingredients."""

    def __init__(self, db_url: str | None = None):
        self.conn = psycopg.connect(db_url or _env_url())

    def close(self) -> None:
        self.conn.close()

    def fetch_work_queue(
        self, *, parser_version: str, site: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Recipes that need parsing under the current PARSER_VERSION.

        A recipe needs parsing when it has zero recipe_ingredients rows at
        `parser_version`. (Older-version rows are ignored — they don't satisfy
        the requirement, and they will be replaced when the recipe is parsed.)
        """
        params: list[Any] = [parser_version]
        site_clause = ""
        if site is not None:
            site_clause = "and r.site = %s"
            params.append(site)

        sql = f"""
            select r.id, r.site, r.source_url, r.jsonld->'recipeIngredient' as recipe_ingredient
            from recipes r
            where jsonb_typeof(r.jsonld->'recipeIngredient') = 'array'
              and not exists (
                select 1 from recipe_ingredients ri
                where ri.recipe_id = r.id and ri.parser_version = %s
              )
              {site_clause}
            order by r.id
        """
        if limit is not None:
            sql += " limit %s"
            params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "id": row[0], "site": row[1], "source_url": row[2],
                "recipe_ingredient": row[3] or [],
            }
            for row in rows
        ]

    def write_recipe_parses(
        self, *, recipe_id: int, rows: Iterable[dict[str, Any]],
        parser_version: str,
    ) -> None:
        """Replace all recipe_ingredients rows for `recipe_id` atomically.

        Each row dict must contain: position, raw_text, amount, amount_max,
        unit, name, modifier, parse_status, parser_rule.
        """
        with self.conn.transaction():
            self.conn.execute(
                "delete from recipe_ingredients where recipe_id = %s",
                (recipe_id,),
            )
            for r in rows:
                self.conn.execute(
                    """
                    insert into recipe_ingredients (
                        recipe_id, position, raw_text,
                        amount, amount_max, unit, name, modifier,
                        parse_status, parser_rule, parser_version
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        recipe_id, r["position"], r["raw_text"],
                        r["amount"], r["amount_max"], r["unit"], r["name"],
                        r["modifier"], r["parse_status"], r["parser_rule"],
                        parser_version,
                    ),
                )

    def count_eval_rows(
        self, *, site: str | None, except_version: str | None,
        older_than: str | None,
    ) -> int:
        sql, params = self._eval_rows_filter(
            select="select count(*)", site=site,
            except_version=except_version, older_than=older_than,
        )
        return self.conn.execute(sql, params).fetchone()[0]

    def clear_eval_rows(
        self, *, site: str | None, except_version: str | None,
        older_than: str | None,
    ) -> int:
        sql, params = self._eval_rows_filter(
            select="delete", site=site,
            except_version=except_version, older_than=older_than,
        )
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    @staticmethod
    def _eval_rows_filter(
        *, select: str, site: str | None,
        except_version: str | None, older_than: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if site is not None:
            clauses.append("ri.recipe_id in (select id from recipes where site = %s)")
            params.append(site)
        if except_version is not None:
            clauses.append("ri.parser_version <> %s")
            params.append(except_version)
        if older_than is not None:
            clauses.append("ri.parsed_at < %s::timestamptz")
            params.append(older_than)
        where = (" where " + " and ".join(clauses)) if clauses else ""
        return f"{select} from recipe_ingredients ri{where}", params
