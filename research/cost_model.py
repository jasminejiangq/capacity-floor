"""
cost_model.py -- Analytic transaction-cost and capacity model.

This module has NO dependency on the database or on the backtest engine.
It is pure arithmetic, which is why it can be unit-tested exhaustively
(see tests/test_cost_model.py).

------------------------------------------------------------------
Why this module exists
------------------------------------------------------------------
The academic transaction-cost literature (Novy-Marx & Velikov, RFS 2016;
Frazzini, Israel & Moskowitz, 2018; Detzel et al., JF 2023) models trading
costs as PROPORTIONAL: some number of basis points of notional traded.

Proportional costs are scale-invariant.  Doubling assets under management
doubles both the gross P&L and the cost, so the net return per unit of
capital is unchanged.  Under a purely proportional model the only thing
that can bound strategy capacity is market impact, which grows with size.
Hence the literature reports capacity as a CEILING: "this anomaly survives
up to $X billion."

Chinese A-share retail brokerage does not work that way.  Commission is
quoted as a rate (here 1.5 bps) but subject to a HARD PER-TRADE MINIMUM of
CNY 5.00.  A CNY 5 minimum is a FIXED cost.  Fixed costs are not
scale-invariant: as a fraction of capital they behave like 1/A.

The consequence is that capacity is a WINDOW, not a ceiling:

    A_min  <  A  <  A_max
     ^                ^
     |                +-- market impact (the classical bound)
     +------------------- per-trade commission floor (ignored by the
                          literature because the literature models US
                          institutional execution, where it does not exist)

Below A_min the commission floor alone consumes the entire gross alpha,
regardless of how good the signal is.  This is the part nobody publishes,
and it is precisely the part that decides whether a retail investor with
CNY 2,500 can run a quarterly multi-factor strategy at all.

------------------------------------------------------------------
Notation
------------------------------------------------------------------
    A     assets under management (CNY)
    N     number of positions held
    tau   one-way turnover per rebalance, as a fraction of portfolio value
          (tau = 0.5 means half the book is replaced)
    f     rebalances per year
    c     commission rate (one way)
    F     commission floor per trade, one way (CNY)
    d     stamp duty, SELL side only
    u     transfer fee, both sides
    s     slippage, one side
    g     GROSS annual return in excess of the benchmark ("alpha"),
          measured with all costs switched off

All rates are decimals, not percent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field


# ----------------------------------------------------------------------
# Default A-share retail cost parameters.
# Sources are recorded in docs/01_data_integrity.md and 研究来源登记表.md.
# ----------------------------------------------------------------------
@dataclass
class CostParams:
    commission_rate: float = 0.00015   # 1.5 bps, one way
    commission_floor: float = 5.0      # CNY, per trade, one way -- THE key term
    stamp_duty: float = 0.0005         # 5 bps, sell side only (since 2023-08-28)
    transfer_fee: float = 0.00001      # 0.1 bps, both sides
    slippage: float = 0.0010           # 10 bps one side, conservative for small caps

    # Market-impact model: impact = impact_coef * daily_vol * sqrt(Q / ADV)
    # Square-root law.  Coefficient near 1 is the standard calibration
    # (Almgren et al. 2005; Torre & Ferrari 1997; Frazzini et al. 2018).
    impact_coef: float = 1.0
    # Cap on participation: fraction of one day's ADV a single order may take.
    max_participation: float = 0.10

    def proportional_rate(self, tau: float) -> float:
        """Per-rebalance cost rate from the SCALE-INVARIANT terms only.

        Stamp duty is charged on sells only, so it applies to tau of the book.
        Transfer fee and slippage apply to both the sell leg and the buy leg,
        hence the factor 2.
        """
        return tau * (self.stamp_duty + 2 * self.transfer_fee + 2 * self.slippage)

    def commission_rate_at(self, aum: float, n: int, tau: float) -> float:
        """Per-rebalance cost rate from commission ALONE.

        This is the whole point of the paper.  Per trade the broker charges
            max(notional * c, F)
        With N equal-weighted positions the notional per trade is A/N, and a
        rebalance with one-way turnover tau touches tau*N names on the sell
        side and tau*N on the buy side.

            commission_cny  = 2 * tau * N * max(A/N * c, F)
            commission_rate = commission_cny / A

        If the floor does NOT bind this collapses to 2*tau*c -- a constant,
        independent of A.  If the floor DOES bind it becomes 2*tau*N*F/A,
        which diverges as A -> 0.
        """
        if aum <= 0 or n <= 0:
            return float("inf")
        per_trade = max(aum / n * self.commission_rate, self.commission_floor)
        return 2.0 * tau * n * per_trade / aum

    def floor_breakpoint(self, n: int) -> float:
        """AUM above which the commission floor stops binding.

        Floor binds while  A/N * c < F,  i.e.  A < N * F / c.
        With N=12, F=5, c=1.5bps this is CNY 400,000 -- which is far above
        anything a Chinese retail investor with a few thousand yuan will ever
        hold.  In other words: for the entire retail range, commission is a
        FIXED cost, not a proportional one.
        """
        if self.commission_floor <= 0:
            return 0.0                    # no floor -> never binds
        if self.commission_rate <= 0:
            return float("inf")           # zero rate -> the floor always binds
        return n * self.commission_floor / self.commission_rate

    def impact_rate_at(self, aum: float, n: int, tau: float,
                       adv: float, daily_vol: float) -> float:
        """Per-rebalance cost rate from market impact (square-root law).

        adv       : average daily notional turnover of a typical holding (CNY)
        daily_vol : daily return volatility of a typical holding (decimal)
        """
        if aum <= 0 or n <= 0 or adv <= 0:
            return 0.0
        q = aum / n                       # notional per name
        impact = self.impact_coef * daily_vol * math.sqrt(q / adv)
        return 2.0 * tau * impact         # both legs


def annual_cost_rate(aum: float, n: int, tau: float, f: float,
                     p: CostParams,
                     adv: float | None = None,
                     daily_vol: float | None = None) -> float:
    """Total annual cost as a fraction of AUM."""
    per_rebalance = p.commission_rate_at(aum, n, tau) + p.proportional_rate(tau)
    if adv is not None and daily_vol is not None:
        per_rebalance += p.impact_rate_at(aum, n, tau, adv, daily_vol)
    return f * per_rebalance


# ----------------------------------------------------------------------
# Closed-form bounds
# ----------------------------------------------------------------------
def lower_bound(g: float, n: int, tau: float, f: float,
                p: CostParams) -> dict:
    """Smallest AUM at which gross alpha still covers total cost.

    In the floor-binding region the break-even condition is

        g = f * [ 2*tau*N*F/A  +  tau*(d + 2u + 2s) ]

    which solves in closed form:

        A_min = 2*f*tau*N*F / ( g - f*tau*(d + 2u + 2s) )

    The denominator is the alpha left over after the scale-invariant costs.
    If it is not positive, the strategy is unprofitable at EVERY size and no
    lower bound exists -- the strategy is dead on proportional costs alone,
    before the floor is even considered.
    """
    prop_annual = f * p.proportional_rate(tau)
    residual = g - prop_annual
    if p.commission_floor <= 0:
        # No fixed component. The cost function is scale-invariant, so the
        # net return per unit of capital does not depend on capital at all
        # and there is no lower capacity bound. This is the US-retail case
        # after October 2019, and it is the control in the experiment.
        return {
            "gross_alpha": g,
            "annual_proportional_cost": prop_annual,
            "residual_alpha": residual,
            "floor_breakpoint": 0.0,
            "a_min": 0.0 if residual > 0 else None,
            "reason": ("no per-trade floor: costs are scale-invariant, "
                       "no lower bound exists" if residual > 0 else
                       "unprofitable at every size on proportional costs alone"),
        }
    out = {
        "gross_alpha": g,
        "annual_proportional_cost": prop_annual,
        "residual_alpha": residual,
        "floor_breakpoint": p.floor_breakpoint(n),
    }
    if residual <= 0:
        out["a_min"] = None
        out["reason"] = ("proportional costs alone exceed gross alpha; "
                         "no AUM makes this strategy profitable")
        return out

    a_min = 2.0 * f * tau * n * p.commission_floor / residual
    out["a_min"] = a_min

    # Consistency check: the closed form assumed the floor binds at A_min.
    if a_min > out["floor_breakpoint"]:
        # The floor stops binding before break-even is reached, so the true
        # constraint is the proportional commission 2*tau*c instead.
        residual2 = g - prop_annual - f * 2.0 * tau * p.commission_rate
        out["a_min"] = None if residual2 <= 0 else 0.0
        out["reason"] = ("commission floor stops binding below break-even; "
                         "no fixed-cost lower bound"
                         if residual2 > 0 else
                         "unprofitable even without the floor")
    else:
        out["reason"] = "commission floor binds; lower bound is real"
    return out


def upper_bound(g: float, n: int, tau: float, f: float,
                p: CostParams, adv: float, daily_vol: float) -> dict:
    """Largest AUM at which gross alpha still covers total cost.

    Above the floor breakpoint the commission is proportional (2*tau*c),
    so break-even against market impact is

        g/f = 2*tau*c + tau*(d+2u+2s) + 2*tau*Y*sigma_d*sqrt(A/(N*ADV))

    =>  A_max = N*ADV * [ (g/f - 2*tau*c - tau*(d+2u+2s)) / (2*tau*Y*sigma_d) ]^2

    We also report the naive participation cap, which is what a practitioner
    would actually use as a hard constraint: never take more than
    max_participation of one day's ADV in a single name.
    """
    prop = p.proportional_rate(tau) + 2.0 * tau * p.commission_rate
    budget = g / f - prop
    out = {"impact_budget_per_rebalance": budget}
    if budget <= 0 or adv <= 0 or daily_vol <= 0:
        out["a_max_impact"] = 0.0
    else:
        root = budget / (2.0 * tau * p.impact_coef * daily_vol)
        out["a_max_impact"] = n * adv * root * root
    out["a_max_participation"] = p.max_participation * adv * n
    out["a_max"] = min(out["a_max_impact"], out["a_max_participation"])
    return out


def capacity_window(g: float, n: int, tau: float, f: float,
                    p: CostParams, adv: float, daily_vol: float) -> dict:
    lo = lower_bound(g, n, tau, f, p)
    hi = upper_bound(g, n, tau, f, p, adv, daily_vol)
    w = {"n": n, "tau": tau, "rebalances_per_year": f,
         "lower": lo, "upper": hi}
    if lo.get("a_min") is not None and hi.get("a_max"):
        w["window_exists"] = lo["a_min"] < hi["a_max"]
        w["window_width_decades"] = (
            math.log10(hi["a_max"] / lo["a_min"]) if lo["a_min"] > 0 else None)
    else:
        w["window_exists"] = None
    return w


# ----------------------------------------------------------------------
# Optimal N: the diversification / fixed-cost trade-off
# ----------------------------------------------------------------------
def portfolio_vol(n: int, avg_vol: float, avg_corr: float) -> float:
    """Equal-weighted portfolio volatility under a constant-correlation model.

        sigma_p(N) = sigma_bar * sqrt( rho + (1-rho)/N )

    Standard result (Elton & Gruber 1977).  As N -> inf this tends to
    sigma_bar*sqrt(rho), the systematic floor.
    """
    n = max(1, int(n))
    return avg_vol * math.sqrt(avg_corr + (1.0 - avg_corr) / n)


def optimal_n(aum: float, g: float, tau: float, f: float, p: CostParams,
              avg_vol: float, avg_corr: float,
              n_max: int = 40,
              adv: float | None = None,
              daily_vol: float | None = None) -> dict:
    """Choose N to maximise net Sharpe ratio at a given AUM.

    More names => lower idiosyncratic risk (good) but more trades, and with
    a per-trade floor that means strictly more cost (bad).  At small AUM the
    fixed cost dominates and the optimum collapses to a handful of names.

    This is the practically useful output of the whole framework: it tells a
    retail investor with CNY 3,000 that holding 12 names is not "prudent
    diversification", it is a guaranteed loss to the broker.
    """
    best, curve = None, []
    for n in range(1, n_max + 1):
        cost = annual_cost_rate(aum, n, tau, f, p, adv, daily_vol)
        net = g - cost
        vol = portfolio_vol(n, avg_vol, avg_corr)
        sharpe = net / vol if vol > 0 else float("-inf")
        row = {"n": n, "annual_cost_rate": cost,
               "net_alpha": net, "portfolio_vol": vol, "net_sharpe": sharpe}
        curve.append(row)
        if best is None or sharpe > best["net_sharpe"]:
            best = row
    return {"aum": aum, "best": best, "curve": curve}





# ----------------------------------------------------------------------
# Market / era presets
# ----------------------------------------------------------------------
# The point of these three is that they differ in ONE structural respect:
# whether commission has a per-trade floor.  A-share retail has one and
# always has.  US retail had one until the autumn of 2019, when Schwab,
# TD Ameritrade, E*TRADE and Fidelity went to zero within days of each
# other.  That is a clean structural break in the cost FUNCTION, not just
# in its level, and it is the natural experiment this project uses as its
# cross-market control: if the lower capacity bound is really caused by
# the fixed component, it must disappear in US retail after October 2019
# and must still be present before it.

PRESETS: dict[str, "CostParams"] = {
    # Chinese A-share retail, competitive broker, 2023 stamp-duty cut applied.
    "cn_retail": CostParams(
        commission_rate=0.00015, commission_floor=5.0,
        stamp_duty=0.0005, transfer_fee=0.00001, slippage=0.0010),

    # US retail before the October 2019 price war. Representative online
    # broker: $4.95 flat per trade, no stamp duty, SEC Section 31 fee on
    # sells only (~$0.0000278 per dollar in 2019 -- negligible but real).
    "us_retail_pre2019": CostParams(
        commission_rate=0.0, commission_floor=4.95,
        stamp_duty=0.0000278, transfer_fee=0.0, slippage=0.0010),

    # US retail after October 2019: commission is zero. The per-trade
    # FLOOR is gone, so the cost function becomes purely proportional and
    # scale-invariant -- and the lower capacity bound should vanish.
    "us_retail_post2019": CostParams(
        commission_rate=0.0, commission_floor=0.0,
        stamp_duty=0.0000278, transfer_fee=0.0, slippage=0.0010),
}


def counterfactual(g: float, n: int, tau: float, f: float) -> dict:
    """Run the lower-bound calculation under each preset.

    This is the headline comparison of the whole project: the same signal,
    the same turnover, the same holding count -- only the cost FUNCTION
    changes -- and the minimum viable account size moves by orders of
    magnitude, or ceases to exist.
    """
    out = {}
    for name, p in PRESETS.items():
        lo = lower_bound(g, n, tau, f, p)
        out[name] = {
            "commission_floor": p.commission_floor,
            "commission_rate": p.commission_rate,
            "a_min": lo["a_min"],
            "reason": lo["reason"],
            "annual_proportional_cost": lo["annual_proportional_cost"],
            "floor_breakpoint": lo["floor_breakpoint"],
        }
    return out


def a_min_sensitivity(n_values, g_values, tau: float, f: float,
                      p: "CostParams") -> list:
    """A_min as a function of assumed gross alpha and holding count.

    Reported because the framework should be judged on its own, not on
    whether this particular four-factor signal happens to have alpha.  A
    reader who believes a different gross alpha can read their own answer
    off this grid.
    """
    rows = []
    for n in n_values:
        for g in g_values:
            lo = lower_bound(g, int(n), tau, f, p)
            rows.append({"n": int(n), "gross_alpha": float(g),
                         "a_min": lo["a_min"], "reason": lo["reason"]})
    return rows


# ----------------------------------------------------------------------
# Two floors, not one
# ----------------------------------------------------------------------
# A_min is linear in N, so the whole content of the fee-based lower bound is
# a single per-position number. That reframing matters, because it puts the
# fee constraint into the same units as a second constraint that is easy to
# overlook and often binds harder:
#
#   fee floor   capital a position must carry for its share of the fees not
#               to exceed its share of the alpha.   Economic. Soft: the trade
#               executes, you simply lose money on it.
#
#   lot floor   capital a position must carry to be buyable at all. Chinese
#               A-shares trade in lots of 100 shares, so one position costs
#               100 x price whether you want that much of it or not.
#               Mechanical. Hard: the broker rejects the order.
#
# They are independent. US retail has no lot constraint (fractional shares
# are routine) but did have a USD 4.95 per-trade commission until October
# 2019 -- a fee floor with no lot floor. A-shares have both at once, which is
# why they are easy to confuse there and why the US case is what separates
# them.
#
# The real minimum account is N times whichever per-position requirement is
# larger.

def capital_per_name(g: float, tau: float, f: float, p: "CostParams") -> float:
    """Capital one position must carry for fees not to eat its alpha.

    Since

        A_min(N) = N * 2*f*tau*F / (g - f*tau*(d+2u+2s))

    is linear in N, the bound is really a per-position quantity and quoting
    A_min without saying how many positions it assumes is meaningless. With
    the measured inputs for this strategy it is about CNY 304 a name; the
    familiar CNY 3,643 is simply that times twelve.
    """
    residual = g - f * p.proportional_rate(tau)
    if residual <= 0:
        return float("inf")
    return 2.0 * f * tau * p.commission_floor / residual


def lot_capital_per_name(lot_cost: float) -> float:
    """Capital one position must carry to be buyable.

    lot_cost is the cash price of one lot: 100 * share price in the A-share
    market. There is no averaging away of this one -- a position is a whole
    number of lots or it does not exist.
    """
    return float(lot_cost)


def binding_minimum(g: float, n: int, tau: float, f: float,
                    p: "CostParams", lot_cost: float) -> dict:
    """Minimum viable account when both floors are respected.

    Returns the two per-position requirements, which of them binds, and the
    resulting minimum account for N positions. Reporting only the larger one
    would hide the fact that they can swap places: the fee floor is fixed in
    yuan, while the lot floor moves with the price of whatever the strategy
    wants to hold.
    """
    fee_pn = capital_per_name(g, tau, f, p)
    lot_pn = lot_capital_per_name(lot_cost)
    binds = "fee" if fee_pn >= lot_pn else "lot"
    per_name = max(fee_pn, lot_pn)
    return {
        "n": int(n),
        "fee_capital_per_name": fee_pn,
        "lot_capital_per_name": lot_pn,
        "binding_constraint": binds,
        "capital_per_name": per_name,
        "minimum_account": per_name * n,
        "fee_only_minimum": fee_pn * n,
        "lot_only_minimum": lot_pn * n,
    }


__all__ = ["CostParams", "annual_cost_rate", "lower_bound", "upper_bound",
           "capacity_window", "portfolio_vol", "optimal_n",
           "PRESETS", "counterfactual", "a_min_sensitivity",
           "capital_per_name", "lot_capital_per_name", "binding_minimum"]
