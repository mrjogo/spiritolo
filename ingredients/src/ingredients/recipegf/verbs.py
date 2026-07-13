"""Load the in-repo ``spiritolo/`` extension verb-defs and build overlays.

The verb-defs live as self-describing YAML under ``verbs/`` (each repo
iterates verbs freely in its own repo, no RecipeGF PR per verb). This module is
the single place that reads them, so both the converter (which needs to know
which spiritolo verbs exist and their required roles) and the bundle exporter
(which embeds the defs a recipe actually uses) share one source of truth.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from recipegf import VerbRegistry

_VERBS_DIR = Path(__file__).resolve().parent / "verbs"


@lru_cache(maxsize=1)
def spiritolo_verb_defs() -> dict[str, dict[str, Any]]:
    """Map ``spiritolo/<verb>`` → its parsed verb-definition dict.

    Read once and cached. Keyed by the fully-qualified verb name carried in
    each def's ``verb`` field, so callers can look defs up by the name that
    appears on a step.
    """
    defs: dict[str, dict[str, Any]] = {}
    for path in sorted(_VERBS_DIR.glob("*.yaml")):
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        defs[definition["verb"]] = definition
    return defs


def is_spiritolo_verb(verb: str) -> bool:
    """True iff ``verb`` is one of the in-repo ``spiritolo/`` extension verbs."""
    return verb in spiritolo_verb_defs()


def verb_defs_for(verbs: list[str]) -> list[dict[str, Any]]:
    """The spiritolo/ verb-defs referenced by ``verbs``, de-duplicated and in a
    stable (sorted-by-name) order. Core verbs in ``verbs`` are ignored — they
    live in RecipeGF's own registry and never travel in a bundle.

    This is exactly the list that goes into a pin-2 bundle's ``verbs`` array:
    only the extension defs the recipe actually uses.
    """
    all_defs = spiritolo_verb_defs()
    used = sorted({v for v in verbs if v in all_defs})
    return [all_defs[v] for v in used]


def overlay_registry(defs: list[dict[str, Any]] | None = None) -> VerbRegistry:
    """A ``core ∪ spiritolo/`` VerbRegistry.

    With ``defs=None`` (default), overlays *all* in-repo spiritolo verb-defs —
    the registry the converter validates against. With an explicit ``defs``
    list (e.g. ``bundle["verbs"]``), overlays exactly those — the registry a
    consumer rebuilds to validate a received bundle.
    """
    overlay = list(spiritolo_verb_defs().values()) if defs is None else defs
    return VerbRegistry().load_overlay(overlay)
