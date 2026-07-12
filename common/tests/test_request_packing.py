"""B7 — request packing.

Pins: N items with pack_size=k produce ceil(N/k) provider calls; outputs
re-map to inputs by id (order-independent); a packed call where some items
error parks exactly those and resolves the rest; a re-run re-submits only
the parked ones.

Pure Python — the LLM seam is FakeProvider.
"""
from __future__ import annotations

from common.providers import FakeProvider, Item, load_stage_config, run_chain


def test_packs_n_items_per_call():
    """25 items with pack_size=10 produce 3 fake-provider calls; every output
    re-maps to its own input by id, independent of response order."""
    items = [Item(f"i{n}", f"name{n}") for n in range(25)]
    canned = {f"i{n}": {"idx": n} for n in range(25)}
    fake = FakeProvider(canned_map=canned, cost_per_call=1)
    cfg = load_stage_config("map", {"providers": ["openai"], "pack_size": 10})

    res = run_chain(items, cfg, {"openai": fake})

    assert fake.calls == 3  # ceil(25 / 10)
    # id-keyed re-map: each item carries its own answer despite the fake
    # emitting each chunk's answers in reversed order.
    assert res.resolved == canned
    assert res.parked == []
    assert res.cost_cents == 3  # 3 calls * 1 cent


def test_partial_failure_parks_right_items():
    """A packed call where 2 of 10 items error parks exactly those 2 and
    resolves the other 8; a re-run re-submits only the parked ones."""
    items = [Item(f"i{n}", f"n{n}") for n in range(10)]
    canned = {f"i{n}": {"idx": n} for n in range(10)}
    bad = {"i3", "i7"}

    fake = FakeProvider(canned_map=canned, cost_per_call=1, raises_for=bad)
    cfg = load_stage_config("map", {"providers": ["openai"], "pack_size": 10})
    res = run_chain(items, cfg, {"openai": fake})

    assert fake.calls == 1  # single packed call over all 10
    assert set(res.resolved) == set(canned) - bad  # 8 resolved
    assert set(res.parked) == bad  # exactly the 2 that errored
    for n in range(10):
        if f"i{n}" not in bad:
            assert res.resolved[f"i{n}"] == {"idx": n}

    # Re-run re-submits ONLY the parked items (now healthy).
    parked_items = [it for it in items if it.id in res.parked]
    fake2 = FakeProvider(canned_map=canned, cost_per_call=1)  # no forced failures
    res2 = run_chain(parked_items, cfg, {"openai": fake2})

    assert fake2.calls == 1
    assert set(res2.resolved) == bad  # only the 2 re-submitted, now resolved
    assert res2.parked == []
