"""Phase 2 orchestrator. Drains the pending_llm queue using a chosen provider.

Reuses:
  - mapping.llm_provider.LLMProvider (the Protocol)
  - mapping.llm_resolver.resolve_with_retry (the retry helper)

Branching by LLM action:
  chose    -> write_normalization(source='llm')
  propose  -> add_cocktail_alias + write_normalization(source='llm')
  abstain  -> write_normalize_abstain
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg

from ingredients.mapping.llm_provider import LLMProvider
from ingredients.mapping.llm_resolver import resolve_with_retry

from .db import (
    add_cocktail_alias,
    fetch_pending_canonical_names,
    write_normalization,
    write_normalize_abstain,
)
from .lexical_layer import lexical_candidates
from .normalize import normalize_cocktail_name
from .prompt import SYSTEM_PROMPT, build_user_prompt, parse_response as _parse_response
from .version import NORMALIZER_VERSION

log = logging.getLogger("dedup.normalizer_llm")


def run_phase2(
    conn: psycopg.Connection,
    *,
    provider: LLMProvider,
    limit: int | None = None,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    raw_names = fetch_pending_canonical_names(
        conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
    )
    for raw in raw_names:
        normalized = normalize_cocktail_name(raw)
        cands = lexical_candidates(conn, normalized, limit=20)
        user_prompt = build_user_prompt(
            raw_name=raw, normalized=normalized, candidates=cands,
        )
        action_obj = resolve_with_retry(
            provider,
            system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
            normalized_name=normalized,
            parse_fn=_parse_response,
        )
        if action_obj is None:
            counts["error"] += 1
            continue
        action = action_obj["action"]

        if action == "chose":
            canonical = action_obj["canonical_name"]
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["chose"] += 1
        elif action == "propose":
            canonical = action_obj["canonical_name"]
            add_cocktail_alias(
                conn, alias=normalized, canonical_name=canonical, source="llm",
            )
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["propose"] += 1
        elif action == "abstain":
            write_normalize_abstain(
                conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION,
            )
            counts["abstain"] += 1
    return dict(counts)
