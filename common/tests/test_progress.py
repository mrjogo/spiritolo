"""Tests for the shared progress helper (rate + ETA display across CLIs)."""

import io

from spiritolo_common.progress import PROGRESS_EVERY, format_eta, make_progress


def test_format_eta_seconds():
    assert format_eta(0) == "0s"
    assert format_eta(1) == "1s"
    assert format_eta(59.4) == "59s"


def test_format_eta_minutes_seconds():
    assert format_eta(60) == "1m0s"
    assert format_eta(65) == "1m5s"
    assert format_eta(3599) == "59m59s"


def test_format_eta_hours_minutes_seconds():
    assert format_eta(3600) == "1h0m0s"
    assert format_eta(3600 + 3 * 60 + 34) == "1h3m34s"
    assert format_eta(10 * 3600) == "10h0m0s"


def test_format_eta_negative_is_zero():
    """Rate-based ETA can go briefly negative at the end of a run — clamp."""
    assert format_eta(-5) == "0s"


def test_make_progress_emits_on_cadence_only():
    buf = io.StringIO()
    progress = make_progress(total=100, out=buf, now=iter([0.0, 1.0, 2.0]).__next__)
    progress(5)
    assert buf.getvalue() == ""  # 5 is not a cadence step, not final
    progress(25)
    assert "25/100" in buf.getvalue()


def test_make_progress_emits_on_final_even_off_cadence():
    buf = io.StringIO()
    progress = make_progress(total=13, out=buf, now=iter([0.0, 1.3]).__next__)
    progress(13)
    out = buf.getvalue()
    assert "13/13" in out
    assert out.endswith("\n"), "final emit must end the line so later stdout isn't stuck mid-update"


def test_make_progress_format_is_classify_style():
    """Format: '\\r  N/M (X.X%)  Y.Y/s  ETA ...    '. The padding trailing
    spaces keep us clean when the next emit is shorter."""
    buf = io.StringIO()
    ticks = iter([0.0, 2.0])
    progress = make_progress(total=100, out=buf, now=ticks.__next__)
    progress(PROGRESS_EVERY)
    out = buf.getvalue()
    assert out.startswith("\r")
    assert "25/100" in out or f"{PROGRESS_EVERY}/100" in out
    assert "(25.0%)" in out or f"({PROGRESS_EVERY}.0%)" in out
    assert "/s" in out
    assert "ETA" in out


def test_make_progress_rate_and_eta_use_elapsed_time():
    buf = io.StringIO()
    ticks = iter([0.0, 10.0])  # start=0, elapsed at emit=10s
    progress = make_progress(total=100, out=buf, now=ticks.__next__)
    progress(25)  # 25 rows in 10s -> 2.5/s -> 75 remaining -> 30s ETA
    out = buf.getvalue()
    assert "2.5/s" in out
    assert "ETA 30s" in out


def test_make_progress_accepts_zero_total_without_dividing_by_zero():
    buf = io.StringIO()
    progress = make_progress(total=0, out=buf, now=iter([0.0, 1.0]).__next__)
    progress(0)  # should not raise
