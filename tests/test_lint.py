import dataclasses

from expbuilder.lint import has_errors, lint
from expbuilder.spec import Punishment, Threshold


def codes(spec, level=None):
    return {f.code for f in lint(spec) if level is None or f.level == level}


def test_examples_have_no_errors(example_spec):
    assert not has_errors(lint(example_spec))


def test_social_dilemma_condition(base):
    assert "PG001" in codes(dataclasses.replace(base, mpcr=1.2), "error")
    assert "PG002" in codes(dataclasses.replace(base, mpcr=0.2), "error")
    assert "PG003" in codes(base, "info")


def test_threshold_checks(base):
    s = dataclasses.replace(base, threshold=Threshold(enabled=True, amount=100))
    assert "TH001" in codes(s, "error")
    s = dataclasses.replace(base, threshold=Threshold(enabled=True, amount=15))
    assert "TH002" in codes(s, "warning")


def test_session_and_matching(base):
    assert "SE001" in codes(dataclasses.replace(base, session_size=18), "error")
    assert "SE002" in codes(dataclasses.replace(base, matching="stranger", session_size=8), "warning")
    assert "MA001" in codes(dataclasses.replace(base, matching="stranger"))


def test_punishment_checks(base):
    weak = dataclasses.replace(base, punishment=Punishment(enabled=True, cost_per_point=3, impact_per_point=1))
    assert "PU001" in codes(weak, "warning")
    neg = dataclasses.replace(base, punishment=Punishment(enabled=True, floor_at_zero=False))
    assert "PU004" in codes(neg, "warning")


def test_low_stakes_warning(base):
    from expbuilder.spec import Payment

    s = dataclasses.replace(base, payment=Payment(points_per_currency_unit=100))
    assert "PA001" in codes(s, "warning")
