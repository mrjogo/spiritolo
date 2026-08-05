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


@dataclass
class _TokenProvider:
    """An LLM tier that answers every packed item and reports fixed token usage
    per call — lets a test pin the per-item usage attribution."""

    prompt_tokens: int | None
    completion_tokens: int | None
    calls: int = 0

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.calls += 1
        ids = packing.decode_request(user_prompt)
        rows = [{"id": i, "answer": f"a:{i}"} for i in ids]
        return ProviderResult(
            raw_text=packing.encode_response(rows),
            model_id="x",
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


def test_pack_token_usage_split_evenly_across_items():
    # One packed call reporting 100 prompt / 40 completion tokens over 4 items
    # attributes 25 / 10 to each item, and the per-item totals sum back to the
    # exact call usage.
    prov = _TokenProvider(prompt_tokens=100, completion_tokens=40)
    chain = ProviderChain(tiers=[("openai", prov)], pack_size=4)

    res = chain.resolve([Item(str(i)) for i in range(4)])

    assert prov.calls == 1
    tokens = res.per_item_tokens
    assert set(tokens) == {"0", "1", "2", "3"}
    assert all(tokens[i] == (25, 10) for i in tokens)
    assert sum(p for p, _ in tokens.values()) == 100
    assert sum(c for _, c in tokens.values()) == 40


def test_pack_token_usage_remainder_goes_to_first_item():
    # An indivisible total (101 / 41 over 4 items) puts the whole remainder on
    # the first item; the split still sums to exactly the call usage.
    prov = _TokenProvider(prompt_tokens=101, completion_tokens=41)
    chain = ProviderChain(tiers=[("openai", prov)], pack_size=4)

    res = chain.resolve([Item(str(i)) for i in range(4)])

    tokens = res.per_item_tokens
    assert tokens["0"] == (26, 11)  # per=25/10 + remainder 1/1 on the first
    assert tokens["1"] == tokens["2"] == tokens["3"] == (25, 10)
    assert sum(p for p, _ in tokens.values()) == 101
    assert sum(c for _, c in tokens.values()) == 41


def test_pack_token_usage_none_when_provider_reports_no_usage():
    # A provider that reports no usage yields (None, None) per item — nothing to
    # roll up (mirrors ProviderResult's default token fields).
    prov = _TokenProvider(prompt_tokens=None, completion_tokens=None)
    chain = ProviderChain(tiers=[("ollama", prov)], pack_size=2)

    res = chain.resolve([Item("1"), Item("2")])

    assert res.per_item_tokens == {"1": (None, None), "2": (None, None)}


def test_per_item_cost_splits_tier_cost_across_resolved_ids():
    # A hosted tier that resolves 4 items in one 7-cent call splits the cost
    # evenly across those ids, whole remainder on the first, summing to 7.
    hosted = FakeProvider(
        canned_map={str(i): {"n": i} for i in range(4)}, cost_per_call=7
    )
    chain = ProviderChain(tiers=[("openai", hosted)], pack_size=4)

    res = chain.resolve([Item(str(i)) for i in range(4)])

    cost = res.per_item_cost
    assert set(cost) == {"0", "1", "2", "3"}
    assert sum(cost.values()) == 7
    assert cost["0"] == 4 and cost["1"] == cost["2"] == cost["3"] == 1


def test_per_item_model_records_resolving_model():
    # Each resolved id carries the model that answered it; the ChainResult's
    # per_item_model maps id -> model_id.
    hosted = FakeProvider(
        canned_map={"a": {"n": 1}, "b": {"n": 2}}, model_id="gpt-5-mini"
    )
    chain = ProviderChain(tiers=[("openai", hosted)], pack_size=10)

    res = chain.resolve([Item("a"), Item("b")])

    assert res.per_item_model == {"a": "gpt-5-mini", "b": "gpt-5-mini"}


def test_deterministic_tier_contributes_zero_cost_and_no_model():
    # A deterministic tier resolves for free: its ids get 0 cost and no model.
    det = _Deterministic(resolve_fn=_resolve_all(lambda it: f"det:{it.id}"))
    chain = ProviderChain(tiers=[("det", det)], pack_size=2)

    res = chain.resolve([Item("1"), Item("2")])

    assert res.per_item_cost == {"1": 0, "2": 0}
    assert res.per_item_model == {}


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
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-5",
        "max_cost_cents": 500,
    }
    chain = _build_providers(job, env={"ANTHROPIC_API_KEY": "sk-a"})

    assert isinstance(chain, ProviderChain)
    assert chain.pack_size == DEFAULT_PACK_SIZE
    assert chain.meter.cap_cents == 500
    [(provider_id, impl)] = chain.tiers
    assert provider_id == "anthropic"
    assert impl.model_id == "claude-sonnet-4-5"


def test_available_providers_reflects_present_keys():
    from ingredients.worker.providers_local import available_providers

    # ollama (local) is always available; hosted providers only with their key.
    assert available_providers({}) == ["ollama"]
    got = available_providers({"DEEPSEEK_API_KEY": "x", "OPENAI_API_KEY": "y"})
    assert got[0] == "ollama"
    assert "deepseek" in got and "openai" in got and "anthropic" not in got


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


@dataclass
class _CountingProvider:
    cost_per_call: int = 0
    calls: int = 0

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.calls += 1
        ids = packing.decode_request(user_prompt)
        rows = [{"id": i, "answer": f"a:{i}"} for i in ids]
        return ProviderResult(raw_text=packing.encode_response(rows), model_id="x")


def test_chain_stops_between_packs_on_should_stop():
    # should_stop trips after the first pack -> the remaining packs are never
    # called and their items are parked (cooperative cancel granularity).
    prov = _CountingProvider()
    chain = ProviderChain(
        tiers=[("ollama", prov)],
        pack_size=1,
        should_stop=lambda: prov.calls >= 1,  # stop once the first pack ran
    )

    res = chain.resolve([Item("1"), Item("2"), Item("3")])

    assert res.resolved == {"1": "a:1"}
    assert set(res.parked) == {"2", "3"}
    assert prov.calls == 1


def test_llm_circuit_breaker_aborts_after_consecutive_pack_failures(_no_backoff):
    # Persistent transient errors: each pack retries then parks; after
    # _CONSECUTIVE_FAIL_ABORT parked packs the breaker fails the run fast
    # instead of grinding every remaining pack into the same wall.
    prov = _RaisingProvider(exc=_TransientStatusError(), fail_calls=999)
    chain = ProviderChain(tiers=[("ollama", prov)], pack_size=1)

    with pytest.raises(ProviderUnavailable):
        chain.resolve([Item(str(i)) for i in range(10)])

    assert prov.calls == _CONSECUTIVE_FAIL_ABORT * _MAX_LLM_ATTEMPTS
