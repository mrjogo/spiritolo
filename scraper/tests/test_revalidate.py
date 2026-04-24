"""Tests for revalidate.py.

Revalidate re-runs validate() + classify_drink() over cached HTML. The
content_type flow is independent of the validate status flow — a row's
validate status may stay at "Recipe" while its content_type flips from
confirmed_food to confirmed_drink under the new scored classifier.
"""

from pathlib import Path

from scraper.src.db import Database
from scraper.src.revalidate import revalidate


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
    db.mark_content(url, status, "seeded", html_path=rel_path)
    if content_type:
        db.set_content_type(url, content_type)
    return rel_path


def _content_type(db: Database, url: str) -> str | None:
    with db._lock:
        row = db.conn.execute(
            "SELECT content_type FROM pages WHERE url = ?", (url,)
        ).fetchone()
    return row["content_type"] if row else None


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


def test_revalidate_dry_run_does_not_mutate_db(tmp_db, tmp_path):
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
