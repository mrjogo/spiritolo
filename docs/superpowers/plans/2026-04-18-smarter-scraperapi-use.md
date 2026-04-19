# Smarter ScraperAPI Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed quota/auth errors with clean abort and `/account`-driven parallel fetching to the scraper fetch step.

**Architecture:** Two thin additions to `scraper/src/client.py` (error subclasses + `get_account()`), thread-safety inside `scraper/src/db.py` (internal `RLock`), and a rewrite of `fetch_pages` in `scraper/src/fetch.py` that pre-flights `/account`, runs N parallel workers via `ThreadPoolExecutor`, and cooperatively shuts down on `AuthError` / `QuotaExhaustedError`. Spec: [`docs/superpowers/specs/2026-04-18-smarter-scraperapi-use-design.md`](../specs/2026-04-18-smarter-scraperapi-use-design.md).

**Tech Stack:** Python 3.11, `requests`, `sqlite3`, `concurrent.futures.ThreadPoolExecutor`, `threading`, `responses` (dev), `pytest` (dev). Run tests via `uv run --project scraper pytest`.

---

## File Structure

All paths relative to repo root `/home/ros/code-projects/spiritolo/`:

**Modified:**
- [`scraper/src/client.py`](scraper/src/client.py) — new error subclasses, timeout bump, new `get_account` method.
- [`scraper/src/db.py`](scraper/src/db.py) — add `check_same_thread=False` + internal `RLock`; wrap all methods.
- [`scraper/src/fetch.py`](scraper/src/fetch.py) — pre-flight, `ThreadPoolExecutor`-based loop, cooperative shutdown, `--workers` CLI flag, `delay` default `0.0`.

**Modified tests:**
- [`scraper/tests/test_client.py`](scraper/tests/test_client.py) — update existing `test_fetch_raises_on_403`; add 401/get_account tests.
- [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py) — existing tests gain `get_account` mock on their `mock_client`; new tests for pre-flight, parallel, quota-abort.
- [`scraper/tests/test_db.py`](scraper/tests/test_db.py) — add cross-thread test.

No new files are created.

---

## Task 1: Typed errors in `client.py` (401 → `AuthError`, 403 → `QuotaExhaustedError`) + 70s timeout

**Files:**
- Modify: `scraper/src/client.py`
- Modify: `scraper/tests/test_client.py`

- [ ] **Step 1.1: Update existing test `test_fetch_raises_on_403` to expect `QuotaExhaustedError`**

Edit [`scraper/tests/test_client.py`](scraper/tests/test_client.py), replace the current `test_fetch_raises_on_403` function (currently at lines 39-52) with:

```python
@responses.activate
def test_fetch_raises_QuotaExhaustedError_on_403():
    from scraper.src.client import QuotaExhaustedError
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="You have exhausted credits",
        status=403,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised QuotaExhaustedError"
    except QuotaExhaustedError as e:
        assert "Credits exhausted" in str(e)
```

- [ ] **Step 1.2: Add new tests for `AuthError` on 401 and subclass hierarchy**

Append to [`scraper/tests/test_client.py`](scraper/tests/test_client.py):

```python
@responses.activate
def test_fetch_raises_AuthError_on_401():
    from scraper.src.client import AuthError
    responses.add(
        responses.GET,
        "https://api.scraperapi.com",
        body="Unauthorized, please check your API key",
        status=401,
    )
    client = ScraperAPIClient(api_key="bad-key")
    try:
        client.fetch("https://example.com/recipe/1")
        assert False, "Should have raised AuthError"
    except AuthError as e:
        assert "Invalid API key" in str(e)


def test_AuthError_is_ScraperAPIError_subclass():
    from scraper.src.client import AuthError
    assert issubclass(AuthError, ScraperAPIError)


def test_QuotaExhaustedError_is_ScraperAPIError_subclass():
    from scraper.src.client import QuotaExhaustedError
    assert issubclass(QuotaExhaustedError, ScraperAPIError)
```

- [ ] **Step 1.3: Run tests to verify they fail**

Run: `uv run --project scraper pytest scraper/tests/test_client.py -v`
Expected: 4 failures — `ImportError: cannot import name 'QuotaExhaustedError' / 'AuthError'` for the three new tests plus the rewritten 403 test.

- [ ] **Step 1.4: Implement error classes + status-code branching + 70s timeout**

Edit [`scraper/src/client.py`](scraper/src/client.py). Replace the entire file content with:

```python
import os

import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class ScraperAPIError(Exception):
    pass


class AuthError(ScraperAPIError):
    pass


class QuotaExhaustedError(ScraperAPIError):
    pass


class ScraperAPIClient:
    BASE_URL = "https://api.scraperapi.com"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SCRAPERAPI_KEY")
        if not self.api_key:
            raise ValueError(
                "No API key provided. Pass api_key or set SCRAPERAPI_KEY environment variable."
            )

    def fetch(self, url: str, render: bool = False) -> str:
        params = {
            "api_key": self.api_key,
            "url": url,
        }
        if render:
            params["render"] = "true"

        resp = requests.get(self.BASE_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=70)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 401:
            raise AuthError(f"Invalid API key: {resp.text[:200]}")
        if resp.status_code == 403:
            raise QuotaExhaustedError(f"Credits exhausted: {resp.text[:200]}")
        raise ScraperAPIError(
            f"ScraperAPI returned {resp.status_code} for {url}: {resp.text[:200]}"
        )
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `uv run --project scraper pytest scraper/tests/test_client.py -v`
Expected: all client tests pass.

- [ ] **Step 1.6: Commit**

```bash
git add scraper/src/client.py scraper/tests/test_client.py
git commit -m "$(cat <<'EOF'
Add AuthError / QuotaExhaustedError typed errors

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `ScraperAPIClient.get_account()` method

**Files:**
- Modify: `scraper/src/client.py`
- Modify: `scraper/tests/test_client.py`

- [ ] **Step 2.1: Write failing tests**

Append to [`scraper/tests/test_client.py`](scraper/tests/test_client.py):

```python
@responses.activate
def test_get_account_returns_parsed_json():
    payload = {
        "concurrencyLimit": 5,
        "concurrentRequests": 0,
        "requestCount": 100,
        "requestLimit": 5000,
    }
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        json=payload,
        status=200,
    )
    client = ScraperAPIClient(api_key="test-key")
    result = client.get_account()
    assert result == payload
    assert responses.calls[0].request.params["api_key"] == "test-key"


@responses.activate
def test_get_account_raises_AuthError_on_401():
    from scraper.src.client import AuthError
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        body="Unauthorized",
        status=401,
    )
    client = ScraperAPIClient(api_key="bad-key")
    try:
        client.get_account()
        assert False, "Should have raised AuthError"
    except AuthError as e:
        assert "Invalid API key" in str(e)


@responses.activate
def test_get_account_raises_ScraperAPIError_on_500():
    responses.add(
        responses.GET,
        "https://api.scraperapi.com/account",
        body="Server error",
        status=500,
    )
    client = ScraperAPIClient(api_key="test-key")
    try:
        client.get_account()
        assert False, "Should have raised ScraperAPIError"
    except ScraperAPIError as e:
        assert "/account returned 500" in str(e)
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `uv run --project scraper pytest scraper/tests/test_client.py::test_get_account_returns_parsed_json scraper/tests/test_client.py::test_get_account_raises_AuthError_on_401 scraper/tests/test_client.py::test_get_account_raises_ScraperAPIError_on_500 -v`
Expected: 3 failures — `AttributeError: ... object has no attribute 'get_account'`.

- [ ] **Step 2.3: Implement `get_account`**

Edit [`scraper/src/client.py`](scraper/src/client.py). At the end of the `ScraperAPIClient` class (after the `fetch` method), add:

```python
    def get_account(self) -> dict:
        resp = requests.get(
            "https://api.scraperapi.com/account",
            params={"api_key": self.api_key},
            timeout=70,
        )
        if resp.status_code == 401:
            raise AuthError(f"Invalid API key (account endpoint): {resp.text[:200]}")
        if resp.status_code != 200:
            raise ScraperAPIError(
                f"/account returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `uv run --project scraper pytest scraper/tests/test_client.py -v`
Expected: all client tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add scraper/src/client.py scraper/tests/test_client.py
git commit -m "$(cat <<'EOF'
Add ScraperAPIClient.get_account() for plan introspection

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `Database` thread-safety (internal `RLock`, `check_same_thread=False`)

**Files:**
- Modify: `scraper/src/db.py`
- Modify: `scraper/tests/test_db.py`

- [ ] **Step 3.1: Write failing cross-thread test**

Append to [`scraper/tests/test_db.py`](scraper/tests/test_db.py):

```python
import threading

def test_db_safe_from_multiple_threads(tmp_db):
    """Regression: Database used to raise 'SQLite objects created in a thread
    can only be used in that same thread' when accessed from worker threads.
    After adding check_same_thread=False + an internal lock, this must work."""
    from scraper.src.db import Database
    db = Database(tmp_db)
    errors: list[Exception] = []

    def worker(i: int):
        try:
            db.add_url("threadsite", f"https://example.com/{i}")
        except Exception as e:  # pragma: no cover - only hit if regression
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    rows = db.conn.execute("SELECT COUNT(*) AS c FROM pages").fetchone()
    assert rows["c"] == 10
    db.close()
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `uv run --project scraper pytest scraper/tests/test_db.py::test_db_safe_from_multiple_threads -v`
Expected: FAIL — `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

- [ ] **Step 3.3: Implement thread-safety**

Edit [`scraper/src/db.py`](scraper/src/db.py). Replace the file with:

```python
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 3

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    content_type TEXT,
    sitemap_source TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    error TEXT,
    html_path TEXT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);",
    "CREATE INDEX IF NOT EXISTS idx_pages_site ON pages(site);",
    "CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);",
    "CREATE INDEX IF NOT EXISTS idx_pages_status_content_type ON pages(status, content_type);",
]


class Database:
    def __init__(self, db_path: str | Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute(CREATE_TABLE)
            for idx in CREATE_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def add_url(self, site: str, url: str) -> bool:
        """Insert a URL if it doesn't exist. Returns True if inserted, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO pages (site, url, discovered_at) VALUES (?, ?, ?)",
                (site, url, now),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def add_urls_batch(self, site: str, urls: list[str], sitemap_source: str | None = None) -> int:
        """Insert multiple URLs in a single transaction. Returns count of new rows inserted."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [(site, url, sitemap_source, now) for url in urls]
        with self._lock:
            cursor = self.conn.executemany(
                "INSERT OR IGNORE INTO pages (site, url, sitemap_source, discovered_at) VALUES (?, ?, ?, ?)",
                rows,
            )
            self.conn.commit()
            return cursor.rowcount

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
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def mark_blocked(self, url: str, reason: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = 'blocked', error = ? WHERE url = ?",
                (reason, url),
            )
            self.conn.commit()

    def mark_content(self, url: str, status: str, reason: str, html_path: str | None = None):
        """Mark a page with an arbitrary content status (JSON-LD @type, 'unverified', etc.)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET status = ?, error = ?, html_path = ?, fetched_at = ? WHERE url = ?",
                (status, reason, html_path, now, url),
            )
            self.conn.commit()

    def mark_failed(self, url: str, error: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET attempts = attempts + 1, error = ? WHERE url = ?",
                (error, url),
            )
            self.conn.execute(
                "UPDATE pages SET status = 'failed' WHERE url = ? AND attempts >= ?",
                (url, MAX_ATTEMPTS),
            )
            self.conn.commit()

    def get_recent_statuses(self, site: str, count: int = 20) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT status FROM pages WHERE site = ? AND status != 'pending' ORDER BY id DESC LIMIT ?",
                (site, count),
            ).fetchall()
        return [row["status"] for row in rows]

    def get_stats(self) -> dict:
        with self._lock:
            rows = self.conn.execute(
                "SELECT site, status, COUNT(*) as cnt FROM pages GROUP BY site, status"
            ).fetchall()
        stats: dict = {}
        for row in rows:
            site = row["site"]
            if site not in stats:
                stats[site] = {}
            stats[site][row["status"]] = row["cnt"]
        return stats

    def set_content_type(self, url: str, content_type: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pages SET content_type = ? WHERE url = ?",
                (content_type, url),
            )
            self.conn.commit()

    def set_content_type_batch(self, ids: list[int], content_type: str):
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
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
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 3.4: Run all DB tests (regression + new)**

Run: `uv run --project scraper pytest scraper/tests/test_db.py -v`
Expected: all tests pass, including the new cross-thread test.

- [ ] **Step 3.5: Commit**

```bash
git add scraper/src/db.py scraper/tests/test_db.py
git commit -m "$(cat <<'EOF'
Make Database safe across threads (RLock + check_same_thread=False)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Pre-flight `/account` call + budget line in `fetch_pages`

**Files:**
- Modify: `scraper/src/fetch.py`
- Modify: `scraper/tests/test_fetch.py`

Existing `test_fetch.py` tests use `MagicMock()` for the client. Because `MagicMock` auto-stubs any attribute access, `mock_client.get_account()` currently returns a `MagicMock` instance — not a dict. Each existing test that calls `fetch_pages(db, mock_client, ...)` needs `mock_client.get_account.return_value = {"concurrencyLimit": 1, "requestCount": 0, "requestLimit": 5000}` added before the `fetch_pages` call, OR we can add a shared fixture. We'll use a helper to keep diffs contained.

- [ ] **Step 4.1: Add a shared helper fixture in conftest.py**

Edit [`scraper/tests/conftest.py`](scraper/tests/conftest.py). Append:

```python
@pytest.fixture
def make_mock_client():
    """Factory that returns a MagicMock with get_account() returning a sensible default."""
    from unittest.mock import MagicMock

    def _make(concurrency: int = 1, request_count: int = 0, request_limit: int = 5000):
        m = MagicMock()
        m.get_account.return_value = {
            "concurrencyLimit": concurrency,
            "concurrentRequests": 0,
            "requestCount": request_count,
            "requestLimit": request_limit,
            "burst": 0,
            "failedRequestCount": 0,
        }
        return m

    return _make
```

- [ ] **Step 4.2: Write failing test for budget print**

Append to [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py):

```python
def test_fetch_pages_preflight_prints_budget(tmp_db, tmp_path, make_mock_client, capsys):
    db = Database(tmp_db)
    mock_client = make_mock_client(concurrency=5, request_count=2613, request_limit=5000)
    fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)
    captured = capsys.readouterr()
    assert "2387/5000 credits remaining" in captured.out
    assert "concurrency=5" in captured.out
    mock_client.get_account.assert_called_once()
    db.close()
```

- [ ] **Step 4.3: Run test to verify it fails**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py::test_fetch_pages_preflight_prints_budget -v`
Expected: FAIL — `AssertionError` on the stdout substring (no pre-flight yet).

- [ ] **Step 4.4: Implement pre-flight call + print at top of `fetch_pages`**

Edit [`scraper/src/fetch.py`](scraper/src/fetch.py). Replace the `fetch_pages` function body. Locate the current signature (line 39) and replace only the function body before `pending = db.get_pending(...)` to inject the pre-flight. Concretely, change the beginning of the function from:

```python
def fetch_pages(
    db: Database,
    client: ScraperAPIClient,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    limit: int | None = None,
    force_site: str | None = None,
    content_type: str | None = "likely_drink_recipe",
    delay: float = 1.5,
) -> dict:
    pending = db.get_pending(site=site or force_site, limit=limit, content_type=content_type)
```

to:

```python
def fetch_pages(
    db: Database,
    client: ScraperAPIClient,
    html_dir: Path = DEFAULT_HTML_DIR,
    site: str | None = None,
    limit: int | None = None,
    force_site: str | None = None,
    content_type: str | None = "likely_drink_recipe",
    delay: float = 0.0,
    workers: int | None = None,
) -> dict:
    account = client.get_account()
    remaining = account["requestLimit"] - account["requestCount"]
    concurrency = account["concurrencyLimit"]
    print(
        f"account: {remaining}/{account['requestLimit']} credits remaining, "
        f"concurrency={concurrency}"
    )

    pending = db.get_pending(site=site or force_site, limit=limit, content_type=content_type)
```

(The `workers` parameter and the `delay` default change are included here to avoid revisiting the signature in later tasks. They are not yet wired into behavior; later tasks use them.)

- [ ] **Step 4.5: Update existing tests to use `make_mock_client` fixture**

Each existing test in [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py) that uses `MagicMock()` directly needs to either switch to `make_mock_client` or add a `get_account.return_value`. Simpler: add the return value on each existing mock. For every function in that file that currently does:

```python
mock_client = MagicMock()
mock_client.fetch.return_value = ...
```

insert immediately after the `MagicMock()` line:

```python
mock_client.get_account.return_value = {
    "concurrencyLimit": 1, "concurrentRequests": 0,
    "requestCount": 0, "requestLimit": 5000,
    "burst": 0, "failedRequestCount": 0,
}
```

Affected test functions (edit each):
- `test_fetch_pages_marks_recipe`
- `test_fetch_pages_marks_blocked`
- `test_fetch_pages_handles_network_error`
- `test_fetch_pages_respects_limit`
- `test_fetch_pages_only_fetches_likely_drink_recipe`
- `test_fetch_pages_circuit_breaker_pauses_site`
- `test_fetch_pages_confirms_drink`
- `test_fetch_pages_confirms_food`
- `test_fetch_pages_leaves_likely_drink_when_no_recipe_jsonld`

- [ ] **Step 4.6: Run all fetch tests — new test passes, existing tests still pass**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py -v`
Expected: all tests pass, including `test_fetch_pages_preflight_prints_budget`.

- [ ] **Step 4.7: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py scraper/tests/conftest.py
git commit -m "$(cat <<'EOF'
Pre-flight /account call prints remaining credits + concurrency

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Pre-flight abort on `AuthError` / `ScraperAPIError`

**Files:**
- Modify: `scraper/src/fetch.py`
- Modify: `scraper/tests/test_fetch.py`

- [ ] **Step 5.1: Write failing tests**

Append to [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py):

```python
def test_fetch_pages_aborts_on_preflight_auth_error(tmp_db, tmp_path, capsys):
    from unittest.mock import MagicMock
    from scraper.src.client import AuthError
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.side_effect = AuthError("Invalid API key")

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    # fetch() should never have been called
    mock_client.fetch.assert_not_called()
    # Page should still be pending
    row = db.conn.execute(
        "SELECT status FROM pages WHERE url = ?",
        ("https://example.com/recipes/margarita",),
    ).fetchone()
    assert row["status"] == "pending"
    captured = capsys.readouterr()
    assert "ABORTED" in captured.out or "AuthError" in captured.out
    assert results == {"blocked": 0, "errors": 0, "paused_sites": []}
    db.close()


def test_fetch_pages_aborts_on_preflight_scraperapi_error(tmp_db, tmp_path, capsys):
    from unittest.mock import MagicMock
    from scraper.src.client import ScraperAPIError
    db = Database(tmp_db)
    db.add_url("testsite", "https://example.com/recipes/margarita")
    db.set_content_type("https://example.com/recipes/margarita", "likely_drink_recipe")

    mock_client = MagicMock()
    mock_client.get_account.side_effect = ScraperAPIError("/account returned 500")

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    mock_client.fetch.assert_not_called()
    captured = capsys.readouterr()
    assert "ABORTED" in captured.out or "500" in captured.out
    assert results == {"blocked": 0, "errors": 0, "paused_sites": []}
    db.close()
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py::test_fetch_pages_aborts_on_preflight_auth_error scraper/tests/test_fetch.py::test_fetch_pages_aborts_on_preflight_scraperapi_error -v`
Expected: 2 failures — exception propagates instead of being caught, or `fetch` is unexpectedly called.

- [ ] **Step 5.3: Implement pre-flight error handling**

Edit [`scraper/src/fetch.py`](scraper/src/fetch.py). At the top of the file add to imports:

```python
from scraper.src.client import ScraperAPIClient, ScraperAPIError, AuthError, QuotaExhaustedError
```

(Remove the old line `from scraper.src.client import ScraperAPIClient`.)

Replace the pre-flight section added in Task 4.4 with:

```python
    try:
        account = client.get_account()
    except AuthError as e:
        print(f"ABORTED: AuthError: {e}")
        return {"blocked": 0, "errors": 0, "paused_sites": []}
    except ScraperAPIError as e:
        print(f"ABORTED: {e}")
        return {"blocked": 0, "errors": 0, "paused_sites": []}
    remaining = account["requestLimit"] - account["requestCount"]
    concurrency = account["concurrencyLimit"]
    print(
        f"account: {remaining}/{account['requestLimit']} credits remaining, "
        f"concurrency={concurrency}"
    )
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py -v`
Expected: all fetch tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py
git commit -m "$(cat <<'EOF'
Abort fetch run cleanly on pre-flight AuthError / ScraperAPIError

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Parallel fetch loop — happy path (`ThreadPoolExecutor`)

**Files:**
- Modify: `scraper/src/fetch.py`
- Modify: `scraper/tests/test_fetch.py`

The goal here is behavior-preserving refactor to a thread pool. Quota/auth abort logic comes in Task 7.

- [ ] **Step 6.1: Write failing parallel happy-path test**

Append to [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py):

```python
def test_fetch_pages_parallel_happy_path(tmp_db, tmp_path, make_mock_client, sample_recipe_html):
    """All 5 URLs get fetched and marked when running with 3 workers."""
    db = Database(tmp_db)
    urls = [f"https://example.com/recipes/{i}" for i in range(5)]
    for url in urls:
        db.add_url("testsite", url)
        db.set_content_type(url, "likely_drink_recipe")

    mock_client = make_mock_client(concurrency=3)
    mock_client.fetch.return_value = sample_recipe_html

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    assert mock_client.fetch.call_count == 5
    assert results.get("Recipe", 0) == 5
    for url in urls:
        row = db.conn.execute(
            "SELECT status FROM pages WHERE url = ?", (url,)
        ).fetchone()
        assert row["status"] == "Recipe"
    # No URL should still be pending
    assert db.get_pending() == []
    db.close()
```

- [ ] **Step 6.2: Run test to verify it fails or passes incidentally**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py::test_fetch_pages_parallel_happy_path -v`
Expected: PASS (sequential implementation handles 5 URLs correctly — this is a behavior-preservation test). Note it as the baseline before refactor; if it FAILs, debug before proceeding.

- [ ] **Step 6.3: Refactor `fetch_pages` body to use `ThreadPoolExecutor`**

Edit [`scraper/src/fetch.py`](scraper/src/fetch.py). Add to imports at top:

```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
```

Replace the entire loop body (everything from `pending = db.get_pending(...)` to the `results["paused_sites"] = list(paused_sites)` assignment) with:

```python
    pending = db.get_pending(site=site or force_site, limit=limit, content_type=content_type)
    paused_sites: set[str] = set()
    results: dict = {"blocked": 0, "errors": 0, "paused_sites": []}
    state_lock = threading.Lock()

    n_workers = workers if workers is not None else concurrency
    if workers is not None and workers > concurrency:
        print(
            f"warning: --workers {workers} exceeds plan concurrency {concurrency}; "
            "expect 429s"
        )

    total = len(pending)
    if total == 0:
        results["paused_sites"] = []
        return results

    def process_one(row: dict) -> None:
        page_site = row["site"]
        url = row["url"]

        # Circuit breaker check (skip if --force-site)
        if page_site != force_site:
            with state_lock:
                if page_site in paused_sites:
                    return
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                with state_lock:
                    if page_site not in paused_sites:
                        paused_sites.add(page_site)
                        print(
                            f"[{page_site}] PAUSED — >{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% "
                            f"of last {CIRCUIT_BREAKER_WINDOW} pages failed validation"
                        )
                return

        print(f"[{page_site}] — {url}")

        try:
            html = client.fetch(url)
        except Exception as e:
            db.mark_failed(url, str(e))
            with state_lock:
                results["errors"] += 1
            print(f"  ERROR: {e}")
            if delay > 0:
                time.sleep(delay)
            return

        result = validate(html)
        if result.status == "blocked":
            db.mark_blocked(url, result.reason or "blocked")
            with state_lock:
                results["blocked"] += 1
            print(f"  BLOCKED: {result.reason}")
        else:
            filename = url_to_filename(url)
            rel_path = save_html(html_dir, page_site, filename, html)
            db.mark_content(url, result.status, result.reason or result.status, html_path=rel_path)
            with state_lock:
                results[result.status] = results.get(result.status, 0) + 1
            print(f"  {result.status}: {result.reason}")

            drink_result = classify_drink(html)
            if drink_result:
                db.set_content_type(url, drink_result)

        # Re-check circuit breaker after each fetch
        if page_site != force_site:
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                with state_lock:
                    if page_site not in paused_sites:
                        paused_sites.add(page_site)
                        print(
                            f"[{page_site}] PAUSED — >{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% "
                            f"of last {CIRCUIT_BREAKER_WINDOW} pages failed validation"
                        )

        if delay > 0:
            time.sleep(delay)

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(process_one, row) for row in pending]
        for f in as_completed(futures):
            f.result()  # re-raise any uncaught exception

    with state_lock:
        results["paused_sites"] = list(paused_sites)
    return results
```

Important: the `time` import is already present (existing file uses it at [fetch.py:3](scraper/src/fetch.py)). `validate` and `classify_drink` and `url_to_filename`, `save_html`, `check_circuit_breaker` are all already imported / defined above.

- [ ] **Step 6.4: Run ALL fetch tests to verify nothing regressed**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py -v`
Expected: all tests pass, including the new parallel happy path.

- [ ] **Step 6.5: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py
git commit -m "$(cat <<'EOF'
Run fetch pages in parallel via ThreadPoolExecutor

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Quota / auth abort mid-run (cooperative shutdown)

**Files:**
- Modify: `scraper/src/fetch.py`
- Modify: `scraper/tests/test_fetch.py`

- [ ] **Step 7.1: Write failing test — quota exhausted mid-run**

Append to [`scraper/tests/test_fetch.py`](scraper/tests/test_fetch.py):

```python
def test_fetch_pages_aborts_on_quota_mid_run(tmp_db, tmp_path, make_mock_client, sample_recipe_html, capsys):
    """After a QuotaExhaustedError, remaining URLs must stay pending (not marked failed)."""
    from scraper.src.client import QuotaExhaustedError
    db = Database(tmp_db)
    urls = [f"https://example.com/recipes/{i}" for i in range(10)]
    for url in urls:
        db.add_url("testsite", url)
        db.set_content_type(url, "likely_drink_recipe")

    # First call succeeds, subsequent calls raise QuotaExhaustedError
    call_count = {"n": 0}
    lock = threading.Lock()
    def fake_fetch(url):
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        if n == 1:
            return sample_recipe_html
        raise QuotaExhaustedError("Credits exhausted: demo")

    mock_client = make_mock_client(concurrency=1)  # sequential to keep ordering deterministic
    mock_client.fetch.side_effect = fake_fetch

    results = fetch_pages(db, mock_client, html_dir=tmp_path, delay=0)

    captured = capsys.readouterr()
    assert "ABORTED" in captured.out
    assert "QuotaExhaustedError" in captured.out

    # At least one URL should have been marked Recipe (the first one).
    recipe_rows = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pages WHERE status = 'Recipe'"
    ).fetchone()
    assert recipe_rows["c"] >= 1

    # At least one URL should remain pending (not marked failed).
    pending = db.get_pending()
    assert len(pending) >= 1
    # No URL should be marked failed due to the quota error.
    failed_rows = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pages WHERE status = 'failed'"
    ).fetchone()
    assert failed_rows["c"] == 0
    db.close()
```

Ensure `import threading` is present at the top of the test file (add if absent).

- [ ] **Step 7.2: Run test to verify it fails**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py::test_fetch_pages_aborts_on_quota_mid_run -v`
Expected: FAIL — current code catches `QuotaExhaustedError` as generic `Exception` in `process_one` and marks the URL as failed.

- [ ] **Step 7.3: Implement cooperative shutdown**

Edit [`scraper/src/fetch.py`](scraper/src/fetch.py).

Inside `fetch_pages`, just before the `def process_one(...)` function, add:

```python
    shutdown = threading.Event()
```

In `process_one`, at the very top (before the `page_site = row["site"]` line), add:

```python
        if shutdown.is_set():
            return
```

Replace the broad `except Exception as e:` clause inside `process_one` with:

```python
        except (QuotaExhaustedError, AuthError):
            shutdown.set()
            raise
        except Exception as e:
            db.mark_failed(url, str(e))
            with state_lock:
                results["errors"] += 1
            print(f"  ERROR: {e}")
            if delay > 0:
                time.sleep(delay)
            return
```

Replace the main-thread `for f in as_completed(futures)` loop with:

```python
        abort_message: str | None = None
        for f in as_completed(futures):
            try:
                f.result()
            except (QuotaExhaustedError, AuthError) as e:
                shutdown.set()
                abort_message = f"ABORTED: {type(e).__name__}: {e}"
                break

    if abort_message:
        print(abort_message)
```

Note the outer `with ThreadPoolExecutor(...)` block — `executor.__exit__` handles draining. Python 3.9+ supports `shutdown(cancel_futures=True)` but the `with` block uses default shutdown semantics (waits for in-flight). If we want un-started futures cancelled promptly, replace the `with` block with explicit shutdown:

```python
    executor = ThreadPoolExecutor(max_workers=n_workers)
    try:
        futures = [executor.submit(process_one, row) for row in pending]
        abort_message: str | None = None
        for f in as_completed(futures):
            try:
                f.result()
            except (QuotaExhaustedError, AuthError) as e:
                shutdown.set()
                abort_message = f"ABORTED: {type(e).__name__}: {e}"
                break
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    if abort_message:
        print(abort_message)
```

Use this explicit form.

- [ ] **Step 7.4: Run all fetch tests to verify behavior**

Run: `uv run --project scraper pytest scraper/tests/test_fetch.py -v`
Expected: all tests pass, including the new quota-abort test.

- [ ] **Step 7.5: Commit**

```bash
git add scraper/src/fetch.py scraper/tests/test_fetch.py
git commit -m "$(cat <<'EOF'
Cooperative shutdown on AuthError / QuotaExhaustedError mid-run

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `--workers` CLI flag + `--delay` default

**Files:**
- Modify: `scraper/src/fetch.py`

No new tests — the behavior is already covered (workers param already present in `fetch_pages` signature from Task 4.4). This task only wires the CLI.

- [ ] **Step 8.1: Update argparse in `__main__` block**

Edit [`scraper/src/fetch.py`](scraper/src/fetch.py). In the `if __name__ == "__main__":` block, add arguments after the existing `--content-type` argument:

```python
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of concurrent fetch workers (default: concurrencyLimit from /account)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between fetches per worker (default: 0.0 — ScraperAPI's concurrency limit governs rate)",
    )
```

And update the `fetch_pages(...)` call in `__main__` to pass them:

```python
    results = fetch_pages(
        db,
        client,
        site=args.site,
        limit=args.limit,
        force_site=args.force_site,
        content_type=content_type,
        workers=args.workers,
        delay=args.delay,
    )
```

- [ ] **Step 8.2: Verify argparse with --help**

Run: `uv run --project scraper python -m scraper.src.fetch --help 2>&1 | head -30`
Expected: shows `--workers` and `--delay` in the help output.

- [ ] **Step 8.3: Run full test suite as sanity check**

Run: `uv run --project scraper pytest scraper/tests/ -v`
Expected: all tests pass.

- [ ] **Step 8.4: Commit**

```bash
git add scraper/src/fetch.py
git commit -m "$(cat <<'EOF'
Wire --workers and --delay CLI flags for fetch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Manual smoke tests (live ScraperAPI)

**Files:** None (verification only).

- [ ] **Step 9.1: Bogus API key smoke test**

Run with a deliberately bad key:

```bash
SCRAPERAPI_KEY=garbled uv run --project scraper python -m scraper.src.fetch --site simplyrecipes --limit 1
```

Expected: prints `ABORTED: AuthError: ...`, no HTML files written, no DB changes.

- [ ] **Step 9.2: Real fetch smoke test (tiny)**

Run:

```bash
uv run --project scraper python -m scraper.src.fetch --site simplyrecipes --limit 5
```

Expected:
- Prints `account: N/5000 credits remaining, concurrency=5` line.
- 5 HTML files appear under `data/html/simplyrecipes/`.
- DB shows 5 fewer pending for `simplyrecipes`.
- Run completes without errors.

- [ ] **Step 9.3: Verify DB state**

Run:

```bash
uv run --project scraper python -c "
from scraper.src.db import Database
from pathlib import Path
db = Database(Path('data/scraper.db'))
for site, counts in db.get_stats().items():
    if site == 'simplyrecipes':
        print(site, counts)
db.close()
"
```

Expected: non-zero count for `Recipe` status for `simplyrecipes`.

- [ ] **Step 9.4: Commit any noted issues or follow-ups (no-op if all clean)**

If smoke tests uncover bugs, create follow-up commits. Otherwise this task has no git commit.

---

## Self-Review Checklist

- [ ] Every spec requirement mapped to a task:
  - Typed errors on 401/403 → Task 1
  - 70s timeout → Task 1
  - `get_account()` → Task 2
  - `Database` thread-safety → Task 3
  - Pre-flight budget print → Task 4
  - Pre-flight abort on errors → Task 5
  - Parallel fetch loop → Task 6
  - Quota/auth abort mid-run → Task 7
  - `--workers` CLI flag → Task 8
  - `--delay` default change → Task 4 (signature) + Task 8 (CLI)
  - Smoke tests → Task 9
- [ ] No placeholders ("TBD", "add error handling", "similar to Task N").
- [ ] Type/signature consistency: `workers: int | None` used in both `fetch_pages` signature (Task 4) and argparse wiring (Task 8). Error class names `AuthError` / `QuotaExhaustedError` consistent across tasks.
- [ ] Every code step shows full code; every test step shows the test.
- [ ] Commits are small (one capability each), test-first.

---

## Out of Scope (from spec, intentional)

- Adaptive concurrency (ramp-up, 429 backoff).
- Per-site concurrency caps.
- Pre-flight budget caps (auto-lowering `--limit` based on remaining credits).
- Performance benchmarks.
- Changes to `discover` / `validate` / `extract` steps.
