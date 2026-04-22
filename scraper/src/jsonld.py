import json
from typing import Any

from bs4 import BeautifulSoup


def parse_recipe_from_html(html: str) -> dict | None:
    """Return the first Schema.org Recipe node found in any JSON-LD script tag, else None.

    Handles: multiple <script> blocks, @graph wrappers, top-level arrays,
    @type as string or array, and malformed JSON (skipped silently).
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        recipe = _find_recipe(data)
        if recipe is not None:
            return recipe
    return None


def _find_recipe(data: Any) -> dict | None:
    """Walk a JSON-LD payload and return the first node with @type='Recipe'."""
    if isinstance(data, list):
        for item in data:
            found = _find_recipe(item)
            if found is not None:
                return found
        return None
    if isinstance(data, dict):
        if _is_recipe(data):
            return data
        graph = data.get("@graph")
        if isinstance(graph, list):
            return _find_recipe(graph)
    return None


def _is_recipe(node: dict) -> bool:
    t = node.get("@type")
    if isinstance(t, str):
        return t == "Recipe"
    if isinstance(t, list):
        return "Recipe" in t
    return False


def derive_author(recipe: dict) -> str | None:
    author = recipe.get("author")
    if isinstance(author, str):
        return author or None
    if isinstance(author, dict):
        name = author.get("name")
        return name if isinstance(name, str) and name else None
    if isinstance(author, list):
        # Multiple authors → use the first with a usable name.
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
