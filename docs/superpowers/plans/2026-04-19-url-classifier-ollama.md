# URL Classifier via Local Ollama Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python -m scraper.src.classify` which reads `content_type IS NULL` rows from `data/scraper.db`, classifies each URL via local `qwen3:14b` on ollama into one of six labels, and writes results back to the DB plus an audit sidecar table.

**Architecture:** New `classify` CLI mirroring the shape of existing `discover`/`fetch` modules. Ollama access via the `ollama` Python package (AsyncClient) against `http://localhost:11434`. Structured output via ollama's JSON schema `format` parameter constrains the response to one of six enum labels. A small asyncio worker pool (default concurrency 4) pulls rows from a queue, each worker calls ollama, and results are written to a new `classifications` sidecar table plus `pages.content_type`.

**Tech Stack:** Python 3.11, `ollama` python package (new dep), `sqlite3` (stdlib), `asyncio` (stdlib), `pytest` + `pytest-asyncio` for tests.

Full design: [docs/superpowers/specs/2026-04-19-url-classifier-ollama-design.md](../specs/2026-04-19-url-classifier-ollama-design.md)

---

## File Structure

**Create:**
- `scraper/src/classify.py` — CLI + orchestration (main run, review, sample subcommands)
- `scraper/src/classify_prompt.py` — system prompt string, few-shot examples, label enum, `PROMPT_VERSION` constant
- `scraper/src/ollama_client.py` — thin async wrapper calling ollama with structured output
- `scraper/eval/classify-urls.jsonl` — hand-labeled eval set for `--review` mode
- `scraper/tests/test_classify_prompt.py` — assertions on prompt constants
- `scraper/tests/test_ollama_client.py` — ollama wrapper tests (mocked)
- `scraper/tests/test_classify.py` — orchestration tests (mocked ollama)

**Modify:**
- `scraper/src/db.py` — add `classifications` table, `record_classification()`, `get_unclassified()`, `sample_classifications()`
- `scraper/tests/test_db.py` — tests for the new DB methods
- `scraper/pyproject.toml` — add `ollama` dependency, add `pytest-asyncio` dev dependency
- `CLAUDE.md` — add "URL classifier" section with install + usage

---

## Task 1: Add `classifications` sidecar table to DB

**Files:**
- Modify: `scraper/src/db.py`
- Modify: `scraper/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `scraper/tests/test_db.py`:

```python
def test_schema_has_classifications_table(tmp_db):
    db = Database(tmp_db)
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='classifications'"
    ).fetchall()
    assert len(rows) == 1
    cols = db.conn.execute("PRAGMA table_info(classifications)").fetchall()
    col_names = {r[1] for r in cols}
    assert {"id", "page_id", "label", "model", "prompt_version", "raw_response", "latency_ms", "created_at"} <= col_names
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scraper && uv run pytest tests/test_db.py::test_schema_has_classifications_table -v`
Expected: FAIL with "no such table: classifications"

- [ ] **Step 3: Add the table to Database.__init__**

In `scraper/src/db.py`, add a new module constant after `CREATE_INDEXES`:

```python
CREATE_CLASSIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    label TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    raw_response TEXT,
    latency_ms INTEGER,
    created_at TEXT NOT NULL
);
"""

CREATE_CLASSIFICATIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_classifications_page_id ON classifications(page_id);",
    "CREATE INDEX IF NOT EXISTS idx_classifications_label ON classifications(label);",
]
```

Then in `Database.__init__`, after the existing index loop, add:

```python
            self.conn.execute(CREATE_CLASSIFICATIONS_TABLE)
            for idx in CREATE_CLASSIFICATIONS_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scraper && uv run pytest tests/test_db.py::test_schema_has_classifications_table -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "Add classifications sidecar table"
```

---

## Task 2: DB method `record_classification()`

Writes one classification record AND updates `pages.content_type` in a single transaction so they can never drift.

**Files:**
- Modify: `scraper/src/db.py`
- Modify: `scraper/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `scraper/tests/test_db.py`:

```python
def test_record_classification_writes_both_tables(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    page_id = db.conn.execute("SELECT id FROM pages LIMIT 1").fetchone()["id"]

    db.record_classification(
        page_id=page_id,
        label="likely_drink_recipe",
        model="qwen3:14b",
        prompt_version="v1",
        raw_response='{"label": "likely_drink_recipe"}',
        latency_ms=423,
    )

    page = db.conn.execute("SELECT content_type FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert page["content_type"] == "likely_drink_recipe"

    clsf = db.conn.execute("SELECT * FROM classifications WHERE page_id = ?", (page_id,)).fetchone()
    assert clsf["label"] == "likely_drink_recipe"
    assert clsf["model"] == "qwen3:14b"
    assert clsf["prompt_version"] == "v1"
    assert clsf["raw_response"] == '{"label": "likely_drink_recipe"}'
    assert clsf["latency_ms"] == 423
    assert clsf["created_at"] is not None
    db.close()


def test_record_classification_allows_reclassification(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    page_id = db.conn.execute("SELECT id FROM pages LIMIT 1").fetchone()["id"]

    db.record_classification(page_id, "likely_drink_recipe", "qwen3:14b", "v1", "{}", 100)
    db.record_classification(page_id, "likely_food_recipe", "qwen3:14b", "v2", "{}", 100)

    rows = db.conn.execute("SELECT label, prompt_version FROM classifications WHERE page_id = ? ORDER BY id", (page_id,)).fetchall()
    assert [(r["label"], r["prompt_version"]) for r in rows] == [
        ("likely_drink_recipe", "v1"),
        ("likely_food_recipe", "v2"),
    ]
    page = db.conn.execute("SELECT content_type FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert page["content_type"] == "likely_food_recipe"
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_db.py -k record_classification -v`
Expected: FAIL with AttributeError on `record_classification`

- [ ] **Step 3: Implement `record_classification`**

Add to the `Database` class in `scraper/src/db.py`:

```python
    def record_classification(
        self,
        page_id: int,
        label: str,
        model: str,
        prompt_version: str,
        raw_response: str | None,
        latency_ms: int | None,
    ):
        """Insert an audit record and update pages.content_type atomically."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "INSERT INTO classifications (page_id, label, model, prompt_version, raw_response, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (page_id, label, model, prompt_version, raw_response, latency_ms, now),
            )
            self.conn.execute(
                "UPDATE pages SET content_type = ? WHERE id = ?",
                (label, page_id),
            )
            self.conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_db.py -k record_classification -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "DB: record_classification writes audit row + updates pages.content_type"
```

---

## Task 3: DB method `get_unclassified()`

Returns rows with `content_type IS NULL`, site-filterable, limit-able. This is the work queue for the main classify run.

**Files:**
- Modify: `scraper/src/db.py`
- Modify: `scraper/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `scraper/tests/test_db.py`:

```python
def test_get_unclassified_returns_null_content_type(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_a", "https://a.com/2")
    db.add_url("site_b", "https://b.com/1")
    db.set_content_type("https://a.com/1", "likely_drink_recipe")

    rows = db.get_unclassified()
    urls = sorted(r["url"] for r in rows)
    assert urls == ["https://a.com/2", "https://b.com/1"]
    db.close()


def test_get_unclassified_filters_by_site(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_b", "https://b.com/1")
    rows = db.get_unclassified(site="site_a")
    assert len(rows) == 1
    assert rows[0]["site"] == "site_a"
    db.close()


def test_get_unclassified_respects_limit(tmp_db):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified(limit=3)
    assert len(rows) == 3
    db.close()


def test_get_unclassified_includes_sitemap_source_and_id(tmp_db):
    db = Database(tmp_db)
    db.add_urls_batch("testsite", ["https://example.com/1"], sitemap_source="recipes.xml")
    rows = db.get_unclassified()
    assert rows[0]["sitemap_source"] == "recipes.xml"
    assert isinstance(rows[0]["id"], int)
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_db.py -k get_unclassified -v`
Expected: FAIL with AttributeError on `get_unclassified`

- [ ] **Step 3: Implement `get_unclassified`**

Add to the `Database` class in `scraper/src/db.py`:

```python
    def get_unclassified(self, site: str | None = None, limit: int | None = None) -> list[dict]:
        query = "SELECT id, site, url, sitemap_source FROM pages WHERE content_type IS NULL"
        params: list = []
        if site:
            query += " AND site = ?"
            params.append(site)
        query += " ORDER BY id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_db.py -k get_unclassified -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "DB: get_unclassified as the classifier's work queue"
```

---

## Task 4: DB method `sample_classifications()`

Backing method for the `--sample` subcommand. Joins `classifications` with `pages` and returns N random rows with the raw model response.

**Files:**
- Modify: `scraper/src/db.py`
- Modify: `scraper/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `scraper/tests/test_db.py`:

```python
def test_sample_classifications_returns_joined_rows(tmp_db):
    db = Database(tmp_db)
    for i in range(3):
        db.add_url("site_a", f"https://a.com/{i}")
    page_ids = [r["id"] for r in db.conn.execute("SELECT id FROM pages ORDER BY id").fetchall()]
    for pid in page_ids:
        db.record_classification(pid, "likely_drink_recipe", "qwen3:14b", "v1", '{"label":"likely_drink_recipe"}', 100)

    rows = db.sample_classifications(site="site_a", label="likely_drink_recipe", n=2)
    assert len(rows) == 2
    assert {r["url"] for r in rows} <= {"https://a.com/0", "https://a.com/1", "https://a.com/2"}
    assert rows[0]["label"] == "likely_drink_recipe"
    assert rows[0]["raw_response"] == '{"label":"likely_drink_recipe"}'
    db.close()


def test_sample_classifications_scopes_by_site_and_label(tmp_db):
    db = Database(tmp_db)
    db.add_url("site_a", "https://a.com/1")
    db.add_url("site_b", "https://b.com/1")
    a_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://a.com/1",)).fetchone()["id"]
    b_id = db.conn.execute("SELECT id FROM pages WHERE url = ?", ("https://b.com/1",)).fetchone()["id"]
    db.record_classification(a_id, "likely_drink_recipe", "qwen3:14b", "v1", "{}", 100)
    db.record_classification(b_id, "likely_food_recipe", "qwen3:14b", "v1", "{}", 100)

    rows = db.sample_classifications(site="site_a", label="likely_drink_recipe", n=10)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://a.com/1"
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_db.py -k sample_classifications -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Implement `sample_classifications`**

Add to the `Database` class in `scraper/src/db.py`:

```python
    def sample_classifications(self, site: str, label: str, n: int = 10) -> list[dict]:
        """Return n random (url, label, raw_response) rows for a (site, label) pair.

        Returns the MOST RECENT classification per page, so re-classifications don't
        produce duplicates in the sample.
        """
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT p.url, c.label, c.raw_response, c.created_at
                FROM classifications c
                JOIN pages p ON p.id = c.page_id
                WHERE p.site = ? AND c.label = ?
                  AND c.id = (
                      SELECT MAX(id) FROM classifications WHERE page_id = c.page_id
                  )
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (site, label, n),
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_db.py -k sample_classifications -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "DB: sample_classifications for ad-hoc spot checks"
```

---

## Task 5: Add `ollama` package as a dependency

**Files:**
- Modify: `scraper/pyproject.toml`

- [ ] **Step 1: Add the dependencies**

In `scraper/pyproject.toml`, edit the `dependencies` list:

```toml
dependencies = [
    "requests>=2.31",
    "lxml>=5.0",
    "pyyaml>=6.0",
    "cssselect>=1.2",
    "python-dotenv>=1.0",
    "ollama>=0.4",
]
```

And edit the `dev` optional-dependencies list:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "responses>=0.25",
    "pytest-asyncio>=0.23",
]
```

- [ ] **Step 2: Add pytest-asyncio config**

In `scraper/pyproject.toml`, under `[tool.pytest.ini_options]`, append:

```toml
asyncio_mode = "auto"
```

So the block becomes:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Sync dependencies**

Run: `cd scraper && uv sync --extra dev`
Expected: succeeds, ollama and pytest-asyncio installed.

- [ ] **Step 4: Sanity-check existing tests still pass**

Run: `cd scraper && uv run pytest -q`
Expected: all existing tests still green.

- [ ] **Step 5: Commit**

```bash
git add scraper/pyproject.toml scraper/uv.lock
git commit -m "Add ollama and pytest-asyncio dependencies"
```

---

## Task 6: Create the prompt module

A small module with the constants `LABELS`, `PROMPT_VERSION`, `SYSTEM_PROMPT`, `RESPONSE_SCHEMA`, and a helper to build the user message. Kept separate so the CLI and tests reference the exact same string.

**Files:**
- Create: `scraper/src/classify_prompt.py`
- Create: `scraper/tests/test_classify_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `scraper/tests/test_classify_prompt.py`:

```python
from scraper.src.classify_prompt import (
    LABELS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_message,
)


def test_labels_are_the_six_known_values():
    assert LABELS == (
        "likely_drink_recipe",
        "likely_food_recipe",
        "likely_drink_article",
        "likely_food_article",
        "likely_junk",
        "likely_user_generated",
    )


def test_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


def test_response_schema_constrains_label_to_the_labels_enum():
    assert RESPONSE_SCHEMA["type"] == "object"
    assert RESPONSE_SCHEMA["required"] == ["label"]
    assert set(RESPONSE_SCHEMA["properties"]["label"]["enum"]) == set(LABELS)


def test_system_prompt_mentions_every_label_name():
    for lbl in LABELS:
        assert lbl in SYSTEM_PROMPT


def test_system_prompt_contains_at_least_one_failure_mode_example():
    # If future refactors accidentally drop the few-shots, this catches it.
    assert "household-uses-for-vodka" in SYSTEM_PROMPT
    assert "pineapple-upside-down-cake" in SYSTEM_PROMPT


def test_build_user_message_formats_url_and_sitemap():
    msg = build_user_message("https://example.com/recipe/1", "recipes.xml")
    assert "https://example.com/recipe/1" in msg
    assert "recipes.xml" in msg


def test_build_user_message_handles_null_sitemap():
    msg = build_user_message("https://example.com/recipe/1", None)
    assert "https://example.com/recipe/1" in msg
    # Must not crash or emit the literal "None"
    assert "None" not in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_classify_prompt.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Create the prompt module**

Create `scraper/src/classify_prompt.py`:

```python
"""Prompt constants for the URL classifier. Kept isolated so prompt iteration
means editing one file and bumping PROMPT_VERSION."""

PROMPT_VERSION = "v1"

LABELS = (
    "likely_drink_recipe",
    "likely_food_recipe",
    "likely_drink_article",
    "likely_food_article",
    "likely_junk",
    "likely_user_generated",
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": list(LABELS),
        }
    },
    "required": ["label"],
}

SYSTEM_PROMPT = """You classify a URL into exactly one of six categories by reading the URL like English. Do not match keywords in the slug — read it as a sentence and decide what the page at that URL is most likely to be.

Categories:
- likely_drink_recipe: an individual drink recipe (alcoholic or non-alcoholic). A single drink name, with a mixing method or drink ingredients.
- likely_food_recipe: an individual food recipe. A single dish, with a cooking method or food ingredients.
- likely_drink_article: drink-related editorial that is NOT a single recipe — listicles, bar guides, "best-of" roundups, technique explainers, news, glossary entries, ingredient explainers, series landing pages.
- likely_food_article: food-related editorial that is NOT a single recipe — tips, restaurant guides, health pieces, cooking technique explainers, reviews.
- likely_junk: structural/meta/commercial pages with no editorial content. This includes about/FAQ/privacy/contact/terms/sitemap pages, author bios, tag/category/topic indexes, brand pages, retail/affiliate/shop pages, product reviews, advertise/subscribe pages, and bare section indexes like /recipes/.
- likely_user_generated: user-submitted content from a community or forum sitemap. Guest authors are editorial and do NOT belong here.

Rules:
- Read the slug as a sentence. "household-uses-for-vodka" is NOT a recipe just because it contains "vodka".
- The URL path matters: a root-level slug is usually an article or landing page even on a recipe-heavy site.
- If a bare section index like /recipes/ is the URL, that is likely_junk (navigation hub), not a recipe.
- Sitemap source is a hint, not a rule — a URL under a "recipes" sitemap can still be an article.
- When genuinely torn between drink and food, lean drink. When torn between recipe and article, lean recipe.

Examples:
URL: https://marthastewart.com/household-uses-for-vodka
Sitemap: articles-sitemap.xml
Answer: likely_drink_article   (article about uses for vodka, not a recipe)

URL: https://marthastewart.com/what-drinking-milk-every-day-does-to-your-body
Sitemap: articles-sitemap.xml
Answer: likely_food_article   (health article — "drinking" is not a drink signal)

URL: https://simplyrecipes.com/best-gin-for-negroni-bartenders
Sitemap: sitemap-articles.xml
Answer: likely_drink_article   (buyers' roundup, not a recipe)

URL: https://simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe
Sitemap: sitemap-recipes.xml
Answer: likely_food_recipe   ("lime" is not a drink signal)

URL: https://liquor.com/recipes/spiked-hot-chocolate/
Sitemap: sitemap-recipes.xml
Answer: likely_drink_recipe   (drink despite "chocolate" in slug)

URL: https://liquor.com/recipes/pineapple-upside-down-cake/
Sitemap: sitemap-recipes.xml
Answer: likely_food_recipe   (cake even though path is /recipes/ on a drinks site)

URL: https://simplyrecipes.com/trader-joes-cocktail-shaker-review
Sitemap: sitemap-articles.xml
Answer: likely_junk   (product review — "cocktail" is a distractor)

URL: https://punchdrink.com/recipes/
Sitemap: sitemap.xml
Answer: likely_junk   (bare section index is a navigation hub)

URL: https://punchdrink.com/spirit-forward/
Sitemap: sitemap.xml
Answer: likely_drink_article   (root-level series landing page)

Return JSON of the form {"label": "<one of the six labels>"}. Return only one label."""


def build_user_message(url: str, sitemap_source: str | None) -> str:
    """The per-URL user message. Uniform structure so the model has no latitude."""
    sitemap = sitemap_source if sitemap_source else "(none)"
    return f"URL: {url}\nSitemap: {sitemap}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify_prompt.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/classify_prompt.py scraper/tests/test_classify_prompt.py
git commit -m "Add classify_prompt module (system prompt + few-shots + label schema)"
```

---

## Task 7: Ollama client wrapper — happy path

Thin async wrapper that calls ollama with structured output and returns `(label, raw_response, latency_ms)`.

**Files:**
- Create: `scraper/src/ollama_client.py`
- Create: `scraper/tests/test_ollama_client.py`

- [ ] **Step 1: Write the failing test**

Create `scraper/tests/test_ollama_client.py`:

```python
from unittest.mock import AsyncMock, patch

import pytest

from scraper.src.ollama_client import ClassificationResult, classify_url


@pytest.fixture
def fake_ollama_response():
    return {
        "message": {
            "role": "assistant",
            "content": '{"label": "likely_drink_recipe"}',
        },
        "done": True,
    }


async def test_classify_url_returns_parsed_label(fake_ollama_response):
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=fake_ollama_response)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        result = await classify_url(
            url="https://example.com/recipe/1",
            sitemap_source="recipes.xml",
            model="qwen3:14b",
        )

    assert isinstance(result, ClassificationResult)
    assert result.label == "likely_drink_recipe"
    assert result.raw_response == '{"label": "likely_drink_recipe"}'
    assert result.latency_ms >= 0


async def test_classify_url_sends_system_and_user_messages(fake_ollama_response):
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=fake_ollama_response)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        await classify_url("https://example.com/x", "s.xml", "qwen3:14b")

    call = mock_client.chat.await_args
    kwargs = call.kwargs
    assert kwargs["model"] == "qwen3:14b"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "https://example.com/x" in messages[1]["content"]
    assert kwargs["format"]["type"] == "object"


async def test_classify_url_raises_on_invalid_label():
    bad = {"message": {"content": '{"label": "not_a_real_label"}'}, "done": True}
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=bad)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="invalid label"):
            await classify_url("https://example.com/x", None, "qwen3:14b")


async def test_classify_url_raises_on_malformed_json():
    bad = {"message": {"content": "not json"}, "done": True}
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(return_value=bad)

    with patch("scraper.src.ollama_client.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="malformed"):
            await classify_url("https://example.com/x", None, "qwen3:14b")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_ollama_client.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Create the client module**

Create `scraper/src/ollama_client.py`:

```python
"""Thin async wrapper around ollama's chat API for URL classification.

One request per URL. Structured output via the `format` parameter prevents
malformed responses; the model can only return JSON matching RESPONSE_SCHEMA."""

import json
import time
from dataclasses import dataclass

from ollama import AsyncClient

from scraper.src.classify_prompt import (
    LABELS,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_user_message,
)


@dataclass
class ClassificationResult:
    label: str
    raw_response: str
    latency_ms: int


async def classify_url(
    url: str,
    sitemap_source: str | None,
    model: str,
    host: str | None = None,
) -> ClassificationResult:
    """Ask ollama to classify one URL. Returns ClassificationResult or raises.

    Raises ValueError for malformed or out-of-enum responses. Transport errors
    bubble up from the ollama library unchanged so the caller can decide
    retry policy.
    """
    client = AsyncClient(host=host) if host else AsyncClient()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(url, sitemap_source)},
    ]
    start = time.monotonic()
    resp = await client.chat(
        model=model,
        messages=messages,
        format=RESPONSE_SCHEMA,
        options={"temperature": 0, "num_predict": 50},
        think=False,
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    raw = resp["message"]["content"]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON from model: {raw!r}") from e

    label = payload.get("label")
    if label not in LABELS:
        raise ValueError(f"invalid label {label!r} (raw={raw!r})")

    return ClassificationResult(label=label, raw_response=raw, latency_ms=latency_ms)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_ollama_client.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/ollama_client.py scraper/tests/test_ollama_client.py
git commit -m "Ollama client wrapper (async, structured output, enum-constrained)"
```

---

## Task 8: Orchestration core — single-URL sync path

The pure orchestration logic: given one unclassified row and a classify function, call it and record the result. This is the unit the async pool will wrap.

**Files:**
- Create: `scraper/src/classify.py`
- Create: `scraper/tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

Create `scraper/tests/test_classify.py`:

```python
from unittest.mock import AsyncMock

import pytest

from scraper.src.classify import classify_one
from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult


async def test_classify_one_records_successful_result(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_drink_recipe",
        raw_response='{"label": "likely_drink_recipe"}',
        latency_ms=123,
    ))

    await classify_one(
        row=row,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version="v1",
    )

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] == "likely_drink_recipe"
    clsf = db.conn.execute("SELECT label, model, prompt_version, raw_response FROM classifications").fetchone()
    assert clsf["label"] == "likely_drink_recipe"
    assert clsf["model"] == "qwen3:14b"
    assert clsf["prompt_version"] == "v1"
    db.close()


async def test_classify_one_passes_url_and_sitemap_to_fn(tmp_db):
    db = Database(tmp_db)
    db.add_urls_batch("testsite", ["https://example.com/r"], sitemap_source="recipes.xml")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_food_recipe", raw_response="{}", latency_ms=10,
    ))

    await classify_one(row=row, classify_fn=fake_classify, db=db, model="m", prompt_version="v")

    fake_classify.assert_awaited_once()
    kwargs = fake_classify.await_args.kwargs
    assert kwargs["url"] == "https://example.com/r"
    assert kwargs["sitemap_source"] == "recipes.xml"
    assert kwargs["model"] == "m"
    db.close()


async def test_classify_one_leaves_row_unclassified_on_error(tmp_db):
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipe/1")
    row = db.get_unclassified()[0]

    fake_classify = AsyncMock(side_effect=ValueError("malformed"))

    # Must not raise — errors are swallowed, logged, and the row stays NULL.
    await classify_one(row=row, classify_fn=fake_classify, db=db, model="m", prompt_version="v")

    page = db.conn.execute("SELECT content_type FROM pages").fetchone()
    assert page["content_type"] is None
    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
    assert clsf_count == 0
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: FAIL with ImportError on `classify_one`.

- [ ] **Step 3: Create classify.py with `classify_one`**

Create `scraper/src/classify.py`:

```python
"""URL classifier: main runner, review mode, and sample subcommand.

Main run: asyncio pool of workers pulling unclassified rows, classifying each
via ollama, writing back to pages.content_type + classifications audit table.
"""

import logging
from typing import Awaitable, Callable

from scraper.src.db import Database
from scraper.src.ollama_client import ClassificationResult

log = logging.getLogger(__name__)

ClassifyFn = Callable[..., Awaitable[ClassificationResult]]


async def classify_one(
    row: dict,
    classify_fn: ClassifyFn,
    db: Database,
    model: str,
    prompt_version: str,
) -> None:
    """Classify one row. Errors are logged and the row is left unclassified
    so a future run will retry it."""
    try:
        result = await classify_fn(
            url=row["url"],
            sitemap_source=row.get("sitemap_source"),
            model=model,
        )
    except Exception as e:
        log.warning("classify failed for id=%s url=%s: %s", row["id"], row["url"], e)
        return

    db.record_classification(
        page_id=row["id"],
        label=result.label,
        model=model,
        prompt_version=prompt_version,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/classify.py scraper/tests/test_classify.py
git commit -m "Classify: single-URL orchestration with graceful error handling"
```

---

## Task 9: Async worker pool

Wraps `classify_one` in an asyncio semaphore-limited pool that runs through the work queue.

**Files:**
- Modify: `scraper/src/classify.py`
- Modify: `scraper/tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

Add to `scraper/tests/test_classify.py`:

```python
import asyncio

from scraper.src.classify import run_classify_pool


async def test_run_classify_pool_processes_all_rows(tmp_db):
    db = Database(tmp_db)
    for i in range(5):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified()

    fake_classify = AsyncMock(return_value=ClassificationResult(
        label="likely_drink_recipe", raw_response="{}", latency_ms=10,
    ))

    await run_classify_pool(
        rows=rows,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version="v1",
        concurrency=3,
    )

    count = db.conn.execute(
        "SELECT COUNT(*) FROM pages WHERE content_type = 'likely_drink_recipe'"
    ).fetchone()[0]
    assert count == 5
    assert fake_classify.await_count == 5
    db.close()


async def test_run_classify_pool_respects_concurrency_limit(tmp_db):
    db = Database(tmp_db)
    for i in range(10):
        db.add_url("testsite", f"https://example.com/{i}")
    rows = db.get_unclassified()

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def tracking_classify(url, sitemap_source, model):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return ClassificationResult(label="likely_junk", raw_response="{}", latency_ms=10)

    await run_classify_pool(
        rows=rows,
        classify_fn=tracking_classify,
        db=db,
        model="m",
        prompt_version="v",
        concurrency=3,
    )

    assert max_in_flight <= 3
    assert max_in_flight >= 2  # should actually parallelize
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_classify.py -k run_classify_pool -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `run_classify_pool`**

Add to `scraper/src/classify.py`:

```python
import asyncio


async def run_classify_pool(
    rows: list[dict],
    classify_fn: ClassifyFn,
    db: Database,
    model: str,
    prompt_version: str,
    concurrency: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Run classify_one over rows with at most `concurrency` in-flight calls.

    on_progress(done, total) is invoked after each row completes, so the CLI
    can render a progress bar without this module knowing anything about UI.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(rows)
    done = 0
    done_lock = asyncio.Lock()

    async def worker(r: dict):
        nonlocal done
        async with sem:
            await classify_one(r, classify_fn, db, model, prompt_version)
        async with done_lock:
            done += 1
            if on_progress:
                on_progress(done, total)

    await asyncio.gather(*(worker(r) for r in rows))
```

Also update the top-of-file imports and the type alias (add `import asyncio` at top if not already, and keep `Callable` + `Awaitable`). The existing imports already include `Callable` and `Awaitable` — only `asyncio` and the new `on_progress` type are new. Full updated import block:

```python
import asyncio
import logging
from typing import Awaitable, Callable
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/classify.py scraper/tests/test_classify.py
git commit -m "Classify: asyncio worker pool with concurrency limit"
```

---

## Task 10: Main CLI (`python -m scraper.src.classify`)

CLI entry point for the main run. Loads unclassified rows, drives the pool, prints progress.

**Files:**
- Modify: `scraper/src/classify.py`
- Modify: `scraper/tests/test_classify.py`

- [ ] **Step 1: Write a failing test for CLI argument parsing**

Add to `scraper/tests/test_classify.py`:

```python
from scraper.src.classify import build_arg_parser


def test_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.site is None
    assert args.limit is None
    assert args.concurrency == 4
    assert args.model == "qwen3:14b"
    assert args.review is False
    assert args.sample is False


def test_arg_parser_main_run_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--site", "liquor", "--limit", "100", "--concurrency", "8", "--model", "qwen3:32b"])
    assert args.site == "liquor"
    assert args.limit == 100
    assert args.concurrency == 8
    assert args.model == "qwen3:32b"


def test_arg_parser_sample_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--sample", "--site", "liquor", "--category", "likely_drink_recipe", "--n", "20"])
    assert args.sample is True
    assert args.site == "liquor"
    assert args.category == "likely_drink_recipe"
    assert args.n == 20


def test_arg_parser_review_flag():
    parser = build_arg_parser()
    args = parser.parse_args(["--review"])
    assert args.review is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_classify.py -k arg_parser -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add `build_arg_parser` and `main`**

Append to `scraper/src/classify.py`:

```python
import argparse
import sys
from pathlib import Path

from scraper.src.classify_prompt import PROMPT_VERSION
from scraper.src.ollama_client import classify_url

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="classify",
        description="Classify unclassified URLs in scraper.db via a local ollama model.",
    )
    p.add_argument("--site", help="Limit run to one site (matches pages.site).")
    p.add_argument("--limit", type=int, help="Stop after this many URLs (main run only).")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Concurrent in-flight ollama requests (default: 4).")
    p.add_argument("--model", default="qwen3:14b", help="Ollama model tag (default: qwen3:14b).")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to scraper.db.")
    p.add_argument("--review", action="store_true",
                   help="Run the prompt against the checked-in eval set instead of the DB.")
    p.add_argument("--sample", action="store_true",
                   help="Print N random (url, label, raw_response) rows for --site --category.")
    p.add_argument("--category", help="For --sample: which label to sample from.")
    p.add_argument("--n", type=int, default=10, help="For --sample: number of rows (default 10).")
    return p


def _progress(done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        pct = 100 * done / total if total else 0
        print(f"\r  {done}/{total} ({pct:.1f}%)", end="", flush=True)
        if done == total:
            print()


async def run_main(args: argparse.Namespace) -> int:
    db = Database(args.db)
    rows = db.get_unclassified(site=args.site, limit=args.limit)
    if not rows:
        print("No unclassified rows. Done.")
        db.close()
        return 0

    print(f"Classifying {len(rows)} rows via {args.model} "
          f"(concurrency={args.concurrency}, prompt={PROMPT_VERSION})")

    await run_classify_pool(
        rows=rows,
        classify_fn=classify_url,
        db=db,
        model=args.model,
        prompt_version=PROMPT_VERSION,
        concurrency=args.concurrency,
        on_progress=_progress,
    )

    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)

    if args.sample:
        return _run_sample(args)
    if args.review:
        return asyncio.run(_run_review(args))
    return asyncio.run(run_main(args))


def _run_sample(args: argparse.Namespace) -> int:
    # Implemented in Task 12.
    raise NotImplementedError("--sample is added in a later task")


async def _run_review(args: argparse.Namespace) -> int:
    # Implemented in Task 11.
    raise NotImplementedError("--review is added in a later task")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: all prior tests PLUS the four new `arg_parser` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/classify.py scraper/tests/test_classify.py
git commit -m "Classify: CLI entry point and main run loop"
```

---

## Task 11: Eval set + `--review` mode

Small hand-curated eval set so prompt iteration is measurable. Review mode runs the current prompt over it, prints a side-by-side of expected vs predicted, and reports pass/fail counts. No DB writes.

**Files:**
- Create: `scraper/eval/classify-urls.jsonl`
- Modify: `scraper/src/classify.py`
- Modify: `scraper/tests/test_classify.py`

- [ ] **Step 1: Create the eval set**

Create `scraper/eval/classify-urls.jsonl` with one JSON object per line. Start with the known failure-mode cases plus a handful of uncontroversial examples per label:

```jsonl
{"url": "https://marthastewart.com/household-uses-for-vodka", "sitemap_source": "articles-sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://marthastewart.com/what-drinking-milk-every-day-does-to-your-body", "sitemap_source": "articles-sitemap.xml", "expected": "likely_food_article"}
{"url": "https://marthastewart.com/marthas-flower-arranging-secrets", "sitemap_source": "articles-sitemap.xml", "expected": "likely_food_article"}
{"url": "https://simplyrecipes.com/best-gin-for-negroni-bartenders", "sitemap_source": "sitemap-articles.xml", "expected": "likely_drink_article"}
{"url": "https://simplyrecipes.com/coconut-poached-fish-with-ginger-and-lime-recipe", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_food_recipe"}
{"url": "https://simplyrecipes.com/blueberry-jello-mold-recipe", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_food_recipe"}
{"url": "https://simplyrecipes.com/dollar-tree-plastic-cocktail-shaker-review", "sitemap_source": "sitemap-articles.xml", "expected": "likely_junk"}
{"url": "https://simplyrecipes.com/trader-joes-cocktail-shaker-review", "sitemap_source": "sitemap-articles.xml", "expected": "likely_junk"}
{"url": "https://liquor.com/recipes/spiked-hot-chocolate/", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_drink_recipe"}
{"url": "https://liquor.com/recipes/pineapple-upside-down-cake/", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_food_recipe"}
{"url": "https://liquor.com/recipes/classic-margarita/", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_drink_recipe"}
{"url": "https://liquor.com/recipes/old-fashioned/", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_drink_recipe"}
{"url": "https://punchdrink.com/recipes/", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://punchdrink.com/spirit-forward/", "sitemap_source": "sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://punchdrink.com/articles/all-things-bitter-amaro-negronis-cocktail-recipes/", "sitemap_source": "sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://foodnetwork.com/tag/cookies", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://foodnetwork.com/author/giada-de-laurentiis", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://foodnetwork.com/about", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://foodnetwork.com/privacy-policy", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://thekitchn.com/how-to-stock-a-home-bar", "sitemap_source": "sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://bonappetit.com/recipe/grilled-salmon-with-lemon", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_food_recipe"}
{"url": "https://bonappetit.com/recipe/negroni", "sitemap_source": "sitemap-recipes.xml", "expected": "likely_drink_recipe"}
{"url": "https://diffordsguide.com/cocktails/recipe/1234/classic-martini", "sitemap_source": "sitemap.xml", "expected": "likely_drink_recipe"}
{"url": "https://seriouseats.com/best-chef-knife-review", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://seriouseats.com/glossary/chiffonade", "sitemap_source": "sitemap.xml", "expected": "likely_food_article"}
{"url": "https://imbibemagazine.com/glossary/aperol", "sitemap_source": "sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://imbibemagazine.com/subscribe", "sitemap_source": "sitemap.xml", "expected": "likely_junk"}
{"url": "https://imbibemagazine.com/news/craft-distilling-trends-2025", "sitemap_source": "sitemap.xml", "expected": "likely_drink_article"}
{"url": "https://foodandwine.com/community/recipes/123/grandmas-apple-pie", "sitemap_source": "user-generated-sitemap.xml", "expected": "likely_user_generated"}
{"url": "https://foodandwine.com/restaurants/best-new-chefs-2025", "sitemap_source": "sitemap.xml", "expected": "likely_food_article"}
```

- [ ] **Step 2: Write a failing test for review mode**

Add to `scraper/tests/test_classify.py`:

```python
from scraper.src.classify import load_eval_set, run_review


def test_load_eval_set_parses_jsonl(tmp_path):
    p = tmp_path / "eval.jsonl"
    p.write_text(
        '{"url": "https://a.com/1", "sitemap_source": "s.xml", "expected": "likely_drink_recipe"}\n'
        '{"url": "https://b.com/1", "sitemap_source": null, "expected": "likely_junk"}\n'
    )
    entries = load_eval_set(p)
    assert len(entries) == 2
    assert entries[0]["url"] == "https://a.com/1"
    assert entries[0]["expected"] == "likely_drink_recipe"
    assert entries[1]["sitemap_source"] is None


async def test_run_review_reports_pass_and_fail_counts(tmp_path, capsys):
    eval_path = tmp_path / "eval.jsonl"
    eval_path.write_text(
        '{"url": "https://a.com/1", "sitemap_source": null, "expected": "likely_drink_recipe"}\n'
        '{"url": "https://b.com/1", "sitemap_source": null, "expected": "likely_junk"}\n'
    )

    async def fake_classify(url, sitemap_source, model):
        # Correct for the first, wrong for the second.
        if url == "https://a.com/1":
            return ClassificationResult(label="likely_drink_recipe", raw_response="{}", latency_ms=1)
        return ClassificationResult(label="likely_drink_article", raw_response="{}", latency_ms=1)

    rc = await run_review(eval_path=eval_path, classify_fn=fake_classify, model="qwen3:14b")

    out = capsys.readouterr().out
    assert "1/2 correct" in out or "correct: 1" in out
    assert "https://b.com/1" in out  # failing row must be printed
    assert rc in (0, 1)  # 0 if all pass, 1 if any fail — implementation choice
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd scraper && uv run pytest tests/test_classify.py -k review -v`
Expected: FAIL with ImportError.

- [ ] **Step 4: Implement `load_eval_set`, `run_review`, wire `_run_review`**

In `scraper/src/classify.py`:

Add a module-level constant near the other path constants:

```python
DEFAULT_EVAL_PATH = Path(__file__).resolve().parent.parent / "eval" / "classify-urls.jsonl"
```

Add these functions (replace the existing placeholder `_run_review`):

```python
import json


def load_eval_set(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


async def run_review(
    eval_path: Path,
    classify_fn: ClassifyFn,
    model: str,
) -> int:
    entries = load_eval_set(eval_path)
    correct = 0
    failures: list[tuple[dict, str]] = []
    for e in entries:
        try:
            result = await classify_fn(
                url=e["url"], sitemap_source=e.get("sitemap_source"), model=model,
            )
            predicted = result.label
        except Exception as err:
            predicted = f"ERROR: {err}"
        expected = e["expected"]
        if predicted == expected:
            correct += 1
        else:
            failures.append((e, predicted))

    total = len(entries)
    print(f"{correct}/{total} correct ({100*correct/total:.1f}%)")
    if failures:
        print("\nFailures:")
        for e, predicted in failures:
            print(f"  {e['url']}")
            print(f"    expected:  {e['expected']}")
            print(f"    predicted: {predicted}")
    return 0 if correct == total else 1


async def _run_review(args: argparse.Namespace) -> int:
    return await run_review(
        eval_path=DEFAULT_EVAL_PATH, classify_fn=classify_url, model=args.model,
    )
```

Add `import json` to the top of the file (already imported transitively in earlier tasks — check before duplicating; if not imported, add it).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: all tests PASS including the two review tests.

- [ ] **Step 6: Commit**

```bash
git add scraper/src/classify.py scraper/tests/test_classify.py scraper/eval/classify-urls.jsonl
git commit -m "Classify: eval set + --review mode for prompt iteration"
```

---

## Task 12: `--sample` mode

Read-only inspection of classified rows for ad-hoc spot-checks. Wired to `Database.sample_classifications` from Task 4.

**Files:**
- Modify: `scraper/src/classify.py`
- Modify: `scraper/tests/test_classify.py`

- [ ] **Step 1: Write a failing test**

Add to `scraper/tests/test_classify.py`:

```python
from scraper.src.classify import run_sample


def test_run_sample_prints_matching_rows(tmp_db, capsys):
    db = Database(tmp_db)
    db.add_url("liquor", "https://liquor.com/recipes/negroni")
    db.add_url("liquor", "https://liquor.com/recipes/margarita")
    db.add_url("foodnetwork", "https://foodnetwork.com/recipes/salmon")

    ids = {r["url"]: r["id"] for r in db.conn.execute("SELECT id, url FROM pages").fetchall()}
    db.record_classification(ids["https://liquor.com/recipes/negroni"], "likely_drink_recipe", "qwen3:14b", "v1", "{}", 1)
    db.record_classification(ids["https://liquor.com/recipes/margarita"], "likely_drink_recipe", "qwen3:14b", "v1", "{}", 1)
    db.record_classification(ids["https://foodnetwork.com/recipes/salmon"], "likely_food_recipe", "qwen3:14b", "v1", "{}", 1)
    db.close()

    rc = run_sample(db_path=tmp_db, site="liquor", category="likely_drink_recipe", n=10)
    out = capsys.readouterr().out

    assert rc == 0
    assert "negroni" in out
    assert "margarita" in out
    assert "salmon" not in out  # different site
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scraper && uv run pytest tests/test_classify.py -k run_sample -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `run_sample` and wire `_run_sample`**

In `scraper/src/classify.py`, replace the placeholder `_run_sample` and add `run_sample`:

```python
def run_sample(db_path: str | Path, site: str, category: str, n: int = 10) -> int:
    if not site or not category:
        print("--sample requires both --site and --category", file=sys.stderr)
        return 2
    db = Database(db_path)
    rows = db.sample_classifications(site=site, label=category, n=n)
    db.close()
    if not rows:
        print(f"No classifications found for site={site} category={category}")
        return 0
    for r in rows:
        print(f"{r['url']}")
        print(f"    raw: {r['raw_response']}")
    return 0


def _run_sample(args: argparse.Namespace) -> int:
    return run_sample(db_path=args.db, site=args.site, category=args.category, n=args.n)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scraper && uv run pytest tests/test_classify.py -v`
Expected: all tests PASS including `run_sample`.

- [ ] **Step 5: Commit**

```bash
git add scraper/src/classify.py scraper/tests/test_classify.py
git commit -m "Classify: --sample for ad-hoc spot-checks"
```

---

## Task 13: End-to-end smoke test

Wire the DB + prompt + classify_one path together with a mocked ollama to verify nothing regressed during assembly. No new production code.

**Files:**
- Modify: `scraper/tests/test_classify.py`

- [ ] **Step 1: Write the integration test**

Add to `scraper/tests/test_classify.py`:

```python
from scraper.src.classify import run_classify_pool
from scraper.src.classify_prompt import PROMPT_VERSION


async def test_end_to_end_classify_run_with_mocked_ollama(tmp_db):
    db = Database(tmp_db)
    # A mix of labels and a pre-classified row that must NOT be revisited.
    db.add_url("liquor", "https://liquor.com/recipes/negroni")
    db.add_url("liquor", "https://liquor.com/tag/gin")
    db.add_url("liquor", "https://liquor.com/articles/home-bar-guide")
    db.set_content_type("https://liquor.com/recipes/negroni", "likely_drink_recipe")

    def fake_label_for(url):
        if "/tag/" in url:
            return "likely_junk"
        if "/articles/" in url:
            return "likely_drink_article"
        return "likely_drink_recipe"

    async def fake_classify(url, sitemap_source, model):
        return ClassificationResult(
            label=fake_label_for(url), raw_response="{}", latency_ms=5,
        )

    rows = db.get_unclassified()
    assert len(rows) == 2  # pre-classified row excluded

    await run_classify_pool(
        rows=rows,
        classify_fn=fake_classify,
        db=db,
        model="qwen3:14b",
        prompt_version=PROMPT_VERSION,
        concurrency=2,
    )

    labels = dict(db.conn.execute("SELECT url, content_type FROM pages").fetchall())
    assert labels["https://liquor.com/recipes/negroni"] == "likely_drink_recipe"
    assert labels["https://liquor.com/tag/gin"] == "likely_junk"
    assert labels["https://liquor.com/articles/home-bar-guide"] == "likely_drink_article"

    clsf_count = db.conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
    assert clsf_count == 2  # only the two new classifications, not the pre-existing row
    db.close()
```

- [ ] **Step 2: Run the test**

Run: `cd scraper && uv run pytest tests/test_classify.py::test_end_to_end_classify_run_with_mocked_ollama -v`
Expected: PASS.

- [ ] **Step 3: Run the full test suite**

Run: `cd scraper && uv run pytest -v`
Expected: all tests across all files PASS.

- [ ] **Step 4: Commit**

```bash
git add scraper/tests/test_classify.py
git commit -m "Classify: end-to-end integration test with mocked ollama"
```

---

## Task 14: Manual live smoke test against real ollama

A one-off sanity check before letting the tool loose on 521k URLs. Uses a `--limit 20` run against a disposable copy of the DB.

- [ ] **Step 1: Install ollama and pull the model (if not already)**

Run:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b
```

- [ ] **Step 2: Run review mode**

Run: `cd scraper && uv run python -m scraper.src.classify --review`
Expected: eval set runs; correct-count printed. Target ≥80% on the checked-in eval set. If accuracy is poor, iterate the prompt in `classify_prompt.py`, bump `PROMPT_VERSION`, and re-run until acceptable before moving on.

- [ ] **Step 3: Run a small main-mode batch against a copy of the DB**

Run:
```bash
cp data/scraper.db /tmp/scraper-smoke.db
cd scraper && uv run python -m scraper.src.classify \
  --db /tmp/scraper-smoke.db --site liquor --limit 20 --concurrency 4
```
Expected: progress prints, finishes, no errors.

- [ ] **Step 4: Spot-check with --sample**

Run:
```bash
cd scraper && uv run python -m scraper.src.classify \
  --db /tmp/scraper-smoke.db --sample --site liquor --category likely_drink_recipe --n 10
cd scraper && uv run python -m scraper.src.classify \
  --db /tmp/scraper-smoke.db --sample --site liquor --category likely_junk --n 10
```
Expected: printed rows look reasonable to a human reader. If results look wrong, stop here and iterate on the prompt before running against the real DB.

- [ ] **Step 5: No commit**

This step is validation, not a code change. No commit.

---

## Task 15: Update `CLAUDE.md` with install + usage

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a URL Classifier section**

Append to `CLAUDE.md` (do not edit the existing Pull Requests or mixin sections):

```markdown

## URL Classifier

The classifier lives at `scraper/src/classify.py`. It reads `content_type IS NULL` rows from `data/scraper.db`, sends each URL to a local ollama model, and writes the label back plus an audit row in the `classifications` table.

**One-time setup:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b
```

**Typical usage (from repo root):**
```bash
# Main run — classify all remaining NULL rows for a site.
cd scraper && uv run python -m scraper.src.classify --site liquor

# Prompt iteration — run against the checked-in eval set, no DB writes.
cd scraper && uv run python -m scraper.src.classify --review

# Ad-hoc spot-check after a run.
cd scraper && uv run python -m scraper.src.classify --sample --site liquor --category likely_drink_recipe --n 10
```

Prompt lives in `scraper/src/classify_prompt.py`. To iterate, edit the prompt, bump `PROMPT_VERSION`, and re-run `--review` until the eval set passes at an acceptable rate.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Docs: add URL Classifier section to CLAUDE.md"
```

---

## Spec Coverage Check

- [x] **Module `scraper/src/classify.py` with CLI flags `--site --limit --concurrency --model`** — Task 10.
- [x] **`--review` mode running against checked-in eval set** — Task 11.
- [x] **`--sample --site --category --n` ad-hoc command** — Task 12.
- [x] **Structured output via ollama `format` enum** — Task 6 (schema) + Task 7 (client wiring).
- [x] **Thinking mode off** — `think=False` in Task 7.
- [x] **Asyncio worker pool, default concurrency 4** — Task 9; wired in Task 10.
- [x] **No per-site audit in main run** — Task 10 prints only progress; no audit code added.
- [x] **`classifications` sidecar table with `page_id, label, model, prompt_version, raw_response, latency_ms, created_at`** — Task 1.
- [x] **Atomic write of label + audit row** — Task 2 (`record_classification` uses one transaction).
- [x] **Resumable via NULL filter** — Task 3 (`get_unclassified` only returns NULL rows; pre-classified rows stay untouched, verified in Task 13).
- [x] **Transport retry** — handled by the ollama library's built-in httpx retries; plus `classify_one` gracefully skips on exception (Task 8) leaving the row NULL for re-run. No custom retry wrapper, which keeps the code minimal per YAGNI. If empirical flakiness demands more, a retry decorator can be added later.
- [x] **Eval set at `scraper/eval/classify-urls.jsonl`** — Task 11.
- [x] **Install instructions in `CLAUDE.md`** — Task 15.
- [x] **Runbook removed** — already committed in spec commit.

## Placeholder Scan

Reviewed: no TBDs, no "implement later", no "similar to Task N". Every code step has full code. Every test has full assertions. Every command has explicit expected output.

Two intentional placeholder functions (`_run_review`, `_run_sample`) are introduced in Task 10 and **filled in** by Task 11 and Task 12 respectively — this is a deliberate dependency order that keeps task size small, not an unfinished handoff.

## Type Consistency

- `ClassificationResult(label, raw_response, latency_ms)` — defined in Task 7, consumed in Task 8/9/10.
- `Database.record_classification(page_id, label, model, prompt_version, raw_response, latency_ms)` — defined in Task 2, called in Task 8 with the same kwargs.
- `Database.get_unclassified(site, limit)` — Task 3, called in Task 10.
- `Database.sample_classifications(site, label, n)` — Task 4, called via `run_sample` in Task 12.
- `ClassifyFn` type alias — defined in Task 8, used in Tasks 9/11.
- `classify_url(url, sitemap_source, model)` — signature consistent in Tasks 7, 8, 10, 11.
- `PROMPT_VERSION` — defined in Task 6, used in Tasks 10/11/13.
- `LABELS` tuple vs enum list — Task 6 exports `LABELS` as a tuple and wraps it in `list()` inside `RESPONSE_SCHEMA`; tests use both forms.

No drift detected.
