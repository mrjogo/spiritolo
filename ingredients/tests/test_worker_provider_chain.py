"""WS-B23 — worker provider-chain seam (pure, no DB).

The worker resolves a stage's items through a ``ProviderChain`` built from
*external config* (an ordered list of provider ids + a pack size). The chain
short-circuits when a tier resolves everything, re-maps packed outputs back to
their entity ids, and parks per-item failures — all pinned here with fake
providers only, never a live model.

Reuses the ``common.providers`` building blocks (``FakeProvider``,
``DeterministicProvider``, ``Item``, ``StageChainConfig``) so the worker chain is
a thin wiring layer, not a re-implementation.
"""
from __future__ import annotations

from common.providers import DeterministicProvider, FakeProvider, Item
from common.providers.config import StageChainConfig

from ingredients.worker.providers import ProviderChain


def _resolve_all(value_fn):
    """A deterministic resolver that answers every item."""
    return lambda items: {it.id: value_fn(it) for it in items}


def _abstain(items):
    """A deterministic resolver that answers nothing (falls through)."""
    return {}


def test_chain_order_deterministic_first():
    # [deterministic, llm]; the deterministic tier resolves everything, so the
    # llm tier is never touched (short-circuit).
    det = DeterministicProvider(resolve_fn=_resolve_all(lambda it: f"det:{it.id}"))
    llm = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})
    config = StageChainConfig(stage="map", provider_ids=("det", "llm"), pack_size=2)

    chain = ProviderChain(config=config, providers={"det": det, "llm": llm})
    result = chain.resolve([Item("1"), Item("2")])

    assert result.resolved == {"1": "det:1", "2": "det:2"}
    assert result.parked == []
    assert llm.calls == 0, "llm tier must not be called once det resolves all"


def test_chain_falls_through_on_abstain():
    # deterministic abstains -> llm is reached; the STORED output equals the
    # llm fake's canned structured result (tier-independent stored shape).
    det = DeterministicProvider(resolve_fn=_abstain)
    llm = FakeProvider(canned_map={"1": {"node": "gin", "conf": 0.9}})
    config = StageChainConfig(stage="map", provider_ids=("det", "llm"), pack_size=1)

    chain = ProviderChain(config=config, providers={"det": det, "llm": llm})
    result = chain.resolve([Item("1")])

    assert result.resolved == {"1": {"node": "gin", "conf": 0.9}}
    assert llm.calls == 1


def test_chain_is_config_not_hardcoded():
    # Reordering the config ([llm, det] vs [det, llm]) changes which tier runs
    # first, with no code change — the seam is honored.
    det_factory = lambda: DeterministicProvider(
        resolve_fn=_resolve_all(lambda it: f"det:{it.id}")
    )
    items = [Item("1"), Item("2")]

    det_first = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})
    chain_det_first = ProviderChain(
        config=StageChainConfig(stage="map", provider_ids=("det", "llm"), pack_size=2),
        providers={"det": det_factory(), "llm": det_first},
    )
    chain_det_first.resolve(items)
    assert det_first.calls == 0, "with det first, llm never runs"

    llm_first = FakeProvider(canned_map={"1": "llm:1", "2": "llm:2"})
    chain_llm_first = ProviderChain(
        config=StageChainConfig(stage="map", provider_ids=("llm", "det"), pack_size=2),
        providers={"det": det_factory(), "llm": llm_first},
    )
    r = chain_llm_first.resolve(items)
    assert llm_first.calls == 1, "reorder to [llm, det] runs llm first — no code change"
    assert r.resolved == {"1": "llm:1", "2": "llm:2"}


def test_packing_maps_by_id():
    # A packed N-item request splits results back to the right entity ids, and a
    # partial provider failure parks ONLY the failed item (mirrors the
    # pending_llm_tried discipline) while resolving the rest.
    llm = FakeProvider(
        canned_map={"1": "A", "2": "B", "3": "C"},
        raises_for={"2"},
    )
    config = StageChainConfig(stage="map", provider_ids=("llm",), pack_size=2)

    chain = ProviderChain(config=config, providers={"llm": llm})
    result = chain.resolve([Item("1"), Item("2"), Item("3")])

    # Order-independent re-mapping: FakeProvider emits answers reversed, so the
    # values must be keyed by id, not by position.
    assert result.resolved == {"1": "A", "3": "C"}
    assert result.parked == ["2"]
    assert llm.calls == 2, "3 items at pack_size 2 -> ceil(3/2) == 2 calls"
