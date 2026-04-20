import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse


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


_JSONLD_PATTERN = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _iter_jsonld_objects(html: str):
    """Yield all top-level objects from JSON-LD blocks."""
    for match in _JSONLD_PATTERN.finditer(html):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        candidates = []
        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            if "@graph" in data:
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)

        for obj in candidates:
            if isinstance(obj, dict):
                yield obj


_TYPE_PRIORITY = ("Recipe", "NewsArticle", "Article", "WebPage", "WebSite")


def _type_rank(t: str) -> int:
    if t in _TYPE_PRIORITY:
        return _TYPE_PRIORITY.index(t)
    return len(_TYPE_PRIORITY)


def _find_jsonld_type(html: str) -> str | None:
    """Return the highest-priority @type across all JSON-LD blocks, or None.

    Priority: Recipe > NewsArticle > Article > WebPage > WebSite > other. Needed
    because sites like Tasting Table emit a wrapper Article block before the
    Recipe block — picking "first type seen" would misclassify recipes.
    """
    best: str | None = None
    best_rank = len(_TYPE_PRIORITY) + 1
    for obj in _iter_jsonld_objects(html):
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

    # 2. JSON-LD — if present, the page has real structured content
    jsonld_type = _find_jsonld_type(html)
    if jsonld_type:
        return ValidationResult(jsonld_type, f"JSON-LD @type: {jsonld_type}")

    # 3. No JSON-LD — check for blockers
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

    # 4. Has content but no JSON-LD
    return ValidationResult("unverified", "No JSON-LD found")


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
