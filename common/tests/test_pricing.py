from datetime import datetime, time, timezone
from unittest.mock import MagicMock

import pytest

from common.providers import cost, pricing
from common.providers.pricing import ModelPrice, RateWindow

# A Wednesday.
NOON = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def test_haiku_5_5_item_estimate_is_hand_computed():
    # 1200 in * $0.10 + 200 out * $0.50 per MTok = $0.00022 = 0.022 cents.
    assert pricing.estimate_item_cents("anthropic", "claude-haiku-5-5", 1) == pytest.approx(0.022)
    assert pricing.estimate_item_cents("anthropic", "claude-haiku-5-5", 1000) == pytest.approx(22.0)


def test_claude_alias_and_default_model():
    assert pricing.estimate_item_cents("claude", None, 10) == pytest.approx(
        pricing.estimate_item_cents("anthropic", "claude-haiku-5-5", 10)
    )


def test_long_prompt_bills_at_long_context_rate():
    short = pricing.estimate_call_cents("anthropic", "claude-haiku-5-5", 100_000, 0)
    long_ = pricing.estimate_call_cents("anthropic", "claude-haiku-5-5", 100_001, 0)
    assert short == pytest.approx(100_000 * 0.10 / 1e4)
    assert long_ == pytest.approx(100_001 * 0.50 / 1e4)


@pytest.mark.parametrize("pid", ["ollama", "local", None, "nonesuch"])
def test_local_and_unknown_providers_are_free(pid):
    assert pricing.estimate_item_cents(pid, "qwen3:14b", 1000) == 0
    assert not pricing.is_metered(pid)


def test_unlisted_hosted_model_is_priced_at_the_providers_dearest():
    # Never 0: an unknown id must not switch the cost cap off.
    assert pricing.is_metered("anthropic", "claude-unknown")
    assert pricing.price_for("anthropic", "claude-unknown") == pricing.MODEL_PRICES[
        ("anthropic", "claude-haiku-4-5")
    ]


def test_run_estimate_rounds_a_metered_run_up_not_to_zero():
    assert pricing.estimate_run_cents("anthropic", "claude-haiku-5-5", 10) == 1
    assert pricing.estimate_run_cents("anthropic", "claude-haiku-5-5", 0) == 0
    assert pricing.estimate_run_cents("ollama", "qwen3:14b", 10_000) == 0


PEAK = RateWindow(
    "peak", frozenset({0, 1, 2, 3, 4}), time(1), time(4), input_per_mtok=0.30, output_per_mtok=1.20
)
NIGHT = RateWindow(  # wraps midnight; starts Fridays only
    "night", frozenset({4}), time(22), time(2), input_per_mtok=0.05, output_per_mtok=0.10
)
PRICE = ModelPrice(0.15, 0.60, "test", "test", windows=(PEAK, NIGHT))


def test_rate_window_picks_rate_by_utc_time_of_week():
    wed = lambda h, m=0: datetime(2026, 10, 21, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert PRICE.rates(0, wed(0, 59)) == (0.15, 0.60)
    assert PRICE.rates(0, wed(1)) == (0.30, 1.20)
    assert PRICE.rates(0, wed(3, 59)) == (0.30, 1.20)
    assert PRICE.rates(0, wed(4)) == (0.15, 0.60)  # end is exclusive
    sat = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
    assert PRICE.rates(0, sat) == (0.15, 0.60)  # peak is weekdays only


def test_rate_window_wrapping_midnight():
    fri_late = datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc)
    sat_early = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
    sat_late = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    assert PRICE.window_at(fri_late) is NIGHT
    assert PRICE.window_at(sat_early) is NIGHT
    assert PRICE.window_at(sat_late) is None


def test_rate_window_reads_aware_times_in_utc():
    from datetime import timedelta
    tz = timezone(timedelta(hours=8))
    # 09:30 at UTC+8 on Wednesday = 01:30 UTC Wednesday -> peak.
    assert PRICE.window_at(datetime(2026, 10, 21, 9, 30, tzinfo=tz)) is PEAK


def test_estimates_use_the_window_in_force(monkeypatch):
    monkeypatch.setitem(pricing.MODEL_PRICES, ("deepseek", "ds-test"), PRICE)
    off = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    peak = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
    assert pricing.estimate_call_cents("deepseek", "ds-test", 1_000_000, 0, at=off) == pytest.approx(15)
    assert pricing.estimate_call_cents("deepseek", "ds-test", 1_000_000, 0, at=peak) == pytest.approx(30)


def test_call_cost_scales_with_pack_items_and_reads_model_id():
    provider = MagicMock(spec=["model_id"], model_id="claude-haiku-5-5")
    assert cost.call_cost_cents("anthropic", provider, items=1, now=NOON) == pytest.approx(0.022)
    assert cost.call_cost_cents("anthropic", provider, items=4, now=NOON) == pytest.approx(0.088)
    # No item count: a full default pack.
    assert cost.call_cost_cents("anthropic", provider, now=NOON) == pytest.approx(
        0.022 * pricing.DEFAULT_PACK_ITEMS
    )
    assert cost.is_metered(cost.call_cost_cents("anthropic", provider, items=1))


def test_call_cost_self_report_wins_and_local_is_free():
    assert cost.call_cost_cents("anthropic", MagicMock(cost_per_call=7), items=3) == 7
    assert cost.call_cost_cents("ollama", MagicMock(spec=["model_id"], model_id="qwen3:14b")) == 0
    assert not cost.is_metered(0)


def test_tiers_are_in_picker_order_with_defaults():
    tiers = pricing.llm_tiers()
    assert [t.provider for t in tiers] == ["local", "deepseek", "openai", "anthropic"]
    assert tiers[0].model == "qwen3.5-9b" and not tiers[0].metered
    assert tiers[-1].model == "claude-haiku-5-5" and tiers[-1].metered
    assert tiers[-1].label == "Claude · claude-haiku-5-5 — metered"
    assert tiers[0].label == "Local · qwen3.5-9b — free (local)"
    assert pricing.llm_tiers(local_model="qwen/qwen3-14b")[0].model == "qwen/qwen3-14b"


def test_every_default_hosted_model_has_a_price():
    for pid, model in pricing.DEFAULT_MODEL.items():
        if not pricing.is_local(pid):
            assert (pid, model) in pricing.MODEL_PRICES


def test_tier_payload_carries_the_price_in_force(monkeypatch):
    monkeypatch.setitem(pricing.MODEL_PRICES, ("deepseek", "ds-test"), PRICE)
    tier = pricing.tier_for("deepseek", "ds-test")
    peak = pricing.tier_payload(tier, True, at=datetime(2026, 10, 21, 2, tzinfo=timezone.utc))
    assert peak["available"] is True and peak["metered"] is True
    assert peak["price"]["input_per_mtok"] == 0.30
    assert peak["price"]["current_window"] == "peak"
    assert peak["price"]["windows"][0] == {
        "label": "peak", "weekdays": [0, 1, 2, 3, 4], "start_utc": "01:00", "end_utc": "04:00",
        "input_per_mtok": 0.30, "output_per_mtok": 1.20,
    }
    local = pricing.tier_payload(pricing.tier_for("ollama", "qwen3:14b"), True)
    assert local["provider"] == "local"  # old id normalized
    assert local["price"] is None and local["metered"] is False


def test_gpt6_luna_is_the_openai_default_at_its_listed_price():
    assert pricing.DEFAULT_MODEL["openai"] == "gpt-6-luna"
    # Same list price as Haiku 5.5: 1200 * 0.10 + 200 * 0.50 per MTok.
    assert pricing.estimate_item_cents("openai", None, 1) == pytest.approx(0.022)


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-flash", None])
def test_deepseek_flash_doubles_in_weekday_peak_hours(model):
    utc = lambda d, h: datetime(2026, 10, d, h, 30, tzinfo=timezone.utc)  # noqa: E731
    per_mtok_in = lambda at: pricing.estimate_call_cents("deepseek", model, 1_000_000, 0, at=at)  # noqa: E731
    assert per_mtok_in(utc(21, 0)) == pytest.approx(15)   # Wed 00:30 off-peak
    assert per_mtok_in(utc(21, 2)) == pytest.approx(30)   # Wed 02:30 peak
    assert per_mtok_in(utc(21, 5)) == pytest.approx(15)   # Wed 05:30 between windows
    assert per_mtok_in(utc(21, 9)) == pytest.approx(30)   # Wed 09:30 peak
    assert per_mtok_in(utc(21, 10)) == pytest.approx(15)  # Wed 10:30 off-peak
    assert per_mtok_in(utc(24, 2)) == pytest.approx(15)   # Sat 02:30 off-peak
    out = pricing.estimate_call_cents("deepseek", model, 0, 1_000_000, at=utc(21, 2))
    assert out == pytest.approx(120)


def test_local_default_mirrors_the_worker_default():
    import importlib.util
    if importlib.util.find_spec("ingredients") is None:
        pytest.skip("ingredients not installed")
    from ingredients.worker.providers_local import DEFAULT_LOCAL_MODEL
    assert pricing.LOCAL_DEFAULT_MODEL == DEFAULT_LOCAL_MODEL


def test_call_cost_uses_the_measured_prompt_size():
    provider = MagicMock(spec=["model_id"], model_id="claude-haiku-5-5")
    # One extract-sized call: ~5000 input tokens, not the 1200 per-item default.
    big = cost.call_cost_cents("anthropic", provider, items=1, input_tokens=5000, now=NOON)
    assert big == pytest.approx((5000 * 0.10 + 200 * 0.50) / 1e4)
    # A prompt past 100K tokens bills at the long-context rate.
    huge = cost.call_cost_cents("anthropic", provider, items=1, input_tokens=200_000, now=NOON)
    assert huge == pytest.approx((200_000 * 0.50 + 200 * 2.50) / 1e4)


def test_extract_estimates_with_page_sized_items():
    per_default = pricing.estimate_item_cents("anthropic", "claude-haiku-5-5", 1)
    per_extract = pricing.estimate_item_cents("anthropic", "claude-haiku-5-5", 1, stage="extract-recipe")
    assert per_extract == pytest.approx((5000 * 0.10 + 600 * 0.50) / 1e4)
    assert per_extract > per_default
    assert pricing.estimate_tokens("x" * 300) == 101
