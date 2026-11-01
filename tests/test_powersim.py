from dataclasses import replace

import numpy as np
import pytest
import statsmodels.api as sm

from powersim import (
    Design,
    analytic_power_session_means,
    design_effect,
    ols_cluster,
    ols_iid,
    rejection_rates,
    required_sessions,
    simulate_data,
    wild_cluster_bootstrap,
)


@pytest.fixture(scope="module")
def data():
    return simulate_data(Design(sessions_per_arm=3), np.random.default_rng(7))


@pytest.mark.parametrize("level", ["session", "group", "subject"])
def test_cluster_se_matches_statsmodels(data, level):
    X = sm.add_constant(data["treat"])
    fit = sm.OLS(data["y"], X).fit(cov_type="cluster", cov_kwds={"groups": data[level]})
    beta, se, df = ols_cluster(data["y"], data["treat"], data[level])
    assert beta == pytest.approx(fit.params[1], abs=1e-12)
    assert se == pytest.approx(fit.bse[1], rel=1e-10)
    assert df == len(np.unique(data[level])) - 1


def test_iid_se_matches_statsmodels(data):
    fit = sm.OLS(data["y"], sm.add_constant(data["treat"])).fit()
    assert ols_iid(data["y"], data["treat"])[1] == pytest.approx(fit.bse[1], rel=1e-10)


def test_dimensions():
    d = Design(sessions_per_arm=2, groups_per_session=3, group_size=4, rounds=5)
    x = simulate_data(d, np.random.default_rng(0))
    assert len(x["y"]) == 4 * 3 * 4 * 5
    assert len(np.unique(x["subject"])) == 4 * 12 and x["treat"].sum() == 2 * 12 * 5
    assert x["y"].min() >= 0 and x["y"].max() <= 1


def test_wild_bootstrap_pvalue_range(data):
    _, p = wild_cluster_bootstrap(data["y"], data["treat"], data["session"], np.random.default_rng(1), B=199)
    assert 0 <= p <= 1


def test_size_naive_vs_session_level():
    r = rejection_rates(Design(sessions_per_arm=6), reps=400, seed=3).set_index("estimator").rejection_rate
    assert r["ols_iid"] > 0.25                     # ignoring clustering grossly over-rejects
    assert 0.01 <= r["session_means"] <= 0.09      # session-level inference holds its size
    assert 0.01 <= r["wild_session"] <= 0.10


def test_analytic_power_matches_simulation():
    d = Design(sessions_per_arm=8, effect=0.12, clip=False)
    sim = rejection_rates(d, reps=600, seed=11).set_index("estimator").rejection_rate["session_means"]
    assert abs(sim - analytic_power_session_means(d)) < 0.08


def test_design_effect_and_required_sessions():
    assert design_effect(1, 0.3) == 1 and design_effect(11, 0.1) == pytest.approx(2.0)
    d = Design(effect=0.15)
    k = required_sessions(d)
    assert k is not None and analytic_power_session_means(replace(d, sessions_per_arm=k)) >= 0.8
    assert analytic_power_session_means(replace(d, sessions_per_arm=k - 1)) < 0.8


def test_invalid_design():
    with pytest.raises(ValueError):
        Design(sessions_per_arm=1)
    with pytest.raises(ValueError):
        Design(icc_session=0.5, icc_group=0.3, icc_subject=0.3)
