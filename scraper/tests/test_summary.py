"""Tests for the shared per-site/per-category summary printer."""

import io
from collections import Counter

from scraper.src.summary import print_summary


def test_print_summary_empty():
    buf = io.StringIO()
    print_summary("Validate", {}, out=buf)
    out = buf.getvalue()
    assert "--- Validate ---" in out
    assert "No changes" in out


def test_print_summary_per_site_per_category():
    buf = io.StringIO()
    changes = {
        "imbibe": Counter({"confirmed_food -> confirmed_drink": 1666}),
        "punch": Counter({"confirmed_food -> confirmed_drink": 542}),
    }
    print_summary("Validate", changes, out=buf)
    out = buf.getvalue()
    assert "--- Validate ---" in out
    assert "imbibe:" in out
    assert "punch:" in out
    assert "1666" in out
    assert "542" in out
    assert "confirmed_food -> confirmed_drink" in out
    assert "Total: 2208" in out


def test_print_summary_mode_is_labeled():
    buf = io.StringIO()
    changes = {"imbibe": Counter({"x -> y": 3})}
    print_summary("Validate", changes, mode="dry-run", out=buf)
    assert "(dry-run)" in buf.getvalue()


def test_print_summary_default_mode_is_applied():
    buf = io.StringIO()
    print_summary("Validate", {"site": Counter({"a -> b": 1})}, out=buf)
    assert "(applied)" in buf.getvalue()


def test_print_summary_sites_sorted_alphabetically():
    buf = io.StringIO()
    changes = {
        "zeta": Counter({"a -> b": 1}),
        "alpha": Counter({"a -> b": 1}),
        "mike": Counter({"a -> b": 1}),
    }
    print_summary("X", changes, out=buf)
    out = buf.getvalue()
    assert out.index("alpha:") < out.index("mike:") < out.index("zeta:")


def test_print_summary_categories_sorted_by_descending_count():
    """Within a site, the biggest category should appear first — this is how
    revalidate already presents it and it matches how people read results."""
    buf = io.StringIO()
    changes = {
        "imbibe": Counter({
            "small": 1,
            "huge": 999,
            "medium": 50,
        }),
    }
    print_summary("X", changes, out=buf)
    out = buf.getvalue()
    assert out.index("huge") < out.index("medium") < out.index("small")
