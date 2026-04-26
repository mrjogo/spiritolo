import io
import sys

from ingredients.cli import run_review


def test_run_review_prints_summary_and_returns_zero_on_pass(capsys):
    rc = run_review()
    captured = capsys.readouterr()
    assert "passed" in captured.out.lower()
    assert rc == 0
