import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser


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


def _find_jsonld_type(html: str) -> str | None:
    """Return the first @type found across all JSON-LD blocks, or None."""
    for obj in _iter_jsonld_objects(html):
        obj_type = obj.get("@type")
        if obj_type is None:
            continue
        if isinstance(obj_type, list):
            if obj_type:
                return obj_type[0]
        else:
            return obj_type
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


def validate(html: str) -> ValidationResult:
    # 1. JSON-LD — if present, the page has real structured content
    jsonld_type = _find_jsonld_type(html)
    if jsonld_type:
        return ValidationResult(jsonld_type, f"JSON-LD @type: {jsonld_type}")

    # 2. No JSON-LD — check for blockers
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

    # 3. Has content but no JSON-LD
    return ValidationResult("unverified", "No JSON-LD found")
