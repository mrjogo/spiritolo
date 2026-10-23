from ingredients.dedup.eval_set import run_eval


def test_dedup_eval_passes():
    report = run_eval()
    assert report.failed == 0, report.failures
