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

from common.llm import LLMProvider
from common.llm.batch_provider import BatchProvider, BatchRequest
from common.llm.batch_runner import (
    BatchSubmitOutcome, ingest_batch, submit_batch,
)
from common.llm.retry import resolve_with_retry

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
    from common.interrupt import InterruptHandler
    from common.progress import make_progress

    counts: Counter[str] = Counter()
    raw_names = fetch_pending_canonical_names(
        conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
    )
    total = len(raw_names)
    if total == 0:
        log.info("nothing pending; queue is empty")
        return dict(counts)
    log.info("Phase 2: resolving %d distinct names via %s", total, provider.model_id)
    progress = make_progress(total=total)

    with InterruptHandler() as interrupt:
        for idx, raw in enumerate(raw_names, start=1):
            if interrupt.requested:
                # First Ctrl-C: in-flight LLM call (if any) has finished
                # and its result was written by the per-call commit. Stop
                # before paying for the next one.
                break
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
                progress(idx)
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
            progress(idx)
    return dict(counts)


def submit_normalize_names_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batches_dir,
    limit: int | None = None,
) -> BatchSubmitOutcome:
    """Submit pending canonical-name resolutions as an OpenAI batch."""
    from common.progress import make_progress

    raw_names = fetch_pending_canonical_names(
        conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
    )
    if not raw_names:
        raise RuntimeError("nothing pending; queue is empty")
    total = len(raw_names)

    log.info("building %d prompts (lexical lookup per name)…", total)
    progress = make_progress(total=total)
    rows = []
    for idx, raw in enumerate(raw_names, start=1):
        normalized = normalize_cocktail_name(raw)
        cands = lexical_candidates(conn, normalized, limit=20)
        user_prompt = build_user_prompt(
            raw_name=raw, normalized=normalized, candidates=cands,
        )
        rows.append((raw, SYSTEM_PROMPT, user_prompt))
        progress(idx)

    log.info("submitting %d-request batch to %s…", total, provider.model_id)
    return submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(
            custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2],
        ),
        row_to_id=lambda r: r[0],
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        batches_dir=batches_dir,
    )


def ingest_normalize_names_batch(
    conn: psycopg.Connection,
    *,
    provider: BatchProvider,
    batch_id: str,
    batches_dir,
) -> dict[str, int]:
    """Ingest a previously submitted normalize-names batch."""

    def on_result(row_id: str, raw_text: str | None, error: str | None) -> None:
        if error or raw_text is None:
            log.warning("batch result error for %r: %s", row_id, error)
            return
        try:
            action_obj = _parse_response(raw_text)
        except Exception as exc:
            log.warning("batch result parse failed for %r: %s", row_id, exc)
            return
        action = action_obj["action"]
        raw = row_id
        normalized = normalize_cocktail_name(raw)

        if action == "chose":
            canonical = action_obj["canonical_name"]
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
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
        elif action == "abstain":
            write_normalize_abstain(
                conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION,
            )

    return ingest_batch(
        provider=provider, batch_id=batch_id,
        flow="dedup.normalize_names.resolve_pending",
        version_constant=NORMALIZER_VERSION,
        on_result=on_result,
        batches_dir=batches_dir,
    )
