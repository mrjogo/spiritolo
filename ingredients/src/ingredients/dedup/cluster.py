"""Pure cluster + variant key derivation.

Cluster identity is ``hash(canonical_name, role-tagged ingredient set rolled up
to the curated antichain)``. The set is keyed by taxonomy **slugs** (portable,
correction-stable), not node ids — so re-pointing a resolution never silently
rewrites a cluster key for an unrelated reason. Two recipes share a variant iff,
within the same cluster, their specific ingredient slugs + amounts + units match.

The allow-list (``INCLUDED_ROLES``) is the invariant the spec calls out: a role
added elsewhere does NOT enter the cluster key without an explicit addition here
AND a ``DEDUP_VERSION`` bump.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

INCLUDED_ROLES = frozenset({
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "wash", "other",
})


def in_cluster_key(ing: dict[str, Any]) -> bool:
    """Whether an ingredient contributes to the cluster key.

    An ingredient with no antichain slug (unresolved, or rolled up to nothing)
    is excluded — treated as role='other' off the key, per spec, and so
    ``sorted()`` never sees a None slug. A garnish counts only when it is a
    defining garnish; otherwise its role must be in ``INCLUDED_ROLES``.
    """
    if ing.get("antichain_slug") is None:
        return False
    role = ing.get("role")
    if role == "garnish":
        return bool(ing.get("is_defining_garnish"))
    return role in INCLUDED_ROLES


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_cluster_key(canonical_name: str, ingredients: list[dict[str, Any]]) -> str:
    """Cluster identity = sha256(canonical_name, sorted set of (role, antichain_slug))."""
    members = sorted(
        (ing["role"], ing["antichain_slug"])
        for ing in ingredients
        if in_cluster_key(ing)
    )
    payload = _canonical_json({
        "canonical_name": canonical_name,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _none_safe_sort_key(t: tuple[Any, ...]) -> tuple[Any, ...]:
    """Wrap each tuple element so None is comparable with any concrete type
    (Python 3 raises on ``None < 1.5``); expands each value to ``(is_none, value)``."""
    return tuple((v is None, v) for v in t)


def compute_variant_key(cluster_key: str, ingredients: list[dict[str, Any]]) -> str:
    """Variant identity adds the specific ingredient slug + amount/amount_max/unit.
    Two recipes share a variant iff their amounts + specific ingredients match
    within the same cluster."""
    members = sorted(
        (
            (
                ing["role"],
                ing["antichain_slug"],
                ing.get("taxonomy_slug"),
                ing.get("amount"),
                ing.get("amount_max"),
                ing.get("unit"),
            )
            for ing in ingredients
            if in_cluster_key(ing)
        ),
        key=_none_safe_sort_key,
    )
    payload = _canonical_json({
        "cluster_key": cluster_key,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ingredient_set_json(ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stored ``recipe_clusters.ingredient_set`` snapshot: the distinct
    (role, antichain_slug) members the cluster key hashed, in a stable order."""
    items = sorted(
        {
            (ing["role"], ing["antichain_slug"])
            for ing in ingredients
            if in_cluster_key(ing)
        }
    )
    return [{"role": role, "antichain_slug": slug} for role, slug in items]
