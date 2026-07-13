"""Find a Schema.org Recipe object in a page's JSON-LD, with field derivation.

A stdlib-only reader (no extruct/bs4) so the ingredients package stays free of
the scraper's HTML dependencies: it pulls every ``<script type="application/
ld+json">`` block, tolerates malformed blocks, unfolds ``@graph`` wrappers and
top-level arrays, and returns the first object whose ``@type`` names a Recipe.
The `derive_*` helpers pull the website-facing header fields out of that object.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

_LD_JSON_RE = re.compile(
    r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _iter_jsonld_blocks(html: str) -> Iterator[Any]:
    for match in _LD_JSON_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue


def _iter_nodes(data: Any) -> Iterator[dict]:
    """Unfold @graph wrappers and arrays into individual JSON-LD dict nodes."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            for item in data["@graph"]:
                yield from _iter_nodes(item)
        yield data


def _type_names(obj: dict) -> Iterator[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        yield t
    elif isinstance(t, list):
        for item in t:
            if isinstance(item, str):
                yield item


def _is_recipe(obj: dict) -> bool:
    return any("Recipe" in name for name in _type_names(obj))


def find_recipe_jsonld(html: str) -> dict | None:
    """The first Schema.org Recipe object in the page's JSON-LD, or None."""
    for block in _iter_jsonld_blocks(html):
        for node in _iter_nodes(block):
            if _is_recipe(node):
                return node
    return None


def derive_name(recipe: dict) -> str | None:
    name = recipe.get("name")
    if isinstance(name, str):
        return name or None
    if isinstance(name, list):
        for n in name:
            if isinstance(n, str) and n:
                return n
    return None


def derive_author(recipe: dict) -> str | None:
    author = recipe.get("author")
    if isinstance(author, str):
        return author or None
    if isinstance(author, dict):
        name = author.get("name")
        return name if isinstance(name, str) and name else None
    if isinstance(author, list):
        for a in author:
            derived = derive_author({"author": a})
            if derived:
                return derived
    return None


def derive_image_url(recipe: dict) -> str | None:
    image = recipe.get("image")
    if isinstance(image, str):
        return image or None
    if isinstance(image, dict):
        url = image.get("url")
        return url if isinstance(url, str) and url else None
    if isinstance(image, list) and image:
        for item in image:
            derived = derive_image_url({"image": item})
            if derived:
                return derived
    return None
