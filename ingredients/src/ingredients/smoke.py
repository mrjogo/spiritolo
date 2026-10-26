"""Headless LLM-tier smoke test against a copy of the database.

Assembles the same runs an operator would build in ``/ops`` (create → set the
LLM tier → load items → start with a cost cap), runs each one to completion on
the calling thread through the real executor path (``runner.run_job``), and
prints a markdown report of what the model did: run state + error, cost, item
outcomes, and every ingredient name whose resolution changed. Meant for
``scripts/preview.sh --smoke`` on a scratch copy of the live database; it writes
to whatever ``--db`` names, so never point it at the live file.

    python -m ingredients.smoke --db /tmp/preview.db --provider deepseek \\
        [--model M] [--map 20] [--extract 5] [--cap-cents 50]

The provider's API key comes from the environment (``DEEPSEEK_API_KEY`` …), as
in the service. ``--extract`` reads page HTML through the corpus reader, so it
also needs the ``CORPUS_*`` variables; pass ``--extract 0`` without them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from common.db import SQL_NOW, Connection, jlist, open_database

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS
from ingredients import runs
from ingredients.worker import runner


def pick_map_recipes(conn: Connection, n: int) -> list[int]:
    """Recipes with at least one ingredient the deterministic tiers left
    unattached (minted provisional, or abstained) — the LLM tier's residue."""
    rows = conn.execute(
        """
        select distinct ri.recipe_id from recipe_ingredients ri
        join ingredient_resolutions r on r.normalized_name = lower(trim(ri.name))
        where r.method in ('provisional', 'abstain')
        order by ri.recipe_id limit ?
        """,
        (n,),
    ).fetchall()
    return [r[0] for r in rows]


def pick_extract_pages(conn: Connection, n: int) -> list[int]:
    """Pages whose latest extract outcome was an abstain (no Recipe JSON-LD)."""
    rows = conn.execute(
        """
        select i.entity_id from job_items i
        where i.stage = 'extract-recipe' and i.entity_type = 'page'
          and i.id = (select max(j.id) from job_items j
                      where j.stage = i.stage and j.entity_id = i.entity_id
                        and j.state in ('applied', 'flagged', 'failed'))
          and i.outcome = 'abstain'
        order by i.entity_id limit ?
        """,
        (n,),
    ).fetchall()
    return [r[0] for r in rows]


def _resolutions(conn: Connection, recipe_ids: list[int]) -> dict[str, tuple[Any, Any]]:
    rows = conn.execute(
        """
        select r.normalized_name, r.method, r.taxonomy_slug from ingredient_resolutions r
        where r.normalized_name in (
            select lower(trim(name)) from recipe_ingredients
            where recipe_id in (select value from json_each(?)) and name is not null)
        """,
        (jlist(recipe_ids),),
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def run_one(
    conn: Connection, stage: str, entity_ids: list[int], *, provider: str,
    model: str | None, cap_cents: int, run_job: Callable[..., str] = runner.run_job,
    **run_kwargs: Any,
) -> dict[str, Any]:
    """Build, start and run one smoke run to completion; return its job row."""
    job_id = runs.create_run(conn, stage, created_by="smoke-test")
    runs.set_run_llm(conn, job_id, provider, model)
    runs.add_run_items(conn, job_id, runs.entity_type_for(stage), entity_ids)
    runs.start_run(conn, job_id, cap_cents)
    # Claim exactly this job (a database copy can hold other queued runs).
    conn.execute(
        f"update jobs set state = 'running', started_at = {SQL_NOW}, worker_id = 'smoke' "
        "where id = ?",
        (job_id,),
    )
    job = runner._job_row(conn.execute("select * from jobs where id = ?", (job_id,)).fetchone())
    run_job(conn, job, **run_kwargs)
    return dict(conn.execute("select * from jobs where id = ?", (job_id,)).fetchone())


def _items_table(conn: Connection, job_id: int) -> list[str]:
    rows = conn.execute(
        "select state, outcome, method, count(*) from job_items where job_id = ? "
        "group by 1, 2, 3 order by 4 desc",
        (job_id,),
    ).fetchall()
    return ["| state | outcome | method | items |", "|---|---|---|---|"] + [
        f"| {s} | {o} | {m} | {n} |" for s, o, m, n in rows
    ]


def _job_lines(job: dict[str, Any]) -> list[str]:
    lines = [
        f"- run {job['id']}: **{job['state']}** on {job['llm_provider']}"
        f" · {job['llm_model'] or '(default model)'}",
        f"- cost: actual {job['cost_actual_cents']}¢, estimate"
        f" {job['cost_estimate_cents']}¢, cap {job['max_cost_cents']}¢",
    ]
    if job.get("error_code"):
        lines.append(f"- error: `{job['error_code']}` — {job.get('error_detail')}")
    return lines


def smoke(
    conn: Connection, *, provider: str, model: str | None = None, n_map: int = 20,
    n_extract: int = 5, cap_cents: int = 50, **run_kwargs: Any,
) -> str:
    """Run the map (and optionally extract) smoke runs; return the report."""
    out = [f"# LLM smoke test: {provider} · {model or '(default model)'}", ""]

    recipe_ids = pick_map_recipes(conn, n_map) if n_map else []
    if recipe_ids:
        before = _resolutions(conn, recipe_ids)
        job = run_one(conn, "map-ingredient", recipe_ids, provider=provider, model=model,
                      cap_cents=cap_cents, **run_kwargs)
        after = _resolutions(conn, recipe_ids)
        llm = sorted((n, s) for n, (m, s) in after.items() if m == "llm")
        out += [f"## map-ingredient ({len(recipe_ids)} recipes, {len(after)} names)", "",
                *_job_lines(job), "", *_items_table(conn, job["id"]), "",
                f"Names the model attached to a live node: **{len(llm)}**", ""]
        out += [f"- {n} → `{s}` (was {before.get(n, ('new', None))[0]})" for n, s in llm]
        out.append("")
    elif n_map:
        out += ["## map-ingredient", "", "No recipe has an unattached ingredient; skipped.", ""]

    page_ids = pick_extract_pages(conn, n_extract) if n_extract else []
    if page_ids:
        job = run_one(conn, "extract-recipe", page_ids, provider=provider, model=model,
                      cap_cents=cap_cents, **run_kwargs)
        out += [f"## extract-recipe ({len(page_ids)} pages without JSON-LD)", "",
                *_job_lines(job), "", *_items_table(conn, job["id"]), ""]
        for url, outcome, title, n_ing in conn.execute(
            """
            select p.url, i.outcome, r.title, json_array_length(r.source, '$.recipeIngredient')
            from job_items i join pages p on p.id = i.entity_id
            left join recipes r on r.source_url = p.url
            where i.job_id = ? order by p.id
            """,
            (job["id"],),
        ).fetchall():
            got = f"“{title}”, {n_ing} ingredients" if outcome == "resolved" else outcome
            out.append(f"- {url} → {got}")
        out.append("")
    elif n_extract:
        out += ["## extract-recipe", "", "No page has an abstained extract; skipped.", ""]

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", required=True, help="A scratch COPY of the database.")
    p.add_argument("--provider", default="deepseek")
    p.add_argument("--model", default=None)
    p.add_argument("--map", type=int, default=20, dest="n_map")
    p.add_argument("--extract", type=int, default=5, dest="n_extract")
    p.add_argument("--cap-cents", type=int, default=50)
    p.add_argument("--out", default=None, help="Also write the report to this file.")
    args = p.parse_args(argv)
    conn = open_database(args.db, actor=("human", None, "smoke-test"))
    try:
        report = smoke(conn, provider=args.provider, model=args.model, n_map=args.n_map,
                       n_extract=args.n_extract, cap_cents=args.cap_cents)
    finally:
        conn.close()
    print(report)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
