"""Tests for the statistics helpers.

Each estimator is checked against a case where the right answer is known
analytically or by construction, not against a previously recorded output.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "research"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _approx import approx                      # noqa: E402
from stats_tools import (                       # noqa: E402
    newey_west_t, icir, deflated_sharpe, haircut_sharpe, mr_test, pbo_cscv,
    spearman_ic,
)


# ----------------------------------------------------------------------
def test_newey_west_equals_ols_t_when_no_autocorrelation_is_allowed():
    rng = np.random.default_rng(0)
    x = rng.normal(0.01, 0.1, 400)
    nw = newey_west_t(x, lags=0)
    t_ols = x.mean() / (x.std(ddof=0) / math.sqrt(len(x)))
    assert nw["t"] == approx(t_ols, rel=1e-9)


def test_newey_west_shrinks_t_on_positively_autocorrelated_data():
    """This is the whole reason the correction exists: overlapping or
    persistent series look far more significant than they are."""
    rng = np.random.default_rng(1)
    e = rng.normal(0, 1, 2000)
    x = np.zeros(2000)
    for i in range(1, 2000):
        x[i] = 0.8 * x[i - 1] + e[i]
    x = x + 0.5
    naive = newey_west_t(x, lags=0)["t"]
    robust = newey_west_t(x)["t"]
    assert robust < naive
    assert robust / naive < 0.6


def test_newey_west_handles_degenerate_input():
    out = newey_west_t([1.0])
    assert math.isnan(out["t"])


# ----------------------------------------------------------------------
def test_icir_threshold_follows_from_the_t3_rule():
    """ICIR_annual bar must equal 3/sqrt(years); that is the only content
    of the 'ICIR > 0.5' folklore once you fix the hurdle at t = 3."""
    rng = np.random.default_rng(2)
    ic = rng.normal(0.03, 0.08, 60)      # 60 quarters = 15 years
    out = icir(ic, 4)
    assert out["years"] == approx(15.0)
    assert out["hlz_threshold_icir"] == approx(3.0 / math.sqrt(15.0))


def test_icir_annualisation():
    ic = np.array([0.05, -0.01, 0.03, 0.02, 0.04, -0.02] * 10)
    out = icir(ic, 12)
    assert out["icir_annual"] == approx(
        out["icir_per_period"] * math.sqrt(12), rel=1e-9)


# ----------------------------------------------------------------------
def test_deflated_sharpe_falls_as_trials_rise():
    a = deflated_sharpe(0.08, 3000, 1)["dsr"]
    b = deflated_sharpe(0.08, 3000, 50)["dsr"]
    c = deflated_sharpe(0.08, 3000, 5000)["dsr"]
    assert a > b > c


def test_deflated_sharpe_penalises_negative_skew_and_fat_tails():
    base = deflated_sharpe(0.06, 3000, 50, skew=0.0, kurt=3.0)["dsr"]
    bad = deflated_sharpe(0.06, 3000, 50, skew=-1.5, kurt=12.0)["dsr"]
    assert bad < base


def test_expected_max_sharpe_under_null_grows_with_trials():
    a = deflated_sharpe(0.05, 3000, 2)["expected_max_sharpe_under_null"]
    b = deflated_sharpe(0.05, 3000, 200)["expected_max_sharpe_under_null"]
    assert b > a > 0


# ----------------------------------------------------------------------
def test_haircut_removes_more_when_more_tests_were_run():
    a = haircut_sharpe(4.0, 1, 15)
    b = haircut_sharpe(4.0, 100, 15)
    assert a["haircut"] < b["haircut"]
    assert a["t_adjusted"] > b["t_adjusted"]


def test_haircut_is_zero_for_a_single_test():
    out = haircut_sharpe(3.0, 1, 15)
    assert out["haircut"] == approx(0.0, abs=1e-6)


def test_weak_result_does_not_survive_many_tests():
    """A t of 1.4 -- which is roughly what an honest retail A-share
    strategy produces -- must be annihilated by any serious correction."""
    out = haircut_sharpe(1.4, 26, 15)
    assert out["surviving_fraction"] == approx(0.0, abs=1e-9)


# ----------------------------------------------------------------------
def test_mr_test_accepts_a_genuinely_monotone_pattern():
    rng = np.random.default_rng(3)
    means = np.linspace(-0.02, 0.02, 10)
    X = rng.normal(0, 0.01, (400, 10)) + means
    out = mr_test(X, n_boot=400)
    assert out["monotone_in_sample"] is True
    assert out["p_value"] < 0.05


def test_mr_test_rejects_a_spread_that_is_not_monotone():
    """Top-minus-bottom is strongly positive, yet the interior is a mess.
    The spread test would pass; the MR test must not."""
    rng = np.random.default_rng(4)
    means = np.array([-0.03, 0.01, -0.01, 0.00, 0.01,
                      -0.005, 0.005, 0.00, 0.01, 0.03])
    X = rng.normal(0, 0.01, (400, 10)) + means
    out = mr_test(X, n_boot=400)
    assert (X.mean(0)[-1] - X.mean(0)[0]) > 0.05
    assert out["monotone_in_sample"] is False
    assert out["n_steps_wrong_way"] >= 3
    assert out["p_value"] > 0.10


def test_mr_test_on_flat_data_does_not_reject():
    rng = np.random.default_rng(5)
    X = rng.normal(0, 0.01, (300, 10))
    out = mr_test(X, n_boot=400)
    assert out["p_value"] > 0.05


# ----------------------------------------------------------------------
def test_pbo_is_near_one_half_on_pure_noise():
    """With no true skill, choosing the best backtest must be a coin flip
    out of sample.  Averaged over independent datasets, PBO -> 0.5."""
    rng = np.random.default_rng(6)
    vals = []
    for k in range(10):
        X = rng.normal(0, 0.05, (240, 16))
        vals.append(pbo_cscv(X, n_splits=10, seed=k)["pbo"])
    assert 0.30 < float(np.mean(vals)) < 0.70


def test_pbo_is_low_when_one_configuration_is_genuinely_better():
    rng = np.random.default_rng(7)
    X = rng.normal(0, 0.05, (240, 16))
    X[:, 3] += 0.05                      # a real, persistent edge
    out = pbo_cscv(X, n_splits=10)
    assert out["pbo"] < 0.10


def test_pbo_rejects_a_single_configuration():
    out = pbo_cscv(np.zeros((100, 1)))
    assert "error" in out


def test_mr_test_never_concludes_monotone_on_a_non_monotone_sample():
    """The least-favourable-null bootstrap can hand back a small p-value on
    a sample whose pattern is not monotone at all, because the null
    distribution of min-diff sits below zero. The verdict must depend on
    both facts, not on the p-value alone."""
    rng = np.random.default_rng(11)
    means = np.array([0.0, 0.02, -0.01, 0.015, 0.0,
                      0.01, -0.005, 0.02, 0.0, 0.01])
    X = rng.normal(0, 0.02, (60, 10)) + means
    out = mr_test(X, n_boot=400)
    assert out["monotone_in_sample"] is False
    assert out["monotonic"] is False
    assert out["monotonic"] is False
    assert "strictly monotone" not in out["verdict"]


def test_mr_test_verdict_is_positive_only_when_both_conditions_hold():
    rng = np.random.default_rng(12)
    X = rng.normal(0, 0.008, (500, 8)) + np.linspace(-0.02, 0.02, 8)
    out = mr_test(X, n_boot=400)
    assert out["monotone_in_sample"] is True
    assert out["p_value"] < 0.05
    assert out["monotonic"] is True
    assert out["verdict"] == "strictly monotone, flatness rejected"
    assert out["flatness_rejected"] is True


# ----------------------------------------------------------------------
def test_spearman_ic_matches_the_definition_with_ties():
    """Spearman is Pearson on average-ranked data. Checked against a case
    computed by hand rather than against another library, so the test does
    not depend on the dependency this function exists to avoid."""
    import pandas as pd
    a = pd.Series([1.0, 2.0, 2.0, 4.0, 5.0])     # a tie at rank 2.5
    b = pd.Series([10.0, 9.0, 8.0, 7.0, 6.0])    # strictly decreasing
    ra = pd.Series([1.0, 2.5, 2.5, 4.0, 5.0])
    rb = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
    expected = float(np.corrcoef(ra, rb)[0, 1])
    assert spearman_ic(a, b) == approx(expected, abs=1e-12)


def test_spearman_ic_is_invariant_to_monotone_transforms():
    """The property that makes rank IC the right headline for fat-tailed
    A-share returns: one limit-up name cannot drive it."""
    import pandas as pd
    rng = np.random.default_rng(3)
    a = pd.Series(rng.normal(0, 1, 300))
    b = pd.Series(rng.normal(0, 1, 300) + 0.4 * a)
    base = spearman_ic(a, b)
    blown = b.copy()
    blown.iloc[0] = 1e6                      # one absurd outlier
    assert spearman_ic(a, blown) == approx(base, abs=0.02)
    assert abs(a.corr(blown) - a.corr(b)) > 0.05   # Pearson is not immune


def test_spearman_ic_ranks_after_pairwise_deletion():
    """Ranking each series over its own full support and only then dropping
    incomplete pairs gives a different, wrong answer. This asserts the
    order, because with complete inputs the bug is invisible."""
    import pandas as pd
    a = pd.Series([1.0, 2.0, 3.0, 4.0, np.nan, 6.0])
    b = pd.Series([6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    assert spearman_ic(a, b) == approx(-1.0, abs=1e-12)


def test_spearman_ic_returns_nan_on_too_few_pairs():
    import pandas as pd
    a = pd.Series([1.0, np.nan, np.nan])
    b = pd.Series([1.0, 2.0, 3.0])
    assert math.isnan(spearman_ic(a, b))


def test_mr_verdict_separates_flatness_rejection_from_strict_monotonicity():
    """A pattern that rises decisively but inverts one adjacent step must
    not be summarised as a negative result. This is the exact shape the
    low-volatility factor produced on real data: p well under 0.05 with
    one step out of nine going the wrong way."""
    rng = np.random.default_rng(21)
    mu = np.array([-0.015, -0.008, -0.004, 0.000, 0.0040,
                   0.0038, 0.009, 0.014, 0.020, 0.030])  # step 5->6 inverted
    X = rng.normal(0, 0.02, (300, 10)) + mu
    out = mr_test(X, n_boot=800)
    assert out["n_steps_wrong_way"] == 1
    assert out["monotone_in_sample"] is False
    assert out["flatness_rejected"] is True
    assert "flatness rejected" in out["verdict"]
    assert "inverted" in out["verdict"]
