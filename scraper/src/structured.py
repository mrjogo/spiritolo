"""Shared Schema.org structured-data helpers.

Both the validator (which classifies pages by @type) and the extractor (which
pulls Recipe content) need a uniform view across JSON-LD and HTML microdata.

JSON-LD is parsed per-<script>-block with json.loads so a single malformed
block doesn't nuke the rest of the page's structured data (extruct aborts the
whole syntax on the first JSONDecodeError). Microdata comes from extruct with
`uniform=True`, which natively reshapes items into JSON-LD form — so downstream
code sees one schema regardless of source.
"""

import json
import re
from typing import Any, Iterator

import extruct
from bs4 import BeautifulSoup

_SCHEMA_ORG_PREFIX = re.compile(r"^https?://schema\.org/")


def _parse_jsonld_scripts(html: str) -> list:
    """Return the list of JSON objects parsed from every <script type='application/ld+json'>
    block, silently skipping malformed blocks."""
    out: list = []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            out.append(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _parse_microdata(html: str) -> list:
    try:
        return extruct.extract(
            html, syntaxes=["microdata"], uniform=True, errors="ignore"
        ).get("microdata", [])
    except Exception:
        return []


def extract_structured(html: str) -> dict:
    """Parse JSON-LD and microdata out of HTML. Never raises. Microdata is
    returned in JSON-LD shape (via extruct's `uniform=True`)."""
    return {
        "json-ld": _parse_jsonld_scripts(html),
        "microdata": _parse_microdata(html),
    }


def iter_jsonld_objects(structured: dict) -> Iterator[dict]:
    """Yield top-level JSON-LD dict objects, unfolding @graph wrappers and
    top-level arrays."""
    for obj in structured.get("json-ld", []):
        yield from _iter_jsonld_nodes(obj)


def _iter_jsonld_nodes(data: Any) -> Iterator[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _iter_jsonld_nodes(item)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for inner in graph:
                yield from _iter_jsonld_nodes(inner)
        else:
            yield data


def iter_microdata_items(structured: dict) -> Iterator[dict]:
    """Yield microdata items (already JSON-LD shaped via extruct uniform=True)."""
    for item in structured.get("microdata", []):
        if isinstance(item, dict):
            yield item


def type_names(obj: dict) -> Iterator[str]:
    """Yield bare schema.org type names from a JSON-LD-shaped dict's @type."""
    raw = obj.get("@type")
    if raw is None:
        return
    types = raw if isinstance(raw, list) else [raw]
    for t in types:
        if isinstance(t, str):
            yield _SCHEMA_ORG_PREFIX.sub("", t)


def _has_recipe_type(obj: dict) -> bool:
    return any("Recipe" in t for t in type_names(obj))


def iter_recipes(structured: dict) -> Iterator[dict]:
    """Yield Recipe-typed objects from both JSON-LD and microdata as JSON-LD-shaped dicts."""
    for obj in iter_jsonld_objects(structured):
        if _has_recipe_type(obj):
            yield obj
    for item in iter_microdata_items(structured):
        if _has_recipe_type(item):
            yield item


def find_recipe(html: str) -> dict | None:
    """Return the first Schema.org Recipe found in JSON-LD or microdata, else None."""
    structured = extract_structured(html)
    for recipe in iter_recipes(structured):
        return recipe
    return None
