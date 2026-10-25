"""The one LLM price table: model prices, default models, and the tier list.

Everything that turns tokens into cents reads this module — the executor's
per-call cost cap (``common.providers.cost.call_cost_cents``), the Start-confirm
estimate (``ingredients.runs.estimate_cents``) and the ``/ops`` tier picker
(``GET /api/ops/llm-tiers``). Prices are list USD per million tokens.

A price may vary by time of week (DeepSeek bills peak and off-peak hours
differently): a ``ModelPrice`` carries ``RateWindow``s in UTC, and the rate
applied to a call is the one in force when the call is made. Long prompts may
bill at a higher rate (Claude Haiku 5.5 above 100K input tokens):
``long_context`` carries that tier.

Every entry names its source and as-of date. Do not add a price you have not
seen on the vendor's pricing page (or been given by Ruddick from it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

# Provider ids. ``claude`` is the old spelling of ``anthropic`` and ``ollama`` the
# old id of ``local`` (the free OpenAI-compatible local runtime); old job rows
# still carry both.
PROVIDER_ALIASES: dict[str, str] = {"claude": "anthropic", "ollama": "local"}
LOCAL_PROVIDERS: frozenset[str] = frozenset({"local", "ollama"})
LOCAL_PROVIDER = "local"
# What the local tier offers when LOCAL_LLM_MODEL is unset (mirrors
# ingredients.worker.providers_local.DEFAULT_LOCAL_MODEL).
LOCAL_DEFAULT_MODEL = "qwen3:14b"

# The per-item token assumption behind every estimate: a packed LLM call costs
# roughly this much per item (stage prompt amortized across the pack).
ITEM_INPUT_TOKENS = 1200
ITEM_OUTPUT_TOKENS = 200
# Items per call when the caller doesn't say (mirrors the worker's
# DEFAULT_PACK_SIZE, which lives in ingredients and can't be imported here).
DEFAULT_PACK_ITEMS = 10


@dataclass(frozen=True)
class RateWindow:
    """A weekly UTC window billed at its own rates.

    ``weekdays`` are the days the window *starts* on (0 = Monday). ``end`` is
    exclusive; an ``end`` at or before ``start`` runs past midnight into the
    next day.
    """

    label: str
    weekdays: frozenset[int]
    start: time
    end: time
    input_per_mtok: float
    output_per_mtok: float

    def contains(self, at: datetime) -> bool:
        at = at.astimezone(timezone.utc)
        t = at.time()
        if self.start < self.end:
            return at.weekday() in self.weekdays and self.start <= t < self.end
        # Wraps midnight: the tail after start on a listed day, or the head
        # before end on the day after one.
        if at.weekday() in self.weekdays and t >= self.start:
            return True
        return (at - timedelta(days=1)).weekday() in self.weekdays and t < self.end


@dataclass(frozen=True)
class LongContextRate:
    """Rates for a call whose input exceeds ``threshold_tokens``."""

    threshold_tokens: int
    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    as_of: str | None
    source: str
    long_context: LongContextRate | None = None
    windows: tuple[RateWindow, ...] = field(default_factory=tuple)

    def window_at(self, at: datetime) -> RateWindow | None:
        return next((w for w in self.windows if w.contains(at)), None)

    def rates(self, input_tokens: int, at: datetime) -> tuple[float, float]:
        """(input, output) $/MTok for a call of ``input_tokens`` made at ``at``."""
        w = self.window_at(at)
        if w is not None:
            return w.input_per_mtok, w.output_per_mtok
        lc = self.long_context
        if lc is not None and input_tokens > lc.threshold_tokens:
            return lc.input_per_mtok, lc.output_per_mtok
        return self.input_per_mtok, self.output_per_mtok


_ANTHROPIC_TABLE = "Anthropic model table"
_OPENAI_PAGE = "OpenAI pricing page (Standard), supplied by Ruddick"
_CARRIED = "carried over from the pre-2026-10 inline estimate; not re-verified"

MODEL_PRICES: dict[tuple[str, str], ModelPrice] = {
    ("anthropic", "claude-haiku-5-5"): ModelPrice(
        0.10, 0.50, "2026-10-06", _ANTHROPIC_TABLE,
        long_context=LongContextRate(100_000, 0.50, 2.50),
    ),
    # Old runs still name these; keep them priced so a retry is capped right.
    ("anthropic", "claude-haiku-4-5"): ModelPrice(1.00, 5.00, "2026-10-06", _ANTHROPIC_TABLE),
    # Standard tier, short context. Long-context rates not yet supplied.
    ("openai", "gpt-6-luna"): ModelPrice(0.10, 0.50, "2026-10-25", _OPENAI_PAGE),
    ("openai", "gpt-5.4-mini"): ModelPrice(0.75, 4.50, "2026-10-25", _OPENAI_PAGE),
    ("deepseek", "deepseek-v4-flash"): ModelPrice(0.14, 0.28, None, _CARRIED),
}

# The model a provider runs when a run names none.
DEFAULT_MODEL: dict[str, str] = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-6-luna",
    "deepseek": "deepseek-v4-flash",
    LOCAL_PROVIDER: LOCAL_DEFAULT_MODEL,
}

DISPLAY_NAME: dict[str, str] = {
    "local": "Local",
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "anthropic": "Claude",
}

# Picker order: free first, then the hosted tiers cheapest-first.
TIER_ORDER: tuple[str, ...] = (LOCAL_PROVIDER, "deepseek", "openai", "anthropic")


def canonical_provider(provider_id: str | None) -> str | None:
    if provider_id is None:
        return None
    return PROVIDER_ALIASES.get(provider_id, provider_id)


def is_local(provider_id: str | None) -> bool:
    return canonical_provider(provider_id) in LOCAL_PROVIDERS


def price_for(provider_id: str | None, model_id: str | None) -> ModelPrice | None:
    """The price of ``model_id`` on ``provider_id``, or ``None`` when free.

    Local providers and unknown providers are free (an unknown provider can't be
    built, so nothing is spent). A hosted provider's unlisted model is priced at
    that provider's most expensive listed model, so a typo or a new id can only
    over-count against the cost cap, never switch it off.
    """
    pid = canonical_provider(provider_id)
    if pid is None or is_local(pid):
        return None
    model = model_id or DEFAULT_MODEL.get(pid)
    hit = MODEL_PRICES.get((pid, model or ""))
    if hit is not None:
        return hit
    same = [p for (p_id, _), p in MODEL_PRICES.items() if p_id == pid]
    if not same:
        return None
    return max(same, key=lambda p: p.input_per_mtok + p.output_per_mtok)


def is_metered(provider_id: str | None, model_id: str | None = None) -> bool:
    return price_for(provider_id, model_id) is not None


def _now(at: datetime | None) -> datetime:
    return datetime.now(timezone.utc) if at is None else at


def estimate_call_cents(
    provider_id: str | None,
    model_id: str | None,
    input_tokens: int,
    output_tokens: int,
    *,
    at: datetime | None = None,
) -> float:
    """Cents for one call of the given size, at the rate in force at ``at``."""
    price = price_for(provider_id, model_id)
    if price is None:
        return 0.0
    rin, rout = price.rates(input_tokens, _now(at))
    return (input_tokens * rin + output_tokens * rout) / 1_000_000 * 100


def estimate_item_cents(
    provider_id: str | None,
    model_id: str | None,
    items: int = 1,
    *,
    at: datetime | None = None,
) -> float:
    """Cents for ``items`` items at the per-item token assumption."""
    per_item = estimate_call_cents(
        provider_id, model_id, ITEM_INPUT_TOKENS, ITEM_OUTPUT_TOKENS, at=at
    )
    return per_item * max(items, 0)


def estimate_run_cents(
    provider_id: str | None, model_id: str | None, items: int | None, *, at: datetime | None = None
) -> int:
    """Whole cents for a run of ``items`` items; a metered run never rounds to 0."""
    cents = estimate_item_cents(provider_id, model_id, items or 0, at=at)
    return math.ceil(cents) if cents > 0 else 0


@dataclass(frozen=True)
class LlmTier:
    provider: str
    model: str
    label: str
    short_label: str
    metered: bool


def tier_for(provider_id: str, model_id: str) -> LlmTier:
    pid = canonical_provider(provider_id) or provider_id
    short = f"{DISPLAY_NAME.get(pid, pid)} · {model_id}"
    metered = is_metered(pid, model_id)
    suffix = "metered" if metered else "free (local)"
    return LlmTier(pid, model_id, f"{short} — {suffix}", short, metered)


def llm_tiers(local_model: str | None = None) -> list[LlmTier]:
    """The tiers a run may be pointed at, in picker order. ``local_model`` is the
    model the local runtime serves (``LOCAL_LLM_MODEL``), else the default."""
    out = []
    for pid in TIER_ORDER:
        model = (local_model or LOCAL_DEFAULT_MODEL) if is_local(pid) else DEFAULT_MODEL[pid]
        out.append(tier_for(pid, model))
    return out


def _window_dict(w: RateWindow) -> dict[str, object]:
    return {
        "label": w.label,
        "weekdays": sorted(w.weekdays),
        "start_utc": w.start.strftime("%H:%M"),
        "end_utc": w.end.strftime("%H:%M"),
        "input_per_mtok": w.input_per_mtok,
        "output_per_mtok": w.output_per_mtok,
    }


def tier_payload(
    tier: LlmTier, available: bool, *, at: datetime | None = None
) -> dict[str, object]:
    """One tier as the API serves it, with the price in force now."""
    price = price_for(tier.provider, tier.model)
    out: dict[str, object] = {
        "provider": tier.provider,
        "model": tier.model,
        "label": tier.label,
        "short_label": tier.short_label,
        "metered": tier.metered,
        "available": available,
        "price": None,
    }
    if price is not None:
        now = _now(at)
        rin, rout = price.rates(ITEM_INPUT_TOKENS, now)
        current = price.window_at(now)
        out["price"] = {
            "input_per_mtok": rin,
            "output_per_mtok": rout,
            "as_of": price.as_of,
            "source": price.source,
            "current_window": current.label if current else None,
            "windows": [_window_dict(w) for w in price.windows],
        }
    return out
