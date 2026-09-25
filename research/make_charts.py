# -*- coding: utf-8 -*-
"""
make_charts.py -- Regenerate every figure from results/*.json.

    python research/make_charts.py

Reads only the JSON that capacity.py and factor_eval.py already wrote, so it
needs no database and no backtest: it runs in about a second. That matters
more than it sounds. The figures were originally produced inside the long
scripts, which meant that a missing plotting library, or wanting to relabel
an axis, cost a ninety-minute re-run. Separating "compute the numbers" from
"draw the numbers" is the same discipline as separating data from
presentation anywhere else.

Palette: five categorical hues, fixed order, validated for colour-vision
deficiency (worst adjacent pair dE 15.1 deutan, 28.4 normal-vision) and for
contrast against the surface. Not eyeballed.
"""

from __future__ import annotations

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.ticker import FuncFormatter   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")

# Fixed categorical order -- assigned by entity, never cycled, never reordered
# when a series is dropped.
HUES = {
    "low_volatility": "#3b5bdb",
    "dividend":       "#d1410c",
    "composite":      "#0f9490",
    "value":          "#7c3aed",
    "quality":        "#b45309",
}
ORDER = ["low_volatility", "dividend", "composite", "value", "quality"]
LABEL = {"low_volatility": "low volatility", "dividend": "dividend",
         "composite": "composite", "value": "value", "quality": "quality"}

INK      = "#1a1a1a"      # primary text
INK_SOFT = "#5c5c5c"      # secondary text
GRID     = "#d9d9d6"
SURFACE  = "#fcfcfb"
ACCENT   = "#b91c1c"      # annotation only, never a series


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, color=INK, fontsize=12, pad=12, loc="left")
    ax.set_xlabel(xlabel, color=INK_SOFT, fontsize=9)
    ax.set_ylabel(ylabel, color=INK_SOFT, fontsize=9)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK_SOFT, labelsize=9, length=0)


def _fig(w=8.2, h=4.8):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    return fig, ax


def _save(fig, name):
    p = os.path.join(RESULTS, name)
    fig.tight_layout()
    fig.savefig(p, dpi=170, facecolor=SURFACE)
    plt.close(fig)
    print(f"  wrote {p}")


def _money(x, _):
    if x >= 1_000_000:
        return f"{x/1_000_000:.0f}M"
    if x >= 1000:
        return f"{x/1000:.0f}k"
    return f"{x:.0f}"


# ----------------------------------------------------------------------
def chart_cost_vs_aum(cap: dict) -> None:
    """The central evidence: the fee rate is not scale-invariant."""
    rows = cap["empirical"]["fixed_n"]
    x = [r["aum"] for r in rows]
    measured = [r["cost_rate_on_mean"] * 100 for r in rows]
    model = [r["predicted_cost_rate"] * 100 for r in rows]

    fig, ax = _fig()
    ax.plot(x, measured, color=HUES["low_volatility"], lw=2, marker="o", ms=6,
            label="measured in backtest", zorder=3)
    ax.plot(x, model, color=HUES["dividend"], lw=2, ls="--", marker="s", ms=6,
            label="closed form", zorder=2)

    a_min = cap["closed_form"]["lower"]["a_min"]
    if a_min:
        ax.axvline(a_min, color=ACCENT, lw=1.2, ls=":", zorder=1)
        ax.annotate(f"$A_{{min}}$ = CNY {a_min:,.0f}", xy=(a_min, max(measured)),
                    xytext=(6, -4), textcoords="offset points",
                    color=ACCENT, fontsize=9, va="top")

    ax.annotate(f"{measured[0]:.2f}%", xy=(x[0], measured[0]),
                xytext=(6, 6), textcoords="offset points",
                color=INK, fontsize=9, fontweight="bold")
    ax.annotate(f"{measured[-1]:.2f}%", xy=(x[-1], measured[-1]),
                xytext=(-4, 10), textcoords="offset points",
                color=INK, fontsize=9, fontweight="bold", ha="right")

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_money))
    _style(ax, "A five-yuan minimum makes trading cost depend on account size",
           "account size (CNY, log scale)", "annual fees, % of mean account value")
    leg = ax.legend(frameon=False, fontsize=9, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK_SOFT)
    _save(fig, "fig1_cost_vs_aum.png")


def chart_optimal_n(cap: dict) -> None:
    o = cap["optimal_n"]
    x = [r["aum"] for r in o]
    y = [r["best_n"] for r in o]
    fig, ax = _fig(8.2, 4.2)
    ax.plot(x, y, color=HUES["composite"], lw=2, marker="o", ms=6, zorder=3)
    for aum in (2000, 100000):
        m = [r for r in o if r["aum"] == aum]
        if m:
            ax.annotate(f"N* = {m[0]['best_n']}", xy=(aum, m[0]["best_n"]),
                        xytext=(8, -2), textcoords="offset points",
                        color=INK, fontsize=9, fontweight="bold")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_money))
    _style(ax, "How many names you can afford to hold is set by the fee floor",
           "account size (CNY, log scale)", "positions maximising net Sharpe")
    _save(fig, "fig2_optimal_n.png")


def chart_ic_decay(fe: dict) -> None:
    """Marginal IC -- quarter h on its own. This is the curve that decays."""
    fig, ax = _fig()
    drawn = []
    for k in ORDER:
        rec = fe["factors"].get(k)
        if not rec:
            continue
        m = rec.get("marginal_ic_by_quarter")
        if not m:
            continue
        hs = list(range(1, len(m) + 1))
        ys = [None if v is None else v for v in m]
        ax.plot(hs, ys, color=HUES[k], lw=2, marker="o", ms=6,
                label=LABEL[k], zorder=3)
        drawn.append(k)
    # Five series: the legend carries identity. Direct labels are reserved for
    # four or fewer, past which they crowd the right margin and stop helping.
    if len(drawn) <= 4:
        for k in drawn:
            m = fe["factors"][k]["marginal_ic_by_quarter"]
            ax.annotate(LABEL[k], xy=(len(m), m[-1]), xytext=(7, -3),
                        textcoords="offset points", color=HUES[k], fontsize=9)
    ax.axhline(0, color=INK_SOFT, lw=0.8, zorder=1)
    ax.set_xlim(0.8, 6.3)
    _style(ax, "The signal decays slowly: half still there after six quarters",
           "quarters after the rebalance (that quarter alone)", "mean Rank IC")
    leg = ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    for t in leg.get_texts():
        t.set_color(INK_SOFT)
    _save(fig, "fig3_ic_decay.png")


def chart_deciles(fe: dict) -> None:
    """Sequential ramp: the bars are ordered by factor score, so magnitude."""
    rec = fe["buckets"]["10"]["low_volatility"]
    means = [v * 100 for v in rec["bucket_mean_returns"]]
    n = len(means)
    ramp = ["#dbe3fb", "#c2cdf7", "#a9b8f2", "#90a2ee", "#778ce9",
            "#5e76e4", "#4a63dd", "#3b5bdb", "#3049b0", "#243786"]
    fig, ax = _fig(8.2, 4.4)
    bars = ax.bar(range(1, n + 1), means, color=ramp[:n], width=0.72,
                  edgecolor=SURFACE, linewidth=2, zorder=3)
    for i in (0, n - 1):
        ax.annotate(f"{means[i]:+.2f}%", xy=(i + 1, means[i]),
                    xytext=(0, 4 if means[i] >= 0 else -14),
                    textcoords="offset points", ha="center",
                    color=INK, fontsize=9, fontweight="bold")
    ax.axhline(0, color=INK_SOFT, lw=0.8, zorder=4)
    ax.set_xticks(range(1, n + 1))
    _style(ax, "Low-volatility deciles: the bottom decile is the whole story",
           "decile by low-volatility score (1 = most volatile)",
           "mean return per quarter (%)")
    _save(fig, "fig4_low_vol_deciles.png")


def main() -> int:
    os.makedirs(RESULTS, exist_ok=True)
    cap_p = os.path.join(RESULTS, "capacity.json")
    fe_p = os.path.join(RESULTS, "factor_eval.json")
    made = 0
    if os.path.exists(cap_p):
        cap = json.load(open(cap_p, encoding="utf-8"))
        chart_cost_vs_aum(cap); chart_optimal_n(cap); made += 2
    else:
        print(f"  (skipped capacity figures: {cap_p} not found)")
    if os.path.exists(fe_p):
        fe = json.load(open(fe_p, encoding="utf-8"))
        chart_ic_decay(fe); chart_deciles(fe); made += 2
    else:
        print(f"  (skipped factor figures: {fe_p} not found)")
    print(f"  {made} figure(s) written from JSON alone -- no database touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
