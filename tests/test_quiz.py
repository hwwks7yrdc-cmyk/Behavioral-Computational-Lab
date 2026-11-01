from expbuilder.games import public_goods as pg


def test_quiz_answers_match_payoff_model(example_spec):
    qs = pg.quiz(example_spec)
    assert len(qs) == example_spec.comprehension.num_questions
    assert [q.key for q in qs] == [f"q{i}" for i in range(1, len(qs) + 1)]
    e, n = example_spec.endowment, example_spec.players_per_group
    assert qs[0].answer == pg.stage1_payoffs(example_spec, [0] + [e] * (n - 1))[0]
    assert qs[1].answer == pg.stage1_payoffs(example_spec, [e] * n)[0]
    for q in qs:
        assert q.text.endswith("?")
        assert str(int(q.answer)) in q.explanation or f"{q.answer:g}" in q.explanation


def test_quiz_is_deterministic(example_spec):
    assert pg.quiz(example_spec) == pg.quiz(example_spec)


def test_punishment_quiz_covers_cost_and_impact(example_spec):
    if not example_spec.punishment.enabled:
        return
    texts = " ".join(q.text for q in pg.quiz(example_spec))
    assert "your own earnings reduced" in texts and "Member 2's earnings reduced" in texts
