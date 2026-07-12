"""B7 — config-not-code provider chain.

Pins: order comes from external config (reorder without code change);
the deterministic tier short-circuits later tiers; the stored/hashed output
is tier-independent; hosted tiers report cumulative cost + metered while
deterministic/local tiers report zero cost + metered=false.

Pure Python — no DB, no network, no live model. The LLM seam is FakeProvider.
"""
from __future__ import annotations

import hashlib
import json

from common.providers import (
    DeterministicProvider,
    FakeProvider,
    Item,
    load_stage_config,
    run_chain,
)


def _hash_stored(output) -> str:
    """The stable digest a downstream dedup/cluster stage would key off."""
    return hashlib.sha256(
        json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_chain_order_from_config():
    """A stage config ['deterministic','local'] calls providers in that order;
    reordering the config reorders the calls with no code change."""
    order: list[str] = []

    def recorder(pid: str) -> DeterministicProvider:
        def fn(items):
            order.append(pid)
            return {}  # abstain on everything so both tiers are reached
        return DeterministicProvider(fn)

    providers = {"deterministic": recorder("deterministic"), "local": recorder("local")}
    items = [Item("a", "vodka")]

    cfg_a = load_stage_config("map", {"providers": ["deterministic", "local"], "pack_size": 1})
    run_chain(items, cfg_a, providers)
    assert order == ["deterministic", "local"]

    order.clear()
    # Only the config data changed — no code path edited between the two runs.
    cfg_b = load_stage_config("map", {"providers": ["local", "deterministic"], "pack_size": 1})
    run_chain(items, cfg_b, providers)
    assert order == ["local", "deterministic"]


def test_deterministic_short_circuits():
    """When the deterministic tier resolves an item, the llm tier is never
    invoked; on abstain the next tier is reached and resolves it."""
    cfg = load_stage_config("map", {"providers": ["deterministic", "llm"], "pack_size": 10})

    det_hit = DeterministicProvider(lambda items: {it.id: {"node": "vodka"} for it in items})
    fake = FakeProvider(canned_map={"a": {"node": "vodka"}}, cost_per_call=5)
    res = run_chain([Item("a", "vodka")], cfg, {"deterministic": det_hit, "llm": fake})
    assert res.resolved == {"a": {"node": "vodka"}}
    assert fake.calls == 0  # short-circuit: llm tier never touched

    det_miss = DeterministicProvider(lambda items: {})  # abstains
    fake2 = FakeProvider(canned_map={"a": {"node": "vodka"}}, cost_per_call=5)
    res2 = run_chain([Item("a", "vodka")], cfg, {"deterministic": det_miss, "llm": fake2})
    assert res2.resolved == {"a": {"node": "vodka"}}
    assert fake2.calls == 1  # on abstain the next tier is reached


def test_stored_output_is_pinned():
    """The chain returns the exact structured output the downstream stage will
    store/hash, byte-identical regardless of which tier produced it."""
    stored = {"canonical": "daiquiri", "ingredients": ["rum", "lime", "sugar"]}

    det = DeterministicProvider(lambda items: {it.id: stored for it in items})
    cfg_det = load_stage_config("dedup", {"providers": ["deterministic"], "pack_size": 1})
    r_det = run_chain([Item("x", "daiquiri")], cfg_det, {"deterministic": det})

    fake = FakeProvider(canned_map={"x": stored}, cost_per_call=3)
    cfg_llm = load_stage_config("dedup", {"providers": ["llm"], "pack_size": 5})
    r_llm = run_chain([Item("x", "daiquiri")], cfg_llm, {"llm": fake})

    assert r_det.resolved["x"] == stored
    assert r_llm.resolved["x"] == stored
    assert r_det.resolved["x"] == r_llm.resolved["x"]
    assert _hash_stored(r_det.resolved["x"]) == _hash_stored(r_llm.resolved["x"])


def test_metered_flag_and_cost():
    """A hosted tier reports cost_cents per call; the chain surfaces cumulative
    cost and marks the tier metered. Deterministic/local tiers report zero cost
    and metered=false."""
    det = DeterministicProvider(lambda items: {})  # abstains, free
    hosted = FakeProvider(canned_map={"a": {"n": 1}, "b": {"n": 2}}, cost_per_call=7)
    cfg = load_stage_config("map", {"providers": ["deterministic", "openai"], "pack_size": 10})

    res = run_chain([Item("a", "x"), Item("b", "y")], cfg, {"deterministic": det, "openai": hosted})
    assert res.resolved == {"a": {"n": 1}, "b": {"n": 2}}
    assert res.cost_cents == 7  # one packed hosted call at 7 cents
    assert res.metered is True

    by_id = {t.provider_id: t for t in res.tiers}
    assert by_id["deterministic"].cost_cents == 0
    assert by_id["deterministic"].metered is False
    assert by_id["openai"].cost_cents == 7
    assert by_id["openai"].metered is True


def test_local_tier_is_free_and_unmetered():
    """A local (barbot/ollama) LLM tier is packed like any LLM but reports
    zero cost and metered=false because its per-call cost is 0."""
    local = FakeProvider(canned_map={"a": {"n": 1}}, cost_per_call=0)
    cfg = load_stage_config("map", {"providers": ["local"], "pack_size": 10})
    res = run_chain([Item("a", "x")], cfg, {"local": local})
    assert res.resolved == {"a": {"n": 1}}
    assert res.cost_cents == 0
    assert res.metered is False
    assert res.tiers[0].kind == "local"
