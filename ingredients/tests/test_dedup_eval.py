import os

import pytest

from ingredients.dedup.eval_set import run_eval


def test_dedup_eval_passes():
    if not os.environ.get("TEST_DB_URL"):
        pytest.skip("TEST_DB_URL not set")
    report = run_eval()
    assert report.failed == 0, report.failures
