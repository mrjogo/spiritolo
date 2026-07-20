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

from common.providers import FakeProvider, Item

from ingredients.worker.cost import CostMeter
from ingredients.worker.loop import _build_providers
from ingredients.worker.providers import DEFAULT_PACK_SIZE, ProviderChain


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
