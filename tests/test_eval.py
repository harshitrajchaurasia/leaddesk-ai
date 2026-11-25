from evals.run_eval import score


def test_score_empty_is_zero():
    assert score([]) == 0.0


def test_score_half():
    assert score([("a", "a"), ("a", "b")]) == 0.5
