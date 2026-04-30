"""LLM prompt for cocktail-name canonicalization.

Action vocabulary:
  - "chose"    : pick one of the supplied candidate canonical names.
  - "propose"  : the title is a real cocktail not yet seen; propose a new
                 canonical name. The orchestrator auto-adds the alias.
  - "abstain"  : the title is editorial noise, not a cocktail, or the
                 model can't decide. Orchestrator stamps abstain.

Output shape (always JSON, single object):

  {"action": "chose",   "canonical_name": "<existing canonical>"}
  {"action": "propose", "canonical_name": "<new canonical>"}
  {"action": "abstain"}

Mirrors mapping/prompt.py shape; the action set differs because cocktail
names don't have a parent-child structure to traverse.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYSTEM_PROMPT = """You canonicalize cocktail recipe titles.

Given a raw recipe title and a list of candidate canonical cocktail
names already known, you must return a single JSON object describing
your decision:

  - "chose": one of the candidate canonical names matches; pick it.
  - "propose": the title is a real cocktail not in the candidates;
    propose a new canonical name (lowercase, no articles, no
    "cocktail"/"recipe" suffix, no editorial words).
  - "abstain": the title is editorial noise, an unrelated drink, or you
    cannot decide.

Be conservative. If the raw title has editorial decoration ("Best",
"Classic", "Perfect", "How to Make a", trailing "Recipe" / "Cocktail")
around an existing candidate, "chose" that candidate. If the title
includes a meaningful prefix ("Mezcal Negroni", "Smoked Old Fashioned",
"Hemingway Daiquiri"), it is a *different* drink — propose a new
canonical or chose a candidate that already includes the prefix.

Output JSON only. No prose. No code fences."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def build_user_prompt(
    *, raw_name: str, normalized: str,
    candidates: list[dict[str, Any]],
) -> str:
    cand_lines = "\n".join(
        f"  - {c['canonical_name']!r} (similarity={c['similarity']:.2f})"
        for c in candidates
    ) or "  (none — propose or abstain)"
    return (
        f"Raw title: {raw_name!r}\n"
        f"Normalized: {normalized!r}\n"
        f"\n"
        f"Candidate canonical names:\n{cand_lines}\n"
        f"\n"
        f"Return one JSON object per the system prompt's vocabulary."
    )


def parse_response(raw: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", raw).strip()
    obj = json.loads(cleaned)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
    action = obj.get("action")
    if action not in {"chose", "propose", "abstain"}:
        raise ValueError(f"Unknown action: {action!r}")
    if action in {"chose", "propose"} and not obj.get("canonical_name"):
        raise ValueError(f"Action {action!r} missing canonical_name")
    return obj


def prompt_hash(
    raw_name: str, normalized: str, candidates: list[dict[str, Any]],
) -> str:
    """Stable hash for prompt-cache provenance / dedup.

    Sorting candidate list keeps the hash stable across pg_trgm tie orderings.
    """
    sorted_cands = sorted(
        ({"canonical_name": c["canonical_name"]} for c in candidates),
        key=lambda c: c["canonical_name"],
    )
    payload = json.dumps(
        {"raw": raw_name, "normalized": normalized, "candidates": sorted_cands},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
