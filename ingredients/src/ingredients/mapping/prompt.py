"""Provider-agnostic prompt building and response parsing for map-ingredient.

The map stage sends each unresolved name to the LLM tier as one packed item
whose ``input`` is ``build_item_input``'s dict (name, unit, site, candidates);
``SYSTEM_PROMPT`` describes that input and the per-item answer, and
``MAP_ANSWER_SCHEMA`` is the answer's JSON schema. ``build_user_prompt`` is the
same input as a standalone prompt string, for one-name callers.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYSTEM_PROMPT = """\
You map free-text cocktail-recipe ingredient strings to canonical taxonomy nodes.

Each item's `input` is an object with:
- "name": a normalized ingredient string (e.g. "tanqueray gin", "lemon juice", "buffalo trace bourbon").
- "parser_unit": the unit recipes use it with (oz, ml, dash, or null). Helpful for distinguishing fruit-as-juice from fruit-as-garnish.
- "site": the source site name, or null.
- "candidates": plausible nodes already in the taxonomy, highest similarity first, each with its slug, display_name, similarity score, and immediate parent names.

You may ONLY attach the string to a node that already exists. You do NOT create,
propose, or place new nodes — anything without a confident existing match is
handled downstream. Each item's `answer` is ONE of these two JSON objects:

1. CHOOSE an existing candidate node (return its slug):
   {"action": "chose_slug", "slug": "<existing-candidate-slug>"}

2. ABSTAIN when no candidate confidently fits:
   {"action": "abstain", "slug": null}

Rules:
- Only ever return a slug that appears among that item's candidates.
- Choose a candidate only when it names the same ingredient, or the exact
  category the string names (e.g. "dry gin" -> "gin"); a merely related node
  (lemon for lime, rye for bourbon) is an abstain.
- Prefer "abstain" over guessing.
"""

# The per-item answer's JSON schema (strict-mode shaped: every key required).
MAP_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["chose_slug", "abstain"]},
        "slug": {"type": ["string", "null"]},
    },
    "required": ["action", "slug"],
    "additionalProperties": False,
}


def build_item_input(
    *,
    normalized_name: str,
    parser_unit: str | None,
    site: str | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """One name's LLM input: the name, its context, and its candidate nodes."""
    return {
        "name": normalized_name,
        "parser_unit": parser_unit,
        "site": site,
        "candidates": [
            {
                "slug": c.get("slug"),
                "display_name": c["display_name"],
                "similarity": round(float(c.get("similarity", 0.0)), 3),
                "parents": c.get("parents") or [],
            }
            for c in candidates
        ],
    }


def build_user_prompt(
    *,
    normalized_name: str,
    parser_unit: str | None,
    site: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    """``build_item_input`` as a standalone JSON prompt string."""
    return json.dumps(build_item_input(
        normalized_name=normalized_name, parser_unit=parser_unit, site=site,
        candidates=candidates,
    ))


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_VALID_ACTIONS = {"chose_slug", "abstain"}


def parse_response(raw: str) -> dict[str, Any]:
    """Parse the provider's response. Strips a single ```json fence wrap if present."""
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    obj = json.loads(text)
    action = obj.get("action")
    if action not in _VALID_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    return obj


def prompt_hash(
    normalized_name: str, parser_unit: str | None, site: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    """Stable hash of the prompt inputs, written to taxonomy_provenance.prompt_hash."""
    payload = json.dumps(
        {"name": normalized_name, "unit": parser_unit, "site": site,
         "candidates": [(c.get("slug"), c["display_name"]) for c in candidates]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
