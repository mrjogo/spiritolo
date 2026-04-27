import argparse
import hashlib
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from spiritolo_common.progress import make_progress
from spiritolo_common.summary import print_summary

from scraper.src.classify_drink import SCORER_VERSION, classify_drink_scored
from scraper.src.client import ScraperAPIClient, ScraperAPIError, AuthError, QuotaExhaustedError
from scraper.src.db import Database
from scraper.src.validation import VALIDATOR_VERSION, validate

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"
DEFAULT_HTML_DIR = DATA_DIR / "html"

CIRCUIT_BREAKER_WINDOW = 20
CIRCUIT_BREAKER_THRESHOLD = 0.4  # 40% failure rate


def url_to_filename(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16] + ".html"


def save_html(html_dir: Path, site_name: str, filename: str, html: str) -> str:
    site_dir = html_dir / site_name
    site_dir.mkdir(parents=True, exist_ok=True)
    file_path = site_dir / filename
    file_path.write_text(html, encoding="utf-8")
    return f"{site_name}/{filename}"


def estimate_credits(
    client: ScraperAPIClient, pending: list[dict]
) -> list[tuple[str, int, int | None]]:
    """Return ``[(site, pending_count, credits_per_req)]`` sorted by site name.

    Probes ``/account/urlcost`` once per site (cost is per-domain on
    ScraperAPI, so a single sample URL is representative). ``credits_per_req``
    is ``None`` if the probe failed."""
    by_site: dict[str, list[dict]] = {}
    for row in pending:
        by_site.setdefault(row["site"], []).append(row)

    def probe(item: tuple[str, list[dict]]) -> tuple[str, int, int | None]:
        site, rows = item
        try:
            cost = client.url_cost(rows[0]["url"])
        except ScraperAPIError:
            cost = None
        return site, len(rows), cost

    with ThreadPoolExecutor(max_workers=min(8, len(by_site))) as ex:
        results = list(ex.map(probe, by_site.items()))
    results.sort(key=lambda r: r[0])
    return results


def print_preflight(
    estimates: list[tuple[str, int, int | None]], remaining: int
) -> int:
    """Render the per-site preflight table, return total estimated credits."""
    print("\nPreflight cost estimate:")
    print(f"  {'site':<16} {'pending':>9} {'cred/req':>9} {'estimated':>11}")
    total = 0
    for site, count, cost in estimates:
        if cost is None:
            cost_str = "?"
            row_str = "?"
        else:
            row_total = count * cost
            total += row_total
            cost_str = str(cost)
            row_str = f"{row_total:,}"
        print(f"  {site:<16} {count:>9,} {cost_str:>9} {row_str:>11}")
    print(f"  {'':<16} {'':>9} {'total':>9} {total:>11,}")
    print(f"  account remaining: {remaining:,}")
    if total > remaining:
        print(f"  WARNING: estimate exceeds remaining credits by {total - remaining:,}")
    return total


def check_circuit_breaker(recent_statuses: list[str]) -> bool:
    n = len(recent_statuses)
    if n < CIRCUIT_BREAKER_WINDOW:
        return False
    window = recent_statuses[:CIRCUIT_BREAKER_WINDOW]
    bad_count = sum(1 for s in window if s == "blocked")
    return bad_count / CIRCUIT_BREAKER_WINDOW > CIRCUIT_BREAKER_THRESHOLD


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
    confirm: bool = False,
) -> tuple[dict[str, Counter], list[str]]:
    """Fetch pending pages and return ``(per_site_changes, paused_sites)``.

    ``per_site_changes`` is the same shape every other stage CLI returns —
    ``dict[str, Counter]`` keyed by site, with categories like the JSON-LD
    ``@type`` of the fetched page (Recipe, NewsArticle, …), ``blocked``
    (validator rejection), or ``error`` (network/HTTP failure). Renders via
    ``spiritolo_common.summary.print_summary``.

    ``paused_sites`` is reported separately because it isn't a count — it's
    a side-effect (circuit-breaker tripped). Returned for tests / pipeline
    bookkeeping; the per-site PAUSED line is also logged inline as it fires.
    """
    try:
        account = client.get_account()
    except AuthError as e:
        print(f"ABORTED: AuthError: {e}")
        return {}, []
    except ScraperAPIError as e:
        print(f"ABORTED: {e}")
        return {}, []
    remaining = account["requestLimit"] - account["requestCount"]
    concurrency = account["concurrencyLimit"]
    print(
        f"account: {remaining}/{account['requestLimit']} credits remaining, "
        f"concurrency={concurrency}"
    )

    pending = db.get_pending(site=site or force_site, limit=limit, content_type=content_type)
    paused_sites: set[str] = set()
    changes: dict[str, Counter] = {}
    state_lock = threading.Lock()
    shutdown = threading.Event()

    def bump(site_name: str, category: str) -> None:
        # Caller already holds state_lock when needed for the surrounding
        # mutation; the dict.setdefault path is a single C-level op.
        changes.setdefault(site_name, Counter())[category] += 1

    n_workers = workers if workers is not None else concurrency
    if workers is not None and workers > concurrency:
        print(
            f"warning: --workers {workers} exceeds plan concurrency {concurrency}; "
            "expect 429s"
        )

    total = len(pending)
    if total == 0:
        return changes, []

    if confirm:
        estimates = estimate_credits(client, pending)
        print_preflight(estimates, remaining)
        answer = input("\nProceed? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return changes, []

    run_id = db.start_run(
        stage="fetch",
        site=site or force_site,
        args={
            "limit": limit, "content_type": content_type,
            "workers": n_workers, "delay": delay, "force_site": force_site,
        },
    )
    progress = make_progress(total=total)

    def process_one(row: dict) -> None:
        if shutdown.is_set():
            return
        page_site = row["site"]
        url = row["url"]
        page_id = row["id"]
        status_before = row["status"]
        content_type_before = row["content_type"]

        # Circuit breaker check (skip if --force-site). Pause is a notable
        # event — print it inline (it's rare and otherwise invisible).
        if page_site != force_site:
            with state_lock:
                if page_site in paused_sites:
                    return
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                with state_lock:
                    if page_site not in paused_sites:
                        paused_sites.add(page_site)
                        # Newline first so the inline notice doesn't collide
                        # with the in-progress \r progress line.
                        print(
                            f"\n[{page_site}] PAUSED — "
                            f">{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% "
                            f"of last {CIRCUIT_BREAKER_WINDOW} pages failed validation"
                        )
                return

        try:
            html = client.fetch(url)
        except (QuotaExhaustedError, AuthError):
            shutdown.set()
            raise
        except Exception as e:
            db.mark_failed(url, str(e))
            with state_lock:
                bump(page_site, "error")
            if delay > 0:
                time.sleep(delay)
            return

        result = validate(html, url=url)
        filename = url_to_filename(url)
        rel_path = save_html(html_dir, page_site, filename, html)
        if result.status == "blocked":
            db.mark_blocked(url, html_path=rel_path)
            with state_lock:
                bump(page_site, "blocked")
        else:
            db.mark_content(url, result.status, html_path=rel_path)
            with state_lock:
                bump(page_site, result.status)

        # Record the validate + classify_drink evaluations into the same
        # eval tables the standalone validate CLI uses, so both entry points
        # contribute to the same provenance record and latest-only is
        # preserved per page. Snapshot the PRE-fetch pages.* values — they
        # reflect what the row looked like before this fetch ran.
        db.record_validate_html(
            page_id=page_id,
            run_id=run_id,
            status=result.status,
            reason=result.reason,
            validator_version=VALIDATOR_VERSION,
            pages_status_before=status_before,
        )

        # classify_drink runs even on blocked pages; the result is an abstain
        # (label=None, score=0) when there's no Recipe to score.
        classification = classify_drink_scored(html)
        if result.status != "blocked" and classification.label is not None:
            db.set_content_type(url, classification.label)
        db.record_classify_drink(
            page_id=page_id,
            run_id=run_id,
            label=classification.label,
            score=classification.score,
            score_detail={"rules": classification.rules},
            scorer_version=SCORER_VERSION,
            pages_content_type_before=content_type_before,
        )

        # Re-check circuit breaker after each fetch
        if page_site != force_site:
            recent = db.get_recent_statuses(page_site, count=CIRCUIT_BREAKER_WINDOW)
            if check_circuit_breaker(recent):
                with state_lock:
                    if page_site not in paused_sites:
                        paused_sites.add(page_site)
                        print(
                            f"\n[{page_site}] PAUSED — "
                            f">{CIRCUIT_BREAKER_THRESHOLD*100:.0f}% "
                            f"of last {CIRCUIT_BREAKER_WINDOW} pages failed validation"
                        )

        if delay > 0:
            time.sleep(delay)

    executor = ThreadPoolExecutor(max_workers=n_workers)
    abort_message: str | None = None
    done = 0
    try:
        futures = [executor.submit(process_one, row) for row in pending]
        for f in as_completed(futures):
            try:
                f.result()
            except (QuotaExhaustedError, AuthError) as e:
                shutdown.set()
                abort_message = f"\nABORTED: {type(e).__name__}: {e}"
                break
            done += 1
            progress(done)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    if abort_message:
        print(abort_message)

    with state_lock:
        paused = sorted(paused_sites)
    db.finish_run(
        run_id,
        summary={
            "per_site": {s: dict(c) for s, c in changes.items()},
            "paused_sites": paused,
        },
    )
    return changes, paused


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch pending recipe pages via ScraperAPI")
    parser.add_argument("--site", help="Only fetch for a specific site")
    parser.add_argument("--limit", type=int, help="Max number of pages to fetch")
    parser.add_argument("--force-site", help="Resume a paused site (bypasses circuit breaker)")
    parser.add_argument(
        "--content-type",
        default="likely_drink_recipe",
        help="Filter pending pages by content_type (default: likely_drink_recipe). Pass 'any' to disable the filter.",
    )
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
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip preflight confirmation prompt",
    )
    args = parser.parse_args()
    content_type = None if args.content_type == "any" else args.content_type

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(DEFAULT_DB_PATH)
    client = ScraperAPIClient()

    changes, paused = fetch_pages(
        db,
        client,
        site=args.site,
        limit=args.limit,
        force_site=args.force_site,
        content_type=content_type,
        workers=args.workers,
        delay=args.delay,
        confirm=not args.yes,
    )

    print_summary("Fetch", changes)
    if paused:
        print(f"Paused (circuit breaker): {', '.join(paused)}")

    db.close()
