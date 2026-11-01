import dataclasses

import pytest

from expbuilder.games import public_goods as pg
from expbuilder.spec import Punishment, Threshold


def test_linear_vcm(base):
    # E = 20, MPCR = 0.4, N = 4
    assert pg.stage1_payoffs(base, [0, 20, 20, 20]) == [44.0, 24.0, 24.0, 24.0]
    assert pg.stage1_payoffs(base, [20, 20, 20, 20]) == [32.0] * 4
    assert pg.stage1_payoffs(base, [0, 0, 0, 0]) == [20.0] * 4
    assert pg.stage1_payoffs(base, [10, 5, 3, 1]) == [17.6, 22.6, 24.6, 26.6]


def test_free_riding_is_dominant(base):
    for others in ([0, 0, 0], [5, 10, 20], [20, 20, 20]):
        pays = [pg.stage1_payoffs(base, [c] + others)[0] for c in range(base.endowment + 1)]
        assert pays == sorted(pays, reverse=True)


def test_threshold_refund_and_bonus(base):
    s = dataclasses.replace(base, threshold=Threshold(enabled=True, amount=48, refund=True, bonus=5))
    assert pg.stage1_payoffs(s, [20, 20, 7, 0]) == [20.0] * 4            # 47 < 48: refund, nothing provided
    assert pg.stage1_payoffs(s, [20, 20, 8, 0]) == [24.2, 24.2, 36.2, 44.2]  # 48: 0.4 * 48 = 19.2, + bonus 5
    no_refund = dataclasses.replace(s, threshold=Threshold(enabled=True, amount=48, refund=False))
    assert pg.stage1_payoffs(no_refund, [20, 20, 7, 0]) == [0.0, 0.0, 13.0, 20.0]


def test_punishment_fehr_gaechter(base):
    s = dataclasses.replace(base, punishment=Punishment(enabled=True, max_points=10, cost_per_point=1, impact_per_point=3))
    contrib = [0, 20, 20, 20]                  # stage 1: [44, 24, 24, 24]
    m = [[0, 0, 0, 0], [2, 0, 0, 0], [3, 0, 0, 0], [1, 0, 0, 0]]
    assert pg.final_payoffs(s, contrib, m) == [44 - 3 * 6, 24 - 2, 24 - 3, 24 - 1]


def test_punishment_floor_and_budget(base):
    s = dataclasses.replace(base, punishment=Punishment(enabled=True, max_points=10))
    m = [[0, 0, 0, 0], [10, 0, 0, 0], [10, 0, 0, 0], [10, 0, 0, 0]]
    assert pg.final_payoffs(s, [20, 20, 20, 20], m)[0] == 0.0          # 32 - 90 floored at zero
    neg = dataclasses.replace(s, punishment=Punishment(enabled=True, max_points=10, floor_at_zero=False))
    assert pg.final_payoffs(neg, [20, 20, 20, 20], m)[0] == -58.0
    with pytest.raises(ValueError, match="more on punishment"):
        pg.final_payoffs(s, [20, 0, 0, 0], [[0, 10, 10, 10], [0] * 4, [0] * 4, [0] * 4])  # stage 1 = 8 < 30


def test_invalid_inputs(base):
    with pytest.raises(ValueError):
        pg.stage1_payoffs(base, [0, 0, 0])
    with pytest.raises(ValueError):
        pg.stage1_payoffs(base, [21, 0, 0, 0])


def test_bounds_and_budget(base):
    b = pg.round_bounds(base)
    assert (b.min_round, b.max_round, b.social_optimum_round, b.nash_round) == (8.0, 44.0, 32.0, 20.0)
    budget = pg.session_budget(base, 16)
    assert budget["per_person_social_optimum"] == 15 + 32 / 2
    assert budget["session_upper_bound"] == 16 * (15 + 16)
