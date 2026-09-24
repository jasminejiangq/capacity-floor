"""Tests for point-in-time alignment and the A-share execution rules.

These cover the two places where a Chinese-equity backtest most often goes
quietly wrong:

  1. Financial statements aligned to the wrong date, which either leaks
     the future or -- the subtler failure this project actually hit --
     delays the data so much that the factor is computed from eighteen-
     month-old fundamentals.
  2. Execution rules. Price limits, suspensions and one-price limit days
     ("一字板") make a large fraction of theoretical trades impossible.
     A backtest that ignores them books returns that were never available.
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "code"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _approx import approx           # noqa: E402
import engine as E                   # noqa: E402


# ----------------------------------------------------------------------
# Statutory filing deadlines
# ----------------------------------------------------------------------
def _avail(report_dates, ann_dates):
    df = pd.DataFrame({"report_date": report_dates, "ann_date": ann_dates})
    return list(E._财务可用日(df))


def test_statutory_deadlines_are_the_published_ones():
    """CSRC deadlines: Q1 by 30 Apr, interim by 31 Aug, Q3 by 31 Oct,
    annual by 30 Apr of the FOLLOWING year."""
    out = _avail(["20240331", "20240630", "20240930", "20231231"],
                 [None, None, None, None])
    assert out == ["2024-04-30", "2024-08-31", "2024-10-31", "2024-04-30"]


def test_early_announcement_is_used_when_it_really_is_early():
    out = _avail(["20240331"], ["2024-04-12"])
    assert out == ["2024-04-12"]


def test_late_vendor_announcement_is_clamped_to_the_deadline():
    """The bug this guards against: the vendor's ann_date field is the date
    of the MOST RECENT filing that mentions the period, not the first one.
    A 2017 interim report gets stamped with a 2018 date because the 2018
    interim report restates the prior-year comparatives. Measured median
    lag in this database was 396 days. Using it verbatim does not leak the
    future -- it does the opposite, and starves the quality factors."""
    out = _avail(["20170630"], ["2018-08-29"])
    assert out == ["2017-08-31"]


def test_missing_announcement_falls_back_to_the_deadline():
    out = _avail(["20240630"], [None])
    assert out == ["2024-08-31"]


def test_corrupt_announcement_before_period_end_is_rejected():
    """Regression test. The property test below generated an announcement
    date of 2009-11-11 for the 2010 annual report; the original code took
    min(ann_date, deadline) and trusted it, which is a look-ahead path.
    A filing cannot predate the period it reports on, so such a value is
    discarded in favour of the statutory deadline."""
    assert _avail(["20101231"], ["2009-11-11"]) == ["2011-04-30"]
    assert _avail(["20240630"], ["2024-06-30"]) == ["2024-08-31"]


def test_availability_is_never_before_the_period_end():
    """The non-negotiable property: no configuration of inputs may make a
    report usable before the period it describes has ended."""
    rng = np.random.default_rng(0)
    reports, anns = [], []
    for year in range(2010, 2026):
        for q in ("0331", "0630", "0930", "1231"):
            reports.append(f"{year}{q}")
            offset = int(rng.integers(-900, 900))
            anns.append((pd.Timestamp(f"{year}-{q[:2]}-{q[2:]}")
                         + pd.Timedelta(days=offset)).strftime("%Y-%m-%d"))
    out = _avail(reports, anns)
    for r, a in zip(reports, out):
        period_end = pd.Timestamp(f"{r[:4]}-{r[4:6]}-{r[6:]}")
        assert pd.Timestamp(a) >= period_end, (r, a)


# ----------------------------------------------------------------------
# Price-limit boards
# ----------------------------------------------------------------------
def test_chinext_and_star_get_the_wide_limit_even_when_flagged_st():
    """ChiNext (30) and STAR (68) trade +/-20% regardless of ST status, so
    the board test must run BEFORE the ST test. Getting this order wrong
    silently applies a 5% limit to 20%-limit names and blocks trades that
    were in fact executable."""
    assert E.板块("sz.300001", 是ST=True, 日期="2024-01-02") == "双创"
    assert E.板块("sh.688001", 是ST=True, 日期="2024-01-02") == "双创"
    assert E.板块("sz.300001", 是ST=False) == "双创"


def test_main_board_non_st():
    assert E.板块("sh.600000", 是ST=False) == "主板"
    assert E.板块("sz.000001", 是ST=False) == "主板"


def test_st_limit_widens_on_the_2026_rule_change():
    """Main-board ST names moved from +/-5% to +/-10% on 2026-07-06."""
    assert E.板块("sh.600000", 是ST=True, 日期="2026-07-05") == "ST"
    assert E.板块("sh.600000", 是ST=True, 日期="2026-07-06") == "ST宽"
    assert E.板块("sh.600000", 是ST=True, 日期="2027-01-04") == "ST宽"


def test_limit_thresholds_sit_just_inside_the_legal_limit():
    """Thresholds are set marginally inside the statutory limit so that
    rounding in the price feed does not cause a limit day to be missed."""
    assert 0.09 < E.涨停阈值["主板"] < 0.10
    assert 0.19 < E.涨停阈值["双创"] < 0.20
    assert 0.04 < E.涨停阈值["ST"] < 0.05
    assert E.涨停阈值["ST宽"] == approx(E.涨停阈值["主板"])


# ----------------------------------------------------------------------
# Costs
# ----------------------------------------------------------------------
def test_buy_cost_uses_the_commission_floor_on_small_orders():
    saved = (E.佣金费率, E.佣金最低, E.印花税率, E.过户费率, E.滑点率)
    E.佣金费率, E.佣金最低 = 0.00015, 5.0
    E.印花税率, E.过户费率, E.滑点率 = 0.0005, 0.00001, 0.0010
    try:
        # CNY 1,000 order: rate would give CNY 0.15, so the floor binds.
        c = E.买入成本(1000.0)
        assert c == approx(5.0 + 1000 * 0.00001 + 1000 * 0.0010)
        # CNY 100,000 order: rate gives CNY 15, above the floor.
        c = E.买入成本(100_000.0)
        assert c == approx(15.0 + 100_000 * 0.00001 + 100_000 * 0.0010)
    finally:
        (E.佣金费率, E.佣金最低, E.印花税率,
         E.过户费率, E.滑点率) = saved


def test_sell_cost_adds_stamp_duty_and_buy_cost_does_not():
    saved = (E.佣金费率, E.佣金最低, E.印花税率, E.过户费率, E.滑点率)
    E.佣金费率, E.佣金最低 = 0.00015, 5.0
    E.印花税率, E.过户费率, E.滑点率 = 0.0005, 0.00001, 0.0010
    try:
        amount = 50_000.0
        assert (E.卖出成本(amount) - E.买入成本(amount)) == approx(
            amount * 0.0005)
    finally:
        (E.佣金费率, E.佣金最低, E.印花税率,
         E.过户费率, E.滑点率) = saved


def test_cost_as_a_fraction_explodes_on_tiny_orders():
    saved = (E.佣金费率, E.佣金最低)
    E.佣金费率, E.佣金最低 = 0.00015, 5.0
    try:
        assert E.买入成本(200.0) / 200.0 > 0.02
        assert E.买入成本(100_000.0) / 100_000.0 < 0.002
    finally:
        E.佣金费率, E.佣金最低 = saved


# ----------------------------------------------------------------------
# Position sizing
# ----------------------------------------------------------------------
def test_minimum_ticket_caps_the_number_of_positions():
    """With a CNY 5 floor per trade, splitting CNY 2,500 across 12 names
    means paying 12 x CNY 5 = CNY 60 a side on CNY 2,500. The minimum
    ticket rule is how the user states what they will pay for
    diversification."""
    F = pd.DataFrame({"真实价": [5.0] * 40},
                     index=[f"sh.6000{i:02d}" for i in range(40)])
    score = pd.Series(np.linspace(1, 0, 40), index=F.index)
    saved = (E.单笔最小金额, E.持仓上限)
    try:
        E.持仓上限 = 35
        E.单笔最小金额 = 0.0
        _, n_free, _, _ = E.选股(F, score, F.index, 2500.0)
        E.单笔最小金额 = 800.0
        _, n_capped, _, _ = E.选股(F, score, F.index, 2500.0)
        assert n_capped <= 3
        assert n_capped < n_free
    finally:
        E.单笔最小金额, E.持仓上限 = saved


def test_selection_never_picks_a_name_it_cannot_afford_one_lot_of():
    """A-shares trade in lots of 100. A CNY 180 share needs CNY 18,000 for
    a single lot; at CNY 2,000 of capital it is simply not buyable, and the
    highest-scoring name being unbuyable must not empty the portfolio."""
    prices = [180.0] + [4.0] * 29
    F = pd.DataFrame({"真实价": prices},
                     index=[f"sh.6000{i:02d}" for i in range(30)])
    score = pd.Series(np.linspace(1, 0, 30), index=F.index)
    saved = (E.单笔最小金额, E.持仓上限)
    try:
        E.单笔最小金额, E.持仓上限 = 0.0, 10
        picks, n, blocked, _ = E.选股(F, score, F.index, 2000.0)
        assert n >= 1
        assert "sh.600000" not in set(picks)
        assert blocked >= 1
        for c in picks:
            assert F.at[c, "真实价"] * 100 <= 2000.0 / n + 1e-9
    finally:
        E.单笔最小金额, E.持仓上限 = saved
