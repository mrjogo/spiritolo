"""Apply an LLM tier's per-name answer to the shared name-keyed resolution.

The deterministic tiers (alias, lexical) resolve a name straight to a taxonomy
slug. The LLM tier may only *attach a name to an existing node* or abstain — it
never proposes or creates taxonomy structure. Anything it can't attach is left
for the deterministic mint pass (``mapping.mint``), which mints a provisional
node. This module is the single place the LLM answer turns into a DB write:

  chose_slug -> write the resolution to an existing slug
  abstain    -> record a deliberate abstain (leaving the name for the mint pass)

The chain-answer contract per name is one of:
  - a bare slug string                       -> chose that slug
  - {"action": "chose_slug", "slug": <str>}
  - {"action": "abstain"}  (or None when the tier dropped the name)
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.mapping.resolutions import write_abstain, write_resolution


def apply_llm_action(
    conn: psycopg.Connection,
    *,
    normalized_name: str,
    answer: Any,
    version: str,
    model_id: str | None = None,
) -> str:
    """Apply one name's LLM answer to the DB; return the action taken.

    Return values: ``chose`` | ``abstain``. An abstain leaves the name without a
    live match; the map stage's mint pass then mints a provisional node for it
    (unless the name can't be slugified, in which case the abstain stands).
    """
    if answer is None:
        write_abstain(conn, normalized_name=normalized_name, version=version)
        return "abstain"

    if isinstance(answer, str):
        write_resolution(
            conn,
            normalized_name=normalized_name,
            taxonomy_slug=answer,
            method="llm",
            version=version,
            model_id=model_id,
        )
        return "chose"

    action = answer.get("action")

    if action == "chose_slug":
        slug = answer.get("slug")
        if not slug:
            write_abstain(conn, normalized_name=normalized_name, version=version)
            return "abstain"
        write_resolution(
            conn,
            normalized_name=normalized_name,
            taxonomy_slug=slug,
            method="llm",
            version=version,
            model_id=model_id,
        )
        return "chose"

    write_abstain(conn, normalized_name=normalized_name, version=version)
    return "abstain"
