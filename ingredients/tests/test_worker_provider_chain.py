"""Worker provider-chain seam (pure, no DB).

The worker resolves a run's residual items through a ``ProviderChain`` built from
the run's chosen LLM tier (``jobs.llm_provider`` / ``jobs.llm_model``) plus a
per-stage ``pack_size``. The chain short-circuits when a tier resolves
everything, re-maps packed outputs back to their entity ids, parks per-item
failures, and surfaces cumulative cost — all pinned here with fake providers
only, never a live model.

Deterministic tiers live inside the stage_fns in production, but the chain still
supports a ``resolve_items`` tier (any object exposing it), so the tier-order /
short-circuit coverage uses a tiny local deterministic stand-in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

import pytest

from common.llm.provider import ProviderResult
from common.providers import FakeProvider, Item, packing

from ingredients.worker.cost import CostMeter
from ingredients.worker.loop import _build_providers
from ingredients.worker.providers import (
    DEFAULT_PACK_SIZE,
    ProviderChain,
    ProviderUnavailable,
    _CONSECUTIVE_FAIL_ABORT,
    _MAX_LLM_ATTEMPTS,
)


@dataclass
class _Deterministic:
    """A pure resolver as a chain tier: exposes ``resolve_items`` like the
    alias/lexical tiers a stage_fn runs before handing residue to the chain."""

    resolve_fn: Callable[[list[Item]], dict[str, Any]]
    kind: str = "deterministic"

    def resolve_items(self, items: list[Item]) -> dict[str, Any]:
        return self.resolve_fn(items)


def _resolve_all(value_fn):
    """A deterministic resolver that answers every item."""
    return lambda items: {it.id: value_fn(it) for it in items}


def _abstain(items):
    """A deterministic resolver that answers nothing (falls through)."""
    return {}


def test_chain_order_deterministic_first():
    # [deterministic, llm]; the deterministic tier resolves everything, so the
    # llm tier is never touched (short-circuit).
    det = _Deterministic(resolve_fn=_resolve_all(lambda it: f"det:{it.id}"))
    llm = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})

    chain = ProviderChain(tiers=[("det", det), ("llm", llm)], pack_size=2)
    result = chain.resolve([Item("1"), Item("2")])

    assert result.resolved == {"1": "det:1", "2": "det:2"}
    assert result.parked == []
    assert llm.calls == 0, "llm tier must not be called once det resolves all"


def test_chain_falls_through_on_abstain():
    # deterministic abstains -> llm is reached; the STORED output equals the
    # llm fake's canned structured result (tier-independent stored shape).
    det = _Deterministic(resolve_fn=_abstain)
    llm = FakeProvider(canned_map={"1": {"node": "gin", "conf": 0.9}})

    chain = ProviderChain(tiers=[("det", det), ("llm", llm)], pack_size=1)
    result = chain.resolve([Item("1")])

    assert result.resolved == {"1": {"node": "gin", "conf": 0.9}}
    assert llm.calls == 1


def test_tier_order_is_the_list_order():
    # Reordering the tier list ([llm, det] vs [det, llm]) changes which tier runs
    # first — the chain honors the order it was handed.
    det_factory = lambda: _Deterministic(
        resolve_fn=_resolve_all(lambda it: f"det:{it.id}")
    )
    items = [Item("1"), Item("2")]

    det_first_llm = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})
    chain_det_first = ProviderChain(
        tiers=[("det", det_factory()), ("llm", det_first_llm)], pack_size=2
    )
    chain_det_first.resolve(items)
    assert det_first_llm.calls == 0, "with det first, llm never runs"

    llm_first = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})
    chain_llm_first = ProviderChain(
        tiers=[("llm", llm_first), ("det", det_factory())], pack_size=2
    )
    r = chain_llm_first.resolve(items)
    assert llm_first.calls == 1, "reorder to [llm, det] runs llm first"
    assert r.resolved == {"1": "llm:1", "2": "llm:2"}


def test_packing_maps_by_id():
    # A packed N-item request splits results back to the right entity ids, and a
    # partial provider failure parks ONLY the failed item (mirrors the
    # pending_llm_tried discipline) while resolving the rest.
    llm = FakeProvider(
        canned_map={"1": "A", "2": "B", "3": "C"},
        raises_for={"2"},
    )

    chain = ProviderChain(tiers=[("llm", llm)], pack_size=2)
    result = chain.resolve([Item("1"), Item("2"), Item("3")])

    # Order-independent re-mapping: FakeProvider emits answers reversed, so the
    # values must be keyed by id, not by position.
    assert result.resolved == {"1": "A", "3": "C"}
    assert result.parked == ["2"]
    assert llm.calls == 2, "3 items at pack_size 2 -> ceil(3/2) == 2 calls"


def test_metered_tier_surfaces_cost():
    # A hosted (metered) LLM tier reports cost_cents per call and marks the chain
    # metered; the per-tier breakdown carries the provider id + cost.
    hosted = FakeProvider(canned_map={"a": {"n": 1}, "b": {"n": 2}}, cost_per_call=7)
    chain = ProviderChain(
        tiers=[("openai", hosted)], pack_size=10, meter=CostMeter(cap_cents=None)
    )

    res = chain.resolve([Item("a", "x"), Item("b", "y")])

    assert res.resolved == {"a": {"n": 1}, "b": {"n": 2}}
    assert res.cost_cents == 7  # one packed hosted call at 7 cents
    assert res.metered is True
    tier = res.tiers[0]
    assert tier.provider_id == "openai"
    assert tier.cost_cents == 7
    assert tier.metered is True


def test_build_providers_uses_the_runs_provider_and_model():
    # A job selecting claude+model builds a chain whose LLM tier carries exactly
    # that provider id and model, at the stage's pack size, bound to the cap.
    job = {
        "stage": "map-ingredient",
        "llm_provider": "claude",
        "llm_model": "claude-sonnet-4-5",
        "max_cost_cents": 500,
    }
    chain = _build_providers(job, env={"ANTHROPIC_API_KEY": "sk-a"})

    assert isinstance(chain, ProviderChain)
    assert chain.pack_size == DEFAULT_PACK_SIZE
    assert chain.meter.cap_cents == 500
    [(provider_id, impl)] = chain.tiers
    assert provider_id == "claude"
    assert impl.model_id == "claude-sonnet-4-5"


def test_build_providers_no_provider_is_none():
    # A run that names no LLM tier -> no chain (deterministic-only run).
    job = {"stage": "map-ingredient", "llm_provider": None, "llm_model": None}
    assert _build_providers(job, env={}) is None


def test_build_providers_missing_key_is_none():
    # Named a hosted provider but no key in env -> no chain, no crash.
    job = {"stage": "map-ingredient", "llm_provider": "openai", "llm_model": "gpt-5-mini"}
    assert _build_providers(job, env={}) is None


# --- LLM error isolation, retry + circuit breaker ---------------------------


class _FatalStatusError(Exception):
    """A non-retryable provider error (auth/billing/bad request), like the
    DeepSeek `402 Insufficient Balance` that killed run #7."""

    status_code = 402

    def __str__(self) -> str:
        return "Insufficient Balance"


class _TransientStatusError(Exception):
    """A retryable provider error (5xx / rate limit)."""

    status_code = 503


@dataclass
class _RaisingProvider:
    """Raises ``exc`` on the first ``fail_calls`` resolve()s, then answers from
    ``canned`` — lets a test drive the retry/park/abort paths deterministically."""

    exc: Exception
    fail_calls: int
    canned: dict[str, Any] | None = None
    cost_per_call: int = 0
    calls: int = 0

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.calls += 1
        if self.calls <= self.fail_calls:
            raise self.exc
        canned = self.canned or {}
        ids = packing.decode_request(user_prompt)
        rows = [{"id": i, "answer": canned.get(i, f"a:{i}")} for i in ids]
        return ProviderResult(raw_text=packing.encode_response(rows), model_id="x")


@pytest.fixture
def _no_backoff(monkeypatch):
    monkeypatch.setattr("ingredients.worker.providers.time.sleep", lambda *_: None)


def test_llm_transient_error_retries_then_succeeds(_no_backoff):
    # Two transient failures then a success on the same pack -> resolved, no park.
    prov = _RaisingProvider(exc=_TransientStatusError(), fail_calls=2, canned={"1": "A"})
    chain = ProviderChain(tiers=[("ollama", prov)], pack_size=1)

    res = chain.resolve([Item("1")])

    assert res.resolved == {"1": "A"}
    assert res.parked == []
    assert prov.calls == 3  # 2 retries + the success


def test_llm_transient_exhausts_retries_parks_pack_and_continues(_no_backoff):
    # The first pack fails all its attempts and parks; later packs still resolve.
    # One 503 blip must not lose the other 7,000 items.
    prov = _RaisingProvider(
        exc=_TransientStatusError(),
        fail_calls=_MAX_LLM_ATTEMPTS,  # exactly kills pack #1's attempts
        canned={"2": "B", "3": "C"},
    )
    chain = ProviderChain(tiers=[("ollama", prov)], pack_size=1)

    res = chain.resolve([Item("1"), Item("2"), Item("3")])

    assert res.resolved == {"2": "B", "3": "C"}
    assert res.parked == ["1"]


def test_llm_fatal_error_aborts_run_fast():
    # A fatal (402) error is not retried and aborts the whole run immediately
    # with the provider's message surfaced (this is exactly run #7).
    prov = _RaisingProvider(exc=_FatalStatusError(), fail_calls=99)
    chain = ProviderChain(tiers=[("deepseek", prov)], pack_size=1, meter=CostMeter(1000))

    with pytest.raises(ProviderUnavailable) as excinfo:
        chain.resolve([Item("1"), Item("2")])

    assert "402" in str(excinfo.value)
    assert "Insufficient Balance" in str(excinfo.value)
    assert prov.calls == 1  # fatal -> no retry, abort on the first pack


def test_llm_circuit_breaker_aborts_after_consecutive_pack_failures(_no_backoff):
    # Persistent transient errors: each pack retries then parks; after
    # _CONSECUTIVE_FAIL_ABORT parked packs the breaker fails the run fast
    # instead of grinding every remaining pack into the same wall.
    prov = _RaisingProvider(exc=_TransientStatusError(), fail_calls=999)
    chain = ProviderChain(tiers=[("ollama", prov)], pack_size=1)

    with pytest.raises(ProviderUnavailable):
        chain.resolve([Item(str(i)) for i in range(10)])

    assert prov.calls == _CONSECUTIVE_FAIL_ABORT * _MAX_LLM_ATTEMPTS
