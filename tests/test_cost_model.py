"""Tests for the analytic cost / capacity model.

These are property tests, not regression tests: each one asserts something
that must hold for the model to mean what the paper says it means.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "research"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _approx import approx        # noqa: E402

from cost_model import (            # noqa: E402
    CostParams, PRESETS, annual_cost_rate, lower_bound, upper_bound,
    optimal_n, portfolio_vol, counterfactual,
)


# ----------------------------------------------------------------------
# The central claim: a per-trade floor breaks scale invariance.
# ----------------------------------------------------------------------
def test_proportional_costs_are_scale_invariant():
    """With no floor, doubling AUM must not change the cost RATE."""
    p = CostParams(commission_floor=0.0)
    a = annual_cost_rate(100_000, 12, 0.5, 4, p)
    b = annual_cost_rate(200_000, 12, 0.5, 4, p)
    assert a == approx(b, rel=1e-12)


def test_floor_breaks_scale_invariance():
    """With a floor, halving AUM must strictly raise the cost rate."""
    p = CostParams()
    big = annual_cost_rate(20_000, 12, 0.5, 4, p)
    small = annual_cost_rate(10_000, 12, 0.5, 4, p)
    assert small > big


def test_cost_rate_diverges_as_aum_goes_to_zero():
    p = CostParams()
    prev = 0.0
    for aum in (100_000, 10_000, 1_000, 100):
        r = annual_cost_rate(aum, 12, 0.5, 4, p)
        assert r > prev
        prev = r
    assert prev > 1.0      # below CNY 100 the annual cost exceeds the account


def test_floor_breakpoint_is_where_the_two_regimes_meet():
    """At exactly N*F/c the floor and the rate give the same commission."""
    p = CostParams()
    n = 12
    bp = p.floor_breakpoint(n)
    assert bp == approx(n * p.commission_floor / p.commission_rate)
    per_trade_rate = bp / n * p.commission_rate
    assert per_trade_rate == approx(p.commission_floor)
    # just above the breakpoint the rate is the proportional one
    above = p.commission_rate_at(bp * 10, n, 0.5)
    assert above == approx(2 * 0.5 * p.commission_rate, rel=1e-9)


def test_commission_rate_matches_hand_arithmetic():
    """CNY 2,500, 12 names, 50% turnover: 12 trades a side at the CNY 5
    floor = CNY 60 out and CNY 60 back = CNY 120 on CNY 2,500 = 4.8%...
    but only tau*N = 6 names actually turn over, so 6*5*2 = CNY 60 = 2.4%."""
    p = CostParams()
    assert p.commission_rate_at(2500, 12, 0.5) == approx(0.024)


# ----------------------------------------------------------------------
# Lower bound
# ----------------------------------------------------------------------
def test_lower_bound_closed_form_matches_numerical_search():
    p = CostParams()
    g, n, tau, f = 0.06, 12, 0.5, 4
    a_min = lower_bound(g, n, tau, f, p)["a_min"]
    assert a_min is not None
    # net alpha must cross zero exactly there
    below = g - annual_cost_rate(a_min * 0.99, n, tau, f, p)
    above = g - annual_cost_rate(a_min * 1.01, n, tau, f, p)
    assert below < 0 < above
    assert abs(g - annual_cost_rate(a_min, n, tau, f, p)) < 1e-9


def test_lower_bound_scales_linearly_in_n_and_in_the_floor():
    p = CostParams()
    a12 = lower_bound(0.06, 12, 0.5, 4, p)["a_min"]
    a24 = lower_bound(0.06, 24, 0.5, 4, p)["a_min"]
    assert a24 == approx(2 * a12, rel=1e-9)

    p2 = CostParams(commission_floor=10.0)
    assert lower_bound(0.06, 12, 0.5, 4, p2)["a_min"] == approx(
        2 * a12, rel=1e-9)


def test_no_lower_bound_when_proportional_costs_already_eat_the_alpha():
    p = CostParams(slippage=0.05)          # absurd slippage
    out = lower_bound(0.01, 12, 0.5, 4, p)
    assert out["a_min"] is None
    assert "exceed" in out["reason"]


def test_rebalancing_more_often_raises_the_floor():
    p = CostParams()
    quarterly = lower_bound(0.06, 12, 0.5, 4, p)["a_min"]
    monthly = lower_bound(0.06, 12, 0.5, 12, p)["a_min"]
    assert monthly > quarterly


# ----------------------------------------------------------------------
# The cross-market control
# ----------------------------------------------------------------------
def test_zero_commission_removes_the_lower_bound():
    cf = counterfactual(0.05, 12, 0.5, 4)
    assert cf["cn_retail"]["a_min"] > 0
    assert cf["us_retail_pre2019"]["a_min"] > 0
    assert cf["us_retail_post2019"]["a_min"] == 0.0
    assert "scale-invariant" in cf["us_retail_post2019"]["reason"]


def test_zero_floor_preset_is_truly_scale_invariant():
    p = PRESETS["us_retail_post2019"]
    rates = [annual_cost_rate(a, 12, 0.5, 4, p)
             for a in (1_000, 10_000, 10_000_000)]
    assert max(rates) == approx(min(rates), rel=1e-12)


# ----------------------------------------------------------------------
# Upper bound
# ----------------------------------------------------------------------
def test_upper_bound_decreases_with_worse_liquidity():
    p = CostParams()
    wide = upper_bound(0.06, 12, 0.5, 4, p, adv=1e8, daily_vol=0.02)["a_max"]
    thin = upper_bound(0.06, 12, 0.5, 4, p, adv=1e6, daily_vol=0.02)["a_max"]
    assert thin < wide


def test_upper_bound_is_zero_when_alpha_cannot_cover_proportional_costs():
    p = CostParams()
    out = upper_bound(0.001, 12, 0.5, 4, p, adv=1e8, daily_vol=0.02)
    assert out["a_max_impact"] == 0.0


def test_window_exists_for_plausible_parameters():
    p = CostParams()
    lo = lower_bound(0.06, 12, 0.5, 4, p)["a_min"]
    hi = upper_bound(0.06, 12, 0.5, 4, p, adv=5e7, daily_vol=0.022)["a_max"]
    assert lo < hi


# ----------------------------------------------------------------------
# Diversification / optimal N
# ----------------------------------------------------------------------
def test_portfolio_vol_falls_with_n_and_converges_to_systematic_floor():
    v1 = portfolio_vol(1, 0.35, 0.30)
    v10 = portfolio_vol(10, 0.35, 0.30)
    v1000 = portfolio_vol(1000, 0.35, 0.30)
    assert v1 > v10 > v1000
    assert v1 == approx(0.35)
    assert v1000 == approx(0.35 * math.sqrt(0.30), abs=1e-3)


def test_optimal_n_is_small_when_capital_is_small():
    p = CostParams()
    small = optimal_n(3_000, 0.06, 0.5, 4, p, 0.35, 0.30)["best"]["n"]
    large = optimal_n(1_000_000, 0.06, 0.5, 4, p, 0.35, 0.30)["best"]["n"]
    assert small < large
    assert small <= 5


def test_optimal_n_without_a_floor_ignores_capital():
    """Sanity check on the mechanism: remove the floor and the optimal
    holding count must stop depending on AUM."""
    p = CostParams(commission_floor=0.0)
    a = optimal_n(3_000, 0.06, 0.5, 4, p, 0.35, 0.30)["best"]["n"]
    b = optimal_n(1_000_000, 0.06, 0.5, 4, p, 0.35, 0.30)["best"]["n"]
    assert a == b
