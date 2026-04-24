"""Tests for the validate CLI (scraper/src/validate.py).

The validate CLI re-runs validate() + classify_drink() over cached HTML.
Work queue is "rows with cached HTML that have no validate_html_runs row" so
runs are resumable and arbitrary subsets can be re-processed by clearing
validate_html_runs via SQL or --reset.

Each invocation also opens a `pipeline_runs` row, writes one `validate_html_runs`
and one `classify_drink_runs` row per processed page (latest-only UPSERT), and
snapshots the pre-run pages.status / pages.content_type onto those eval rows so
"which rows flipped on the last run" is a trivial SELECT away.
"""

from pathlib import Path

from scraper.src.db import Database
from scraper.src.validate import revalidate


IMBIBE_STYLE_DRINK = """<!DOCTYPE html>
<html><body>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Classic Negroni",
    "recipeCategory": "Dessert",
    "recipeIngredient": ["1 oz gin", "1 oz sweet vermouth", "1 oz Campari"],
    "recipeInstructions": "Stir with ice and strain into a rocks glass."
}
</script>
</body></html>"""


OBVIOUS_FOOD = """<!DOCTYPE html>
<html><body>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Bourbon Pecan Pie",
    "recipeCategory": "Dessert",
    "cookTime": "PT50M",
    "recipeIngredient": ["2 cups pecans", "1 cup sugar", "3 tbsp butter"],
    "recipeInstructions": "Preheat oven to 350F. Bake for 50 minutes."
}
</script>
</body></html>"""


def _seed_cached_row(
    db: Database,
    html_dir: Path,
    *,
    url: str,
    site: str,
    status: str,
    content_type: str | None,
    html: str,
) -> str:
    """Insert a row with cached HTML on disk. Returns the html_path stored in
    the DB (relative to html_dir, matching fetch.py's convention)."""
    rel_path = f"{site}/{abs(hash(url)):016x}.html"
    (html_dir / site).mkdir(parents=True, exist_ok=True)
    (html_dir / rel_path).write_text(html, encoding="utf-8")
    db.add_url(site, url)
    db.mark_content(url, status, html_path=rel_path)
    if content_type:
        db.set_content_type(url, content_type)
    return rel_path


def _content_type(db: Database, url: str) -> str | None:
    with db._lock:
        row = db.conn.execute(
            "SELECT content_type FROM pages WHERE url = ?", (url,)
        ).fetchone()
    return row["content_type"] if row else None


def _eval_row(db: Database, table: str, url: str) -> dict | None:
    row = db.conn.execute(
        f"SELECT t.* FROM {table} t JOIN pages p ON p.id = t.page_id "
        "WHERE p.url = ?",
        (url,),
    ).fetchone()
    return dict(row) if row else None


def test_revalidate_flips_confirmed_food_to_drink_when_scored_classifier_disagrees(
    tmp_db, tmp_path
):
    """The Imbibe pattern: recipeCategory='Dessert' but a clear cocktail. The
    old keyword classifier labeled these confirmed_food; the new scored one
    should relabel them to confirmed_drink on revalidation."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir,
        url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food",
        html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir)

    assert _content_type(db, url) == "confirmed_drink"
    db.close()


def test_revalidate_leaves_food_alone_when_scored_classifier_agrees(tmp_db, tmp_path):
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://foodnetwork.com/bourbon-pecan-pie"
    _seed_cached_row(
        db, html_dir,
        url=url, site="foodnetwork", status="Recipe",
        content_type="confirmed_food",
        html=OBVIOUS_FOOD,
    )

    revalidate(db, html_dir=html_dir)

    assert _content_type(db, url) == "confirmed_food"
    db.close()


def test_revalidate_abstain_does_not_clobber_existing_content_type(tmp_db, tmp_path):
    """When classify_drink abstains (returns None), preserve whatever label the
    row already has. Overwriting a human- or LLM-set label with NULL would
    erase work the scored classifier isn't confident enough to overrule."""
    ambiguous = """<!DOCTYPE html><html><body>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Recipe",
 "name": "Strawberry Sauce",
 "recipeIngredient": ["Strawberries", "Sugar"]}
</script></body></html>"""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://example.com/strawberry-sauce"
    _seed_cached_row(
        db, html_dir,
        url=url, site="example", status="Recipe",
        content_type="confirmed_food",
        html=ambiguous,
    )

    revalidate(db, html_dir=html_dir)

    assert _content_type(db, url) == "confirmed_food"
    db.close()


def test_revalidate_dry_run_does_not_mutate_pages(tmp_db, tmp_path):
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir,
        url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food",
        html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir, dry_run=True)

    assert _content_type(db, url) == "confirmed_food"
    db.close()


def test_revalidate_reports_content_type_transitions(tmp_db, tmp_path):
    """The returned changes dict must include content_type transitions so the
    CLI summary shows them alongside status transitions."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    _seed_cached_row(
        db, html_dir,
        url="https://imbibemagazine.com/negroni", site="imbibe",
        status="Recipe", content_type="confirmed_food",
        html=IMBIBE_STYLE_DRINK,
    )

    changes = revalidate(db, html_dir=html_dir)

    imbibe_changes = changes.get("imbibe", {})
    assert "confirmed_food -> confirmed_drink" in imbibe_changes
    assert imbibe_changes["confirmed_food -> confirmed_drink"] == 1
    db.close()


def test_revalidate_writes_validate_html_runs_row(tmp_db, tmp_path):
    """Processed pages get a validate_html_runs row (UPSERT, latest-only)."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir, url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir)

    row = _eval_row(db, "validate_html_runs", url)
    assert row is not None
    assert row["status"] == "Recipe"
    assert row["validator_version"]  # non-empty
    assert row["evaluated_at"] is not None
    db.close()


def test_revalidate_writes_classify_drink_runs_row_with_score_and_snapshot(
    tmp_db, tmp_path
):
    """classify_drink_runs captures the label, score, and the
    pages.content_type as it was RIGHT BEFORE this evaluation. That snapshot
    is how 'what flipped on the last run' becomes a trivial SELECT."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir, url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir)

    row = _eval_row(db, "classify_drink_runs", url)
    assert row is not None
    assert row["label"] == "confirmed_drink"
    assert row["score"] is not None and row["score"] >= 2
    assert row["pages_content_type_before"] == "confirmed_food"
    assert row["scorer_version"]
    db.close()


def test_revalidate_classify_drink_runs_abstain_stores_null_label(tmp_db, tmp_path):
    """Abstain still writes a row (so we know the evaluator ran) but with
    label=NULL. The snapshot still captures what pages.content_type was."""
    # A Recipe with no strong drink or food signals — score stays between
    # -2 and 2, so classify_drink_scored returns label=None.
    ambiguous = """<!DOCTYPE html><html><body>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Recipe",
 "name": "Mystery Thing",
 "recipeIngredient": ["Stuff", "More stuff"]}
</script></body></html>"""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://example.com/strawberry-sauce"
    _seed_cached_row(
        db, html_dir, url=url, site="example", status="Recipe",
        content_type="confirmed_food", html=ambiguous,
    )

    revalidate(db, html_dir=html_dir)

    row = _eval_row(db, "classify_drink_runs", url)
    assert row is not None
    assert row["label"] is None
    assert row["pages_content_type_before"] == "confirmed_food"
    db.close()


def test_revalidate_opens_and_closes_pipeline_runs_row(tmp_db, tmp_path):
    """Each invocation creates a pipeline_runs row with stage='validate_html',
    stamped with started_at at entry and finished_at at the end. Eval rows
    written during the run reference this run_id."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    _seed_cached_row(
        db, html_dir, url="https://imbibemagazine.com/negroni", site="imbibe",
        status="Recipe", content_type="confirmed_food",
        html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir)

    runs = db.conn.execute(
        "SELECT id, stage, started_at, finished_at FROM pipeline_runs"
    ).fetchall()
    assert len(runs) == 1
    assert runs[0]["stage"] == "validate_html"
    assert runs[0]["started_at"] is not None
    assert runs[0]["finished_at"] is not None

    eval_row = db.conn.execute("SELECT run_id FROM validate_html_runs").fetchone()
    assert eval_row["run_id"] == runs[0]["id"]
    db.close()


def test_revalidate_skips_rows_with_existing_eval(tmp_db, tmp_path):
    """Work queue excludes pages that already have a validate_html_runs row."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir, url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )
    page_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", (url,)).fetchone()["id"]
    seeded_run = db.start_run(stage="validate_html")
    db.record_validate_html(
        page_id=page_id, run_id=seeded_run, status="Recipe", reason="seeded",
        validator_version="v0", pages_status_before="Recipe",
    )

    changes = revalidate(db, html_dir=html_dir)

    assert changes == {}
    # content_type must NOT have flipped: the row wasn't in the work queue.
    assert _content_type(db, url) == "confirmed_food"
    db.close()


def test_revalidate_second_run_is_no_op(tmp_db, tmp_path):
    """End-to-end incrementality: run once, then again; second run has no
    rows to process and returns empty changes."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    _seed_cached_row(
        db, html_dir, url="https://imbibemagazine.com/negroni", site="imbibe",
        status="Recipe", content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )

    first = revalidate(db, html_dir=html_dir)
    assert first  # first run does work

    second = revalidate(db, html_dir=html_dir)
    assert second == {}
    db.close()


def test_revalidate_respects_limit(tmp_db, tmp_path):
    """--limit caps the number of rows pulled from the work queue. Evaluated
    rows are the ones with a validate_html_runs row afterward."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    for i in range(5):
        _seed_cached_row(
            db, html_dir, url=f"https://imbibemagazine.com/negroni-{i}",
            site="imbibe", status="Recipe", content_type="confirmed_food",
            html=IMBIBE_STYLE_DRINK,
        )

    revalidate(db, html_dir=html_dir, limit=2)

    count = db.conn.execute(
        "SELECT COUNT(*) c FROM validate_html_runs"
    ).fetchone()["c"]
    assert count == 2
    db.close()


def test_revalidate_dry_run_does_not_insert_eval_rows(tmp_db, tmp_path):
    """--dry-run must not write validate_html_runs or classify_drink_runs,
    otherwise a preview would silently hide rows from the subsequent real run."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/negroni"
    _seed_cached_row(
        db, html_dir, url=url, site="imbibe", status="Recipe",
        content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )

    revalidate(db, html_dir=html_dir, dry_run=True)

    assert db.conn.execute("SELECT COUNT(*) c FROM validate_html_runs").fetchone()["c"] == 0
    assert db.conn.execute("SELECT COUNT(*) c FROM classify_drink_runs").fetchone()["c"] == 0
    db.close()


def test_revalidate_validate_html_runs_snapshot_captures_pre_run_status(
    tmp_db, tmp_path
):
    """When the HTML no longer parses as a Recipe (say, the page was replaced
    with a 404 shell), validate's status flips. The snapshot column records
    what pages.status was BEFORE this eval, enabling 'show me status flips
    from the last run' queries."""
    soft_404 = """<!DOCTYPE html>
<html><head><title>Page Not Found</title><meta name="robots" content="noindex"></head>
<body><h1>404</h1>
<p>""" + ("Sorry, the page you're looking for has been moved or deleted. " * 20) + """</p>
</body></html>"""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    url = "https://imbibemagazine.com/gone"
    _seed_cached_row(
        db, html_dir, url=url, site="imbibe", status="Recipe",
        content_type="confirmed_drink", html=soft_404,
    )

    revalidate(db, html_dir=html_dir)

    row = _eval_row(db, "validate_html_runs", url)
    assert row["status"] == "blocked"
    assert row["pages_status_before"] == "Recipe"
    db.close()


def test_revalidate_reset_deletes_validate_html_runs_scoped(tmp_db, tmp_path):
    """--reset analog at the Database layer: clear_validate_html_runs(site=...)
    deletes only that site's rows, optionally."""
    db = Database(tmp_db)
    html_dir = tmp_path / "html"
    _seed_cached_row(
        db, html_dir, url="https://imbibemagazine.com/a", site="imbibe",
        status="Recipe", content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )
    _seed_cached_row(
        db, html_dir, url="https://punch.com/b", site="punch",
        status="Recipe", content_type="confirmed_food", html=IMBIBE_STYLE_DRINK,
    )
    revalidate(db, html_dir=html_dir)
    assert db.conn.execute("SELECT COUNT(*) c FROM validate_html_runs").fetchone()["c"] == 2

    assert db.clear_validate_html_runs(site="imbibe") == 1

    remaining = db.conn.execute(
        "SELECT p.site FROM validate_html_runs v JOIN pages p ON p.id = v.page_id"
    ).fetchall()
    assert [r["site"] for r in remaining] == ["punch"]
    db.close()
