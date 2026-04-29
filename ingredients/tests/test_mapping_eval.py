from ingredients.mapping.eval_set import run_eval


def test_all_eval_cases_pass_against_fixture(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    out = run_eval(conn)
    assert out["failed"] == 0, [c for c in out["cases"] if not c["ok"]]
    assert out["passed"] == len(out["cases"])
