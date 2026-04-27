"""Tests for CLI helpers shared across pipeline scripts.

confirm_reset() enforces a uniform heuristic for --reset confirmation:
- --yes → always proceed
- TTY stdin → prompt [y/N]
- non-TTY stdin and no --yes → abort (return False) with clear error
"""

import io

from spiritolo_common.cli_common import confirm_reset


def test_confirm_reset_returns_true_when_assume_yes_set():
    err = io.StringIO()
    assert confirm_reset(
        row_count=5000,
        scope_desc="all sites",
        assume_yes=True,
        stdin=io.StringIO("n\n"),  # would say no if prompted — must not prompt
        stdin_is_tty=True,
        err=err,
    ) is True
    assert "5,000" in err.getvalue()
    assert "--yes" in err.getvalue() or "assume_yes" in err.getvalue() or "yes" in err.getvalue().lower()


def test_confirm_reset_prompts_on_tty_and_accepts_y():
    err = io.StringIO()
    assert confirm_reset(
        row_count=100,
        scope_desc="site=imbibe",
        assume_yes=False,
        stdin=io.StringIO("y\n"),
        stdin_is_tty=True,
        err=err,
    ) is True
    assert "site=imbibe" in err.getvalue()
    assert "100" in err.getvalue()


def test_confirm_reset_prompts_on_tty_and_rejects_blank():
    """Default must be No — blank line means 'don't touch my data'."""
    assert confirm_reset(
        row_count=100,
        scope_desc="all sites",
        assume_yes=False,
        stdin=io.StringIO("\n"),
        stdin_is_tty=True,
        err=io.StringIO(),
    ) is False


def test_confirm_reset_prompts_on_tty_and_rejects_n():
    assert confirm_reset(
        row_count=100,
        scope_desc="all sites",
        assume_yes=False,
        stdin=io.StringIO("n\n"),
        stdin_is_tty=True,
        err=io.StringIO(),
    ) is False


def test_confirm_reset_aborts_without_yes_on_non_tty():
    """Piped/redirected stdin with no --yes must refuse rather than read
    an unintended answer from the pipe. Message should tell the user to
    pass --yes."""
    err = io.StringIO()
    assert confirm_reset(
        row_count=500,
        scope_desc="all sites",
        assume_yes=False,
        stdin=io.StringIO(""),
        stdin_is_tty=False,
        err=err,
    ) is False
    assert "--yes" in err.getvalue()


def test_confirm_reset_zero_rows_returns_true_without_prompting():
    """Nothing to reset — there's nothing to confirm."""
    assert confirm_reset(
        row_count=0,
        scope_desc="all sites",
        assume_yes=False,
        stdin=io.StringIO(""),  # empty: would fail a real prompt
        stdin_is_tty=True,
        err=io.StringIO(),
    ) is True
