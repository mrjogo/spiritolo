import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

from scraper.src.structured import (
    extract_structured,
    iter_jsonld_objects,
    iter_microdata_items,
    iter_recipes,
    type_names,
)


@dataclass
class ValidationResult:
    status: str  # "fetched", "blocked", "unverified"
    reason: str | None = None


BLOCKER_FINGERPRINTS = [
    ("cf-challenge-running", "cf-challenge detected"),
    ("cf-turnstile", "cf-turnstile detected"),
    ("g-recaptcha", "recaptcha detected"),
    ("hcaptcha", "hcaptcha detected"),
    ("Access Denied", "access denied"),
    ("_pxhd", "perimeterx detected"),
    ("datadome", "datadome detected"),
    ("Enable JavaScript and cookies", "javascript required page"),
    ("Please verify you are a human", "human verification page"),
    ("cf-mitigated", "cf-mitigated detected"),
]

MIN_PAGE_SIZE = 5000  # bytes

MIN_TEXT_LENGTH = 500  # visible characters after stripping tags



class TextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping script/style tags."""

    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.text_parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.text_parts).strip()


def _extract_visible_text(html: str) -> str:
    extractor = TextExtractor()
    extractor.feed(html)
    return extractor.get_text()


_TYPE_PRIORITY = ("Recipe", "NewsArticle", "Article", "WebPage", "WebSite")


def _type_rank(t: str) -> int:
    if t in _TYPE_PRIORITY:
        return _TYPE_PRIORITY.index(t)
    return len(_TYPE_PRIORITY)


def _find_jsonld_type(structured: dict) -> str | None:
    """Return the highest-priority @type across all JSON-LD blocks, or None.

    Priority: Recipe > NewsArticle > Article > WebPage > WebSite > other. Needed
    because sites like Tasting Table emit a wrapper Article block before the
    Recipe block — picking "first type seen" would misclassify recipes.
    """
    best: str | None = None
    best_rank = len(_TYPE_PRIORITY) + 1
    for obj in iter_jsonld_objects(structured):
        obj_type = obj.get("@type")
        if obj_type is None:
            continue
        candidates = obj_type if isinstance(obj_type, list) else [obj_type]
        for t in candidates:
            if not isinstance(t, str):
                continue
            rank = _type_rank(t)
            if rank < best_rank:
                best_rank = rank
                best = t
                if rank == 0:
                    return best
    return best


def _find_microdata_type(structured: dict) -> str | None:
    """Return the highest-priority schema.org type found in microdata, or None."""
    best: str | None = None
    best_rank = len(_TYPE_PRIORITY) + 1
    for item in iter_microdata_items(structured):
        for t in type_names(item):
            rank = _type_rank(t)
            if rank < best_rank:
                best_rank = rank
                best = t
                if rank == 0:
                    return best
    return best


_CANONICAL_PATTERN = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _normalized_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _canonical_host_mismatch(html: str, url: str) -> str | None:
    """If the canonical link points to a different host than the requested URL,
    return the canonical URL. Relative canonicals and same-host canonicals return None."""
    m = _CANONICAL_PATTERN.search(html)
    if not m:
        return None
    canonical = m.group(1).strip()
    canonical_host = _normalized_host(canonical)
    if not canonical_host:
        return None
    if canonical_host != _normalized_host(url):
        return canonical
    return None


def _check_soft_404(html: str) -> bool:
    html_lower = html.lower()
    if 'content="noindex"' in html_lower or "content='noindex'" in html_lower:
        return True
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower, re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
        if any(phrase in title for phrase in ["not found", "404", "page not found"]):
            return True
    return False


def validate(html: str, url: str | None = None) -> ValidationResult:
    # 1. Canonical host mismatch — we were served a different page (e.g. NYT
    # Cooking substitutes the nytimes.com homepage when access is blocked).
    if url:
        wrong = _canonical_host_mismatch(html, url)
        if wrong:
            return ValidationResult("blocked", f"canonical host mismatch: {wrong}")

    # 2. JSON-LD or microdata — if present, the page has real structured content.
    # Punch uses microdata Recipe instead of JSON-LD; sometimes a JSON-LD wrapper
    # block (e.g. NewsArticle) coexists, so take the highest-priority type across
    # both sources.
    structured = extract_structured(html)
    jsonld_type = _find_jsonld_type(structured)
    microdata_type = _find_microdata_type(structured)
    sources: list[tuple[str, str]] = []
    if jsonld_type:
        sources.append(("JSON-LD", jsonld_type))
    if microdata_type:
        sources.append(("microdata", microdata_type))
    if sources:
        source, best_type = min(sources, key=lambda s: _type_rank(s[1]))
        return ValidationResult(best_type, f"{source} @type: {best_type}")

    # 3. No structured data — check for blockers
    if len(html.encode("utf-8")) < MIN_PAGE_SIZE:
        return ValidationResult("blocked", "Size under 5KB — likely not a content page")

    for fingerprint, reason in BLOCKER_FINGERPRINTS:
        if fingerprint in html:
            return ValidationResult("blocked", reason)

    if _check_soft_404(html):
        return ValidationResult("blocked", "Soft 404 detected")

    visible_text = _extract_visible_text(html)
    if len(visible_text) < MIN_TEXT_LENGTH:
        return ValidationResult("blocked", "Insufficient visible text — likely empty JS shell")

    # 4. Has content but no structured data
    return ValidationResult("unverified", "No structured data found")


# classify_drink lives in scraper.src.classify_drink — kept as a re-export so
# existing callers (fetch.py, revalidate.py, tests) don't need to change.
from scraper.src.classify_drink import classify_drink  # noqa: E402, F401
