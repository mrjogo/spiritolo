# Smarter ScraperAPI Use — Design

**Date:** 2026-04-18
**Status:** Draft — awaiting review
**Scope:** Two additions to the scraper's fetch step: typed quota/auth errors with clean abort, and `/account`-driven parallel fetching.

## Motivation

The current fetch loop ([scraper/src/fetch.py](../../../scraper/src/fetch.py)) treats every non-200 response from ScraperAPI the same: mark the URL failed, sleep, try the next URL. Two cases deserve different treatment:

- **401 (invalid API key)** and **403 (credits exhausted)** are ScraperAPI-side signals that make continuing the run pointless. Per [ScraperAPI's status-code docs](https://docs.scraperapi.com/responses-and-formats/api-status-codes), these are unambiguous — ScraperAPI does not forward target-site 401/403 codes (target blocks surface as 500 after their 70s internal retry window).
- **Concurrency is a known quantity, not a guess.** The `GET https://api.scraperapi.com/account` endpoint returns `concurrencyLimit`, `concurrentRequests`, `requestCount`, and `requestLimit` directly. We can run exactly as many parallel workers as the plan allows with no probing.

Together these let us (a) fail fast on terminal conditions and (b) fetch at full plan speed instead of the current one-at-a-time + 1.5s-delay sequence.

## Scope

In-scope:
- New exception subclasses `AuthError` and `QuotaExhaustedError` (both subclassing existing `ScraperAPIError`).
- `client.fetch` timeout bump 60s → 70s (matches ScraperAPI's documented internal retry window).
- New `ScraperAPIClient.get_account()` method.
- Pre-flight call in `fetch_pages`: print `"account: N/M credits remaining, concurrency=C"`. `AuthError` here exits without touching the DB.
- `ThreadPoolExecutor`-based parallel fetch loop in `fetch_pages`. Worker count = `concurrencyLimit`, overridable by `--workers N`.
- Cooperative shutdown on `QuotaExhaustedError` / `AuthError` from any worker: set a shutdown flag, drain in-flight futures, print an abort message, return.
- `Database` thread-safety: add `check_same_thread=False` to the `sqlite3.connect` call, add an internal `threading.Lock` (wrapping every method body). SQLite serializes writes itself; this just prevents Python's stricter same-thread check from raising.

Out-of-scope (intentionally deferred):
- Adaptive concurrency (ramp-up, 429 backoff).
- Per-site concurrency caps — our investigation showed per-site politeness is mostly placebo because ScraperAPI rotates IPs/fingerprints. The existing per-site circuit breaker is the real safety net.
- Pre-flight budget caps (`--limit` auto-capped to remaining credits). We abort on 403 at the wall instead.
- Performance benchmarks.
- Changes to discover/validate steps.

## Architecture

```
┌─────────────────────────────────────────┐
│ fetch.py (CLI + fetch_pages)            │
│                                          │
│  1. load_dotenv                          │
│  2. client.get_account() → print budget  │
│  3. ThreadPoolExecutor(N=concurrency)    │
│     │                                    │
│     ├── worker thread ──┐                │
│     ├── worker thread ──┤                │
│     └── worker thread ──┤                │
│                         │                │
│           ┌─────────────▼─────────┐      │
│           │ process_one(row):     │      │
│           │   - check shutdown    │      │
│           │   - check paused_sites│      │
│           │   - client.fetch()    │      │
│           │   - validate + save   │      │
│           │   - db.mark_*()       │      │
│           │   - re-check breaker  │      │
│           └───────────────────────┘      │
│                                          │
│  4. on QuotaExhaustedError/AuthError     │
│     in any worker: shutdown.set(),       │
│     cancel futures, print message, exit  │
└─────────────────────────────────────────┘
```

### Shared state between workers

- `shutdown: threading.Event` — set when any worker raises `QuotaExhaustedError` or `AuthError`. Checked at the top of each `process_one` call.
- `state_lock: threading.Lock` — guards `paused_sites: set[str]` and the `results: dict` counters.
- `Database` — thread-safe via its own internal lock (see below).

### `Database` thread-safety

Minimal change: pass `check_same_thread=False` to `sqlite3.connect` and add `self._lock = threading.RLock()`. Every existing method body is wrapped `with self._lock:`. SQLite already serializes writes at the file level, so the lock's role is solely to satisfy Python's stricter cross-thread check and to make individual method calls atomic from the caller's perspective. No method signatures change.

## Component Changes

### `scraper/src/client.py`

```python
class ScraperAPIError(Exception): pass
class AuthError(ScraperAPIError): pass
class QuotaExhaustedError(ScraperAPIError): pass

class ScraperAPIClient:
    # ... existing __init__ unchanged ...

    def fetch(self, url: str, render: bool = False) -> str:
        # ... build params ...
        resp = requests.get(self.BASE_URL, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=70)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 401:
            raise AuthError(f"Invalid API key: {resp.text[:200]}")
        if resp.status_code == 403:
            raise QuotaExhaustedError(f"Credits exhausted: {resp.text[:200]}")
        raise ScraperAPIError(
            f"ScraperAPI returned {resp.status_code} for {url}: {resp.text[:200]}"
        )

    def get_account(self) -> dict:
        resp = requests.get(
            "https://api.scraperapi.com/account",
            params={"api_key": self.api_key}, timeout=70,
        )
        if resp.status_code == 401:
            raise AuthError("Invalid API key (account endpoint)")
        if resp.status_code != 200:
            raise ScraperAPIError(f"/account returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()
```

### `scraper/src/fetch.py`

- Add import: `from concurrent.futures import ThreadPoolExecutor, as_completed` and `import threading`.
- Add `--workers` CLI flag (default: None, meaning "use `concurrencyLimit` from account").
- Rewrite `fetch_pages` body to:
  1. Pre-flight: `account = client.get_account()`; print one-line summary.
  2. Determine worker count: `workers = workers_override or account["concurrencyLimit"]`.
  3. Initialize `shutdown = threading.Event()`, `state_lock = threading.Lock()`.
  4. Define `process_one(row)` inner function that mirrors the current per-URL logic but guards shared-state access with `state_lock` and bails early if `shutdown.is_set()`.
  5. Submit all pending rows to a `ThreadPoolExecutor(max_workers=workers)`.
  6. Iterate `as_completed(futures)`; on `QuotaExhaustedError` or `AuthError`, set `shutdown`, print abort reason, break. Other exceptions (including `ScraperAPIError`) are already caught inside `process_one` and marked as failures.
  7. `executor.shutdown(wait=True, cancel_futures=True)` — in-flight workers finish their current URL, un-started ones are cancelled.
- Keep all existing CLI flags (`--site`, `--limit`, `--force-site`, `--content-type`).
- The `delay` parameter stays in the function signature for backward compat but defaults to `0.0`. Per-worker sleep is unnecessary when ScraperAPI's concurrency limit governs overall rate.
- Pre-flight error handling: if `get_account()` raises `AuthError` → print clear message, return without entering the loop. If it raises any other `ScraperAPIError` (e.g., transient 500) → abort the run with a message; don't silently fall back to a default concurrency, since we'd be guessing.
- `--workers N` override: trusted as-is. If `N > account["concurrencyLimit"]`, print a one-line warning (`"warning: --workers {N} exceeds plan concurrency {C}; expect 429s"`) but proceed. Useful for multi-key experiments; not our current case.

### `scraper/src/db.py`

```python
import threading
# ...

class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute(CREATE_TABLE)
            for idx in CREATE_INDEXES:
                self.conn.execute(idx)
            self.conn.commit()

    # every other method body wrapped:  with self._lock: ...
```

No public API change.

## Data Flow — Happy Path (parallel)

1. Operator runs `uv run python -m scraper.src.fetch --site simplyrecipes --limit 20`.
2. `fetch_pages` pre-flight calls `/account`, prints `"account: 2387/5000 credits remaining, concurrency=5"`.
3. DB query returns 20 pending rows.
4. 5 workers pull URLs off the list (via the `ThreadPoolExecutor` queue).
5. Each worker: checks circuit breaker for its row's site → calls `client.fetch` → runs `validate()` → writes HTML to disk → marks DB row → re-checks circuit breaker.
6. `as_completed` loop tallies successes/failures into `results` dict.
7. When the last future resolves, print summary + overall stats.

## Data Flow — Quota Exhausted Mid-Run

1. Worker A calls `client.fetch(url)` → gets HTTP 403 → `QuotaExhaustedError` raised.
2. `process_one` in worker A re-raises (does not mark the URL as failed).
3. Main thread's `as_completed` loop receives the exception via `future.result()`.
4. Main thread: `shutdown.set()`; prints `"ABORTED: QuotaExhaustedError: Credits exhausted: ..."`.
5. `executor.shutdown(wait=True, cancel_futures=True)` — workers B/C/D/E finish their current URL normally (or bail if `shutdown.is_set()` before their next DB call); un-started URLs are cancelled.
6. Function returns. URLs that never started remain `status='pending'` in DB, so next invocation resumes cleanly.

## Error Handling Summary

| Condition | Behavior |
|-----------|----------|
| 200 | Save HTML + mark DB (unchanged) |
| 401 (any call) | Raise `AuthError`, abort run |
| 403 (any call) | Raise `QuotaExhaustedError`, abort run |
| 500 / 429 / other | Raise `ScraperAPIError`, mark URL failed, continue (unchanged) |
| Network error / timeout | Raise `requests.*`, caught as `Exception`, mark URL failed, continue (unchanged) |
| Circuit breaker trips for site S | Add S to `paused_sites`; subsequent workers skip S (unchanged semantics) |

## Testing (red/green TDD)

Each capability ships as a red test, implementation, green test commit. Order:

1. `AuthError` on 401 — `tests/test_client.py`: mock 401 → assert raises.
2. `QuotaExhaustedError` on 403 — same pattern.
3. Subclass hierarchy — `isinstance(AuthError(...), ScraperAPIError) is True`.
4. `get_account()` — mock JSON response, assert parsed dict returned, assert 401 from this path raises `AuthError`.
5. Pre-flight prints budget — `tests/test_fetch.py`: stdout-capture, assert substring.
6. Pre-flight `AuthError` exits cleanly — mock `get_account` to raise; assert no DB writes, early return.
7. Parallel happy path — 5 mocked URLs, 2-3 workers, assert all 5 marked + HTML files exist.
8. Quota abort mid-run — partway through queue mock returns 403; assert un-started URLs remain `pending`, abort message printed, function returns cleanly.
9. Circuit breaker in parallel — 20+ URLs same site returning blocking HTML; assert site in `paused_sites` and some URLs remain `pending`.

Dev-dependency `responses` (already in `pyproject.toml`) handles the HTTP mocking.

**Manual smoke test** after implementation:
- `--limit 5 --site simplyrecipes` against live ScraperAPI. Verify budget line prints, 5 HTML files land on disk, DB rows marked.
- Same command with a garbled API key → clean `AuthError` exit, no DB writes, no files.

## Migration / Rollout

- All changes are additive or internal. No DB migration.
- Existing `--delay 1.5` users: the flag still accepts values; it just defaults to `0.0`. Document in `--help`.
- No changes to discover/validate/extract steps.

## Open Questions

None at the time of writing — all clarified during brainstorming.

## References

- [ScraperAPI — API Status Codes](https://docs.scraperapi.com/responses-and-formats/api-status-codes)
- [ScraperAPI — Credits and Requests](https://docs.scraperapi.com/credits-and-requests)
- [ScraperAPI — Free Plan & 7-Day Free Trial](https://docs.scraperapi.com/faq/plans-and-billing/free-plan-and-7-day-free-trial)
- Live `/account` response sample (2026-04-18): `{"burst":0,"concurrencyLimit":5,"concurrentRequests":0,"failedRequestCount":3,"requestCount":2613,"requestLimit":5000,"payAsYouGoEnabled":false,"autoUpgradeEnabled":false,...}`
