"""Provider-agnostic prompt building and response parsing.

Both providers (claude, ollama) speak the same JSON-out contract so the
provider modules stay thin. The system prompt names the legal actions
and the JSON shapes; the user prompt assembles per-string context.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYSTEM_PROMPT = """\
You map free-text cocktail-recipe ingredient strings to canonical taxonomy nodes.

You receive:
- A normalized ingredient string (e.g. "tanqueray gin", "lemon juice", "Buffalo Trace bourbon").
- The unit the recipe used (oz, ml, dash, none, ...). Helpful for distinguishing fruit-as-juice from fruit-as-garnish.
- Optionally a source site name.
- A list of plausible candidate nodes already in the taxonomy, with their immediate parent names and a similarity score.

You choose ONE of four actions and reply with a single JSON object, no commentary:

1. CHOOSE an existing candidate node:
   {"action": "chose", "node_id": <int>}

2. PROPOSE a new brand or expression node when the string clearly names a real product whose parent category is already present in the candidates:
   {"action": "propose_brand", "slug": "<snake_case>", "display_name": "<Title Case>",
    "parent_slug": "<existing_parent_slug>", "role": "brand" | "expression"}

3. PROPOSE a new form node (e.g. "lemon zest", "lime oil") when the string names a substance form not already in the taxonomy:
   {"action": "propose_form", "slug": "<snake_case>", "display_name": "<Title Case>",
    "parent_slug": "<existing_parent_slug>"}

4. ABSTAIN when you genuinely cannot tell:
   {"action": "abstain"}

Rules:
- Never invent a parent_slug that isn't in the candidates' parents.
- Prefer "chose" over "propose_*" when a candidate clearly fits.
- Prefer "abstain" over guessing.
- Output JSON only. No prose, no markdown fences.
"""


def build_user_prompt(
    *,
    normalized_name: str,
    parser_unit: str | None,
    site: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    cand_lines = [
        json.dumps({
            "node_id": c["node_id"],
            "display_name": c["display_name"],
            "similarity": round(float(c.get("similarity", 0.0)), 3),
            "parents": c.get("parents") or [],
        })
        for c in candidates
    ]
    context = json.dumps({
        "name": normalized_name,
        "parser_unit": parser_unit,
        "site": site,
    })
    return (
        "INPUT:\n" + context + "\n\n"
        "CANDIDATES (highest similarity first):\n"
        + ("\n".join(cand_lines) if cand_lines else "(none)")
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_VALID_ACTIONS = {"chose", "propose_brand", "propose_form", "abstain"}


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
         "candidates": [(c["node_id"], c["display_name"]) for c in candidates]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
