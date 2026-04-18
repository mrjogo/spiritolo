# Drink Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify recipe URLs as drink or food so the scraper only fetches drink recipes, saving ScraperAPI credits and keeping the database clean.

**Architecture:** New `content_type` column on `pages` table holds classification state (null → likely_* → confirmed_*). Pre-fetch classification is manual via Claude Code. Post-fetch confirmation uses JSON-LD structured data checked against a term list. The fetch pipeline filters to only `likely_drink_recipe` rows.

**Tech Stack:** Python, SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-04-12-drink-detection-design.md`

---

## File Map

| File | Role |
|---|---|
| `scraper/src/db.py` | Add `content_type` column, indexes, new query/update methods |
| `scraper/tests/test_db.py` | Tests for new DB methods |
| `scraper/src/validate.py` | Add `DRINK_TERMS` and `classify_drink()` function |
| `scraper/tests/test_validate.py` | Tests for drink classification |
| `scraper/tests/conftest.py` | New fixture for drink recipe HTML with JSON-LD |
| `scraper/src/fetch.py` | Filter to `likely_drink_recipe`, call `classify_drink()` post-fetch |
| `scraper/tests/test_fetch.py` | Update fetch tests for content_type filtering and confirmation |

---

### Task 1: Add `content_type` column and indexes to DB schema

**Files:**
- Modify: `scraper/src/db.py`
- Test: `scraper/tests/test_db.py`

- [x] **Step 1: Write failing test for content_type column existence**

In `scraper/tests/test_db.py`, add:

```python
def test_schema_has_content_type_column(tmp_db):
    db = Database(tmp_db)
    row = db.conn.execute("PRAGMA table_info(pages)").fetchall()
    columns = [r[1] for r in row]
    assert "content_type" in columns
    db.close()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest scraper/tests/test_db.py::test_schema_has_content_type_column -v`
Expected: FAIL — `content_type` not in column list

- [x] **Step 3: Add content_type column and indexes to schema**

In `scraper/src/db.py`, update `CREATE_TABLE` to add `content_type TEXT` after the `status` line:

```python
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    content_type TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    error TEXT,
    html_path TEXT
);
"""
```

Add to `CREATE_INDEXES`:

```python
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);",
    "CREATE INDEX IF NOT EXISTS idx_pages_site ON pages(site);",
    "CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);",
    "CREATE INDEX IF NOT EXISTS idx_pages_status_content_type ON pages(status, content_type);",
]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest scraper/tests/test_db.py::test_schema_has_content_type_column -v`
Expected: PASS

- [x] **Step 5: Run full test suite to check nothing broke**

Run: `pytest scraper/tests/ -v`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "Add content_type column and indexes to pages schema"
```

---

### Task 2: Add `set_content_type`, `set_content_type_batch`, and `get_by_content_type` methods

**Files:**
- Modify: `scraper/src/db.py`
- Test: `scraper/tests/test_db.py`

- [x] **Step 1: Write failing tests for all three methods**

In `scraper/tests/test_db.py`, add:

```python
def test_set_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.set_content_type("https://example.com/recipe/1", "likely_drink_recipe")
    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipe/1",),
    ).fetchone()
    assert row["content_type"] == "likely_drink_recipe"
    db.close()


def test_set_content_type_batch(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.add_url("testsite", "https://example.com/recipe/3")
    rows = db.conn.execute("SELECT id FROM pages ORDER BY id").fetchall()
    ids = [rows[0]["id"], rows[1]["id"]]
    db.set_content_type_batch(ids, "likely_food_recipe")
    updated = db.conn.execute(
        "SELECT content_type FROM pages WHERE id IN (?, ?)", tuple(ids)
    ).fetchall()
    assert all(r["content_type"] == "likely_food_recipe" for r in updated)
    # Third row should still be NULL
    third = db.conn.execute(
        "SELECT content_type FROM pages WHERE id = ?", (rows[2]["id"],)
    ).fetchone()
    assert third["content_type"] is None
    db.close()


def test_get_by_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/recipe/1")
    db.add_url("site_a", "https://a.com/recipe/2")
    db.add_url("site_b", "https://b.com/recipe/1")
    db.set_content_type("https://a.com/recipe/1", "likely_drink_recipe")
    db.set_content_type("https://a.com/recipe/2", "likely_drink_recipe")
    db.set_content_type("https://b.com/recipe/1", "likely_drink_recipe")
    # All drink recipes
    all_drinks = db.get_by_content_type("likely_drink_recipe")
    assert len(all_drinks) == 3
    # Filter by site
    site_a_drinks = db.get_by_content_type("likely_drink_recipe", site="site_a")
    assert len(site_a_drinks) == 2
    # Limit
    limited = db.get_by_content_type("likely_drink_recipe", limit=1)
    assert len(limited) == 1
    db.close()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest scraper/tests/test_db.py::test_set_content_type scraper/tests/test_db.py::test_set_content_type_batch scraper/tests/test_db.py::test_get_by_content_type -v`
Expected: FAIL — `Database` has no attribute `set_content_type`

- [x] **Step 3: Implement all three methods**

In `scraper/src/db.py`, add to the `Database` class:

```python
def set_content_type(self, url: str, content_type: str):
    self.conn.execute(
        "UPDATE pages SET content_type = ? WHERE url = ?",
        (content_type, url),
    )
    self.conn.commit()

def set_content_type_batch(self, ids: list[int], content_type: str):
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    self.conn.execute(
        f"UPDATE pages SET content_type = ? WHERE id IN ({placeholders})",
        [content_type] + ids,
    )
    self.conn.commit()

def get_by_content_type(self, content_type: str, site: str | None = None, limit: int | None = None) -> list[dict]:
    query = "SELECT * FROM pages WHERE content_type = ?"
    params: list = [content_type]
    if site:
        query += " AND site = ?"
        params.append(site)
    query += " ORDER BY site, discovered_at"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    rows = self.conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest scraper/tests/test_db.py::test_set_content_type scraper/tests/test_db.py::test_set_content_type_batch scraper/tests/test_db.py::test_get_by_content_type -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "Add set_content_type, set_content_type_batch, get_by_content_type DB methods"
```

---

### Task 3: Add `content_type` filter to `get_pending`

**Files:**
- Modify: `scraper/src/db.py`
- Test: `scraper/tests/test_db.py`

- [x] **Step 1: Write failing test for content_type filter on get_pending**

In `scraper/tests/test_db.py`, add:

```python
def test_get_pending_filters_by_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    db.add_url("testsite", "https://example.com/recipe/2")
    db.add_url("testsite", "https://example.com/recipe/3")
    db.set_content_type("https://example.com/recipe/1", "likely_drink_recipe")
    db.set_content_type("https://example.com/recipe/2", "likely_food_recipe")
    # recipe/3 stays NULL
    pending = db.get_pending(content_type="likely_drink_recipe")
    assert len(pending) == 1
    assert pending[0]["url"] == "https://example.com/recipe/1"
    db.close()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest scraper/tests/test_db.py::test_get_pending_filters_by_content_type -v`
Expected: FAIL — `get_pending()` got unexpected keyword argument `content_type`

- [x] **Step 3: Add content_type parameter to get_pending**

In `scraper/src/db.py`, update `get_pending`:

```python
def get_pending(self, site: str | None = None, limit: int | None = None, content_type: str | None = None) -> list[dict]:
    query = "SELECT * FROM pages WHERE status = 'pending'"
    params: list = []
    if site:
        query += " AND site = ?"
        params.append(site)
    if content_type:
        query += " AND content_type = ?"
        params.append(content_type)
    query += " ORDER BY site, discovered_at"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    rows = self.conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest scraper/tests/test_db.py::test_get_pending_filters_by_content_type -v`
Expected: PASS

- [x] **Step 5: Run full DB test suite**

Run: `pytest scraper/tests/test_db.py -v`
Expected: All tests pass (existing tests don't pass `content_type`, so they still work)

- [x] **Step 6: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "Add content_type filter to get_pending"
```

---

### Task 4: Add `classify_drink` function to validate.py

**Files:**
- Modify: `scraper/src/validate.py`
- Modify: `scraper/tests/conftest.py`
- Test: `scraper/tests/test_validate.py`

- [x] **Step 1: Add drink recipe HTML fixtures to conftest.py**

In `scraper/tests/conftest.py`, add these fixtures:

```python
@pytest.fixture
def sample_drink_recipe_html():
    """Recipe HTML with JSON-LD that has drink signals in recipeCategory."""
    body = "<p>A classic cocktail.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Classic Margarita</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Classic Margarita",
    "recipeCategory": "Cocktail",
    "keywords": "tequila, lime",
    "recipeIngredient": ["2 oz tequila", "1 oz lime juice"]
}
</script>
</body>
</html>"""


@pytest.fixture
def sample_food_recipe_html():
    """Recipe HTML with JSON-LD that has no drink signals."""
    body = "<p>A hearty dinner recipe.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Grilled Salmon</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Grilled Salmon",
    "recipeCategory": "Dinner, Main Course",
    "keywords": "salmon, grilled, healthy",
    "recipeIngredient": ["1 lb salmon", "2 tbsp olive oil"]
}
</script>
</body>
</html>"""


@pytest.fixture
def sample_drink_breadcrumb_html():
    """Recipe HTML where the drink signal is in the breadcrumb, not recipeCategory."""
    body = "<p>A refreshing gin cocktail.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Negroni</title></head>
<body>
""" + body + """<script type="application/ld+json">
[{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Negroni",
    "recipeCategory": "Gin",
    "keywords": "campari, vermouth",
    "mainEntityOfPage": {
        "@type": "WebPage",
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "item": {"name": "Recipes"}},
                {"@type": "ListItem", "position": 2, "item": {"name": "Drinks"}},
                {"@type": "ListItem", "position": 3, "item": {"name": "Cocktails"}}
            ]
        }
    }
}]
</script>
</body>
</html>"""


@pytest.fixture
def sample_drink_keywords_html():
    """Recipe HTML where the drink signal is only in keywords."""
    body = "<p>An easy party drink.</p>\n" * 40
    return """<!DOCTYPE html>
<html>
<head><title>Espresso Martini</title></head>
<body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Espresso Martini",
    "recipeCategory": "Vodka",
    "keywords": "beverages, cocktails, party-food"
}
</script>
</body>
</html>"""
```

- [x] **Step 2: Write failing tests for classify_drink**

In `scraper/tests/test_validate.py`, add:

```python
from scraper.src.validate import validate, ValidationResult, classify_drink


def test_classify_drink_from_category(sample_drink_recipe_html):
    result = classify_drink(sample_drink_recipe_html)
    assert result == "confirmed_drink"


def test_classify_drink_from_breadcrumb(sample_drink_breadcrumb_html):
    result = classify_drink(sample_drink_breadcrumb_html)
    assert result == "confirmed_drink"


def test_classify_drink_from_keywords(sample_drink_keywords_html):
    result = classify_drink(sample_drink_keywords_html)
    assert result == "confirmed_drink"


def test_classify_drink_food_recipe(sample_food_recipe_html):
    result = classify_drink(sample_food_recipe_html)
    assert result == "confirmed_food"


def test_classify_drink_no_recipe_jsonld():
    html = """<html><body>
    <script type="application/ld+json">
    {"@type": "Article", "name": "Best Cocktails"}
    </script>
    """ + "<p>content</p>" * 500 + "</body></html>"
    result = classify_drink(html)
    assert result is None


def test_classify_drink_no_jsonld_at_all():
    html = "<html><body>" + "<p>content</p>" * 500 + "</body></html>"
    result = classify_drink(html)
    assert result is None


def test_classify_drink_spirit_in_food_is_not_drink():
    """A food recipe with a spirit name in keywords should NOT be classified as drink."""
    body = "<p>A delicious glazed dish.</p>\n" * 40
    html = """<!DOCTYPE html>
<html><body>
""" + body + """<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Bourbon Glazed Ribs",
    "recipeCategory": "Dinner, BBQ",
    "keywords": "bourbon, ribs, bbq, grilled"
}
</script>
</body></html>"""
    result = classify_drink(html)
    assert result == "confirmed_food"
```

- [x] **Step 3: Run tests to verify they fail**

Run: `pytest scraper/tests/test_validate.py::test_classify_drink_from_category -v`
Expected: FAIL — cannot import `classify_drink`

- [x] **Step 4: Implement classify_drink**

In `scraper/src/validate.py`, add `DRINK_TERMS` near the top (after the existing constants) and the `classify_drink` function:

```python
DRINK_TERMS = {
    # drink types / categories
    "cocktail", "cocktails", "drink", "drinks", "drinking",
    "beverage", "beverages", "mixed drink",
    # cocktail families and styles
    "highball", "lowball", "aperitif", "aperitivo", "digestif",
    "nightcap", "spritz", "sour", "fizz", "flip", "toddy",
    "grog", "sangria", "shooter", "shot", "punch",
    "martini", "margarita", "daiquiri", "mojito", "negroni",
    "colada", "mule", "smash", "swizzle", "cobbler",
    "rickey", "julep", "bellini", "mimosa", "paloma",
}


def _check_terms(value: str) -> bool:
    """Check if any DRINK_TERMS appear in a comma-separated metadata value."""
    for segment in value.lower().split(","):
        segment = segment.strip()
        if any(term in segment for term in DRINK_TERMS):
            return True
    return False


def _extract_breadcrumb_names(recipe: dict) -> list[str]:
    """Extract breadcrumb item names from a Recipe JSON-LD object."""
    mep = recipe.get("mainEntityOfPage", {})
    if not isinstance(mep, dict):
        return []
    bc = mep.get("breadcrumb", {})
    if not isinstance(bc, dict):
        return []
    items = bc.get("itemListElement", [])
    names = []
    for item in items:
        if isinstance(item, dict):
            inner = item.get("item", {})
            if isinstance(inner, dict):
                name = inner.get("name", "")
                if name:
                    names.append(name)
            elif isinstance(inner, str):
                names.append(inner)
    return names


def classify_drink(html: str) -> str | None:
    """Classify a fetched page as confirmed_drink, confirmed_food, or None (no Recipe JSON-LD).

    Checks recipeCategory, breadcrumb, and keywords against DRINK_TERMS.
    Returns None if no Recipe JSON-LD is found at all.
    """
    recipes = []
    for obj in _iter_jsonld_objects(html):
        obj_type = obj.get("@type", "")
        if isinstance(obj_type, list):
            type_str = " ".join(obj_type)
        else:
            type_str = obj_type
        if "Recipe" in type_str:
            recipes.append(obj)

    if not recipes:
        return None

    for recipe in recipes:
        # Check recipeCategory
        category = recipe.get("recipeCategory", "")
        if isinstance(category, list):
            category = ", ".join(category)
        if category and _check_terms(category):
            return "confirmed_drink"

        # Check breadcrumb
        bc_names = _extract_breadcrumb_names(recipe)
        for name in bc_names:
            if _check_terms(name):
                return "confirmed_drink"

        # Check keywords
        keywords = recipe.get("keywords", "")
        if isinstance(keywords, list):
            keywords = ", ".join(keywords)
        if keywords and _check_terms(keywords):
            return "confirmed_drink"

    return "confirmed_food"
```

- [x] **Step 5: Update the import in test_validate.py**

In `scraper/tests/test_validate.py`, update the existing import line at the top:

```python
from scraper.src.validate import validate, ValidationResult, classify_drink
```

- [x] **Step 6: Run all classify_drink tests**

Run: `pytest scraper/tests/test_validate.py -k classify_drink -v`
Expected: All 7 tests PASS

- [x] **Step 7: Run full validate test suite**

Run: `pytest scraper/tests/test_validate.py -v`
Expected: All tests pass (existing tests unaffected)

- [x] **Step 8: Commit**

```bash
git add scraper/src/validate.py scraper/tests/test_validate.py scraper/tests/conftest.py
git commit -m "Add classify_drink function with DRINK_TERMS checking"
```

---

### Task 5: Wire drink classification into fetch pipeline

**Files:**
- Modify: `scraper/src/fetch.py`
- Test: `scraper/tests/test_fetch.py`
- Modify: `scraper/tests/conftest.py`

- [x] **Step 1: Write failing test — fetch only processes likely_drink_recipe rows**

In `scraper/tests/test_fetch.py`, add:

```python
def test_fetch_pages_only_fetches_likely_drink_recipe(tmp_db, tmp_path, sample_drink_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.add_url("testsite", "https://example.com/recipes/salmon")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
    db.set_content_type("https://example.com/recipes/salmon", "likely_food_recipe")

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_drink_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    # Only the margarita should have been fetched
    assert mock_client.fetch.call_count == 1
    mock_client.fetch.assert_called_once_with("https://example.com/recipes/margarita")
    db.close()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest scraper/tests/test_fetch.py::test_fetch_pages_only_fetches_likely_drink_recipe -v`
Expected: FAIL — both URLs are fetched (call_count == 2)

- [x] **Step 3: Update fetch_pages to default to likely_drink_recipe filter**

In `scraper/src/fetch.py`, update the `fetch_pages` function. Change the `pending` line:

```python
def fetch_pages(
    db: Database,
    client: ScraperAPIClient,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    limit: int | None = None,
    force_site: str | None = None,
    delay: float = 1.5,
) -> dict:
    pending = db.get_pending(site=site or force_site, limit=limit, content_type="likely_drink_recipe")
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest scraper/tests/test_fetch.py::test_fetch_pages_only_fetches_likely_drink_recipe -v`
Expected: PASS

- [x] **Step 5: Fix existing fetch tests that now get no results**

The existing tests in `test_fetch.py` add URLs without setting `content_type`, so `get_pending(content_type="likely_drink_recipe")` returns nothing. Update each test that calls `fetch_pages` with actual fetching to set `content_type` after `add_url`. The tests to update are:

`test_fetch_pages_marks_recipe` — after `add_url`, add:
```python
db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
```

`test_fetch_pages_marks_blocked` — after `add_url`, add:
```python
db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
```

`test_fetch_pages_handles_network_error` — after `add_url`, add:
```python
db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")
```

`test_fetch_pages_respects_limit` — after the `add_url` loop, add:
```python
for i in range(10):
    db.set_content_type(f"https://example.com/recipes/{i}", "likely_drink_recipe")
```

`test_fetch_pages_circuit_breaker_pauses_site` — after adding pending pages for badsite (the `range(15, 20)` loop), add:
```python
for i in range(15, 20):
    db.set_content_type(f"https://bad.com/recipes/{i}", "likely_drink_recipe")
```
And after adding the goodsite URL, add:
```python
db.set_content_type("https://good.com/recipes/1", "likely_drink_recipe")
```

- [x] **Step 6: Run all fetch tests**

Run: `pytest scraper/tests/test_fetch.py -v`
Expected: All tests pass

- [x] **Step 7: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py
git commit -m "Filter fetch to likely_drink_recipe rows only"
```

---

### Task 6: Call classify_drink after fetch and update content_type

**Files:**
- Modify: `scraper/src/fetch.py`
- Test: `scraper/tests/test_fetch.py`

- [x] **Step 1: Write failing test — fetch confirms drink via JSON-LD**

In `scraper/tests/test_fetch.py`, add:

```python
def test_fetch_pages_confirms_drink(tmp_db, tmp_path, sample_drink_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_drink_recipe_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/margarita",),
    ).fetchone()
    assert row["content_type"] == "confirmed_drink"
    db.close()


def test_fetch_pages_confirms_food(tmp_db, tmp_path, sample_food_recipe_html):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/salmon")
    db.set_content_type("https://example.com/recipes/salmon", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.fetch.return_value = sample_food_recipe_html

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/salmon",),
    ).fetchone()
    assert row["content_type"] == "confirmed_food"
    db.close()


def test_fetch_pages_leaves_likely_drink_when_no_recipe_jsonld(tmp_db, tmp_path):
    """When the page has no Recipe JSON-LD, content_type stays likely_drink_recipe."""
    body = "<p>content</p>\n" * 200
    html_no_recipe = """<!DOCTYPE html>
<html><head><title>Some Page</title></head><body>
""" + body + """<script type="application/ld+json">
{"@type": "Article", "name": "About Cocktails"}
</script></body></html>"""

    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/article")
    db.set_content_type("https://example.com/recipes/article", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.fetch.return_value = html_no_recipe

    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    row = db.conn.execute(
        "SELECT content_type FROM pages WHERE url = ?",
        ("https://example.com/recipes/article",),
    ).fetchone()
    assert row["content_type"] == "likely_drink_recipe"
    db.close()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest scraper/tests/test_fetch.py::test_fetch_pages_confirms_drink scraper/tests/test_fetch.py::test_fetch_pages_confirms_food -v`
Expected: FAIL — `content_type` is still `likely_drink_recipe`

- [x] **Step 3: Add classify_drink call to fetch_pages**

In `scraper/src/fetch.py`, add the import at the top:

```python
from scraper.src.validate import validate, classify_drink
```

(Replace the existing `from scraper.src.validate import validate` line.)

Then in the `fetch_pages` function, in the `else` branch (after `result.status != "blocked"`), after the `db.mark_content(...)` call, add:

```python
        else:
            filename = url_to_filename(url)
            rel_path = save_html(html_dir, page_site, filename, html)
            db.mark_content(url, result.status, result.reason or result.status, html_path=rel_path)
            results[result.status] = results.get(result.status, 0) + 1
            print(f"  {result.status}: {result.reason}")

            # Classify drink/food from JSON-LD
            drink_result = classify_drink(html)
            if drink_result:
                db.set_content_type(url, drink_result)
```

- [x] **Step 4: Run all three new tests**

Run: `pytest scraper/tests/test_fetch.py::test_fetch_pages_confirms_drink scraper/tests/test_fetch.py::test_fetch_pages_confirms_food scraper/tests/test_fetch.py::test_fetch_pages_leaves_likely_drink_when_no_recipe_jsonld -v`
Expected: All 3 PASS

- [x] **Step 5: Run full test suite**

Run: `pytest scraper/tests/ -v`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py scraper/tests/conftest.py
git commit -m "Classify drink/food from JSON-LD after fetch"
```

---

### Task 7: Delete existing database

**Files:**
- None (operational step)

- [x] **Step 1: Delete the existing scraper.db so it gets recreated with the new schema**

```bash
rm -f data/scraper.db
```

- [x] **Step 2: Verify the database can be recreated**

```bash
python3 -c "from scraper.src.db import Database; db = Database('data/scraper.db'); print('OK'); db.close()"
```

Expected: `OK`

- [x] **Step 3: Verify content_type column exists**

```bash
python3 -c "
from scraper.src.db import Database
db = Database('data/scraper.db')
row = db.conn.execute('PRAGMA table_info(pages)').fetchall()
cols = [r[1] for r in row]
assert 'content_type' in cols, f'Missing content_type, got {cols}'
print('Schema OK:', cols)
db.close()
"
```

Expected: Schema OK with `content_type` in the list

- [x] **Step 4: Delete the recreated empty db (discovery will create it fresh)**

```bash
rm -f data/scraper.db
```

- [x] **Step 5: Commit (no files changed — this is just cleanup)**

No commit needed — no source files changed.
