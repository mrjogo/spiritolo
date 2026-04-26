from ingredients.eval_set import EVAL_CASES, run_eval


def test_eval_cases_exist():
    assert len(EVAL_CASES) >= 20


def test_run_eval_returns_pass_fail_breakdown():
    result = run_eval()
    assert "passed" in result
    assert "failed" in result
    assert "cases" in result
    assert result["passed"] + result["failed"] == len(EVAL_CASES)


def test_all_eval_cases_pass():
    result = run_eval()
    assert result["failed"] == 0, result["cases"]
