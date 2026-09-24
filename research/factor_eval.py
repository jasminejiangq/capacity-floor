# -*- coding: utf-8 -*-
"""
factor_eval.py -- Factor diagnostics: IC, Rank IC, ICIR, IC decay,
sorted-portfolio monotonicity, and a like-for-like comparison of the four
factor groups.

Run:  python research/factor_eval.py [--buckets 10] [--horizons 6]

Why this file exists
--------------------
A backtest equity curve answers one question: "did this specific portfolio
construction make money on this specific sample?"  It cannot tell you
whether the SIGNAL has information, because portfolio construction, the
position cap, the liquidity screen and the cost model are all entangled
with it.  Every quantitative research interview starts from the signal
side instead, and the first three questions are always some version of:

    What is the IC?  What is the ICIR?  How fast does it decay?

So this module evaluates the raw cross-sectional signal, separately from
any portfolio, on exactly the same point-in-time data the backtest uses.

Design decisions worth defending
--------------------------------
* Rank IC (Spearman) is the headline, not Pearson IC.  A-share
  cross-sectional returns have fat tails; Pearson IC in a given month can
  be driven by one limit-up name.
* IC is computed on the SAME universe the strategy can actually trade
  (after the size, liquidity and tradability screens).  Reporting IC on
  the full market, including names you would never buy, flatters the
  signal.
* Significance uses Newey-West.  Horizon-h ICs computed every rebalance
  overlap, so the naive t-stat is inflated.
* Buckets are reported at J=10 AND J=20.  Cattaneo, Crump, Farrell &
  Schaumburg (REStat 2020) show that the universal choice of J=10 is
  arbitrary and often statistically inefficient; a result that only exists
  at one J is not a result.
* Monotonicity is tested with Patton & Timmermann (2010), not eyeballed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "code"))
sys.path.insert(0, HERE)

import engine as E                        # noqa: E402
import settings                            # noqa: E402
from stats_tools import icir, newey_west_t, mr_test   # noqa: E402
from signals import build_panel                        # noqa: E402

RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "data", "cache")
os.makedirs(RESULTS, exist_ok=True)

FACTORS = ["质量", "红利", "低波", "估值"]
FACTOR_EN = {"质量": "quality", "红利": "dividend",
             "低波": "low_volatility", "估值": "value",
             "综合": "composite"}


def say(m=""):
    print(m, flush=True)


def bucket_returns(score: pd.Series, fwd: pd.Series, j: int):
    """Equal-weighted forward return of each of j buckets, low score first."""
    common = score.index.intersection(fwd.index)
    s = score.reindex(common).dropna()
    r = fwd.reindex(s.index)
    ok = np.isfinite(r)
    s, r = s[ok], r[ok]
    if len(s) < j * 5:
        return None
    q = pd.qcut(s.rank(method="first"), j, labels=False)
    return [float(r[q == b].mean()) for b in range(j)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buckets", type=int, nargs="*", default=[10, 20])
    ap.add_argument("--horizons", type=int, default=6,
                    help="IC decay measured out to this many rebalances")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    say("=" * 70)
    say("  FACTOR DIAGNOSTICS -- IC / ICIR / decay / monotonicity")
    say("=" * 70)

    cfg = settings.读配置()
    E.应用配置(cfg)
    freq = cfg.get("调仓", {}).get("调仓频率", "季")
    f_per_year = settings.每年调仓次数.get(freq, 4)

    say("\n  loading database ...")
    D = E.数据(说=lambda m: say("   " + m))
    cal = [d for d in E.调仓日历(D.交易日, freq) if d in D.交易日]
    say(f"  {len(cal)} rebalance dates ({freq}, {f_per_year}/yr)")

    # ---- pass 1+2: build (or reuse) the point-in-time signal panel ----
    say("\n  [1/3] point-in-time factor scores + forward returns")
    H = max(1, int(args.horizons))
    panel = build_panel(D, cal, horizons=H, cache_dir=CACHE,
                        say=say, use_cache=not args.no_cache)
    dates = panel["dates"]
    universe = panel["pool"]
    fwd = panel["fwd"]
    # Individual factors are evaluated AFTER industry/size neutralisation,
    # the same transform the composite uses.  Evaluating raw percentile
    # scores instead would credit the "low volatility" factor for what is
    # really a utilities-sector tilt.
    scores = {name: {d: panel["neutral"][d][name]
                     for d in dates if name in panel["neutral"][d].columns}
              for name in FACTORS}
    scores["\u7efc\u5408"] = {d: panel["composite"][d] for d in dates}
    say(f"        usable rebalance dates: {len(dates)}")
    if len(dates) < 12:
        say("  ! too few usable dates; aborting")
        return 1

    # ---- IC / Rank IC / ICIR / decay ---------------------------------
    say("\n  [2/3] information coefficients")
    out: dict = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rebalance_freq": freq,
        "rebalances_per_year": f_per_year,
        "sample": {"start": dates[0], "end": dates[-1],
                   "n_dates": len(dates),
                   "years": round(len(dates) / f_per_year, 2),
                   "median_universe": float(np.median(
                       [len(universe[d]) for d in dates]))},
        "factors": {},
    }

    say(f"\n  {'factor':16s} {'RankIC':>8s} {'ICIR_ann':>9s} "
        f"{'t_NW':>7s} {'HLZ bar':>8s} {'hit%':>6s}")
    say("  " + "-" * 60)

    for name in FACTORS + ["综合"]:
        rec: dict = {"name_en": FACTOR_EN[name]}
        for h in range(1, H + 1):
            rank_ic, pear_ic = [], []
            for d in dates:
                s = scores[name].get(d)
                r = fwd[h].get(d)
                if s is None or r is None or not len(r):
                    continue
                common = s.dropna().index.intersection(r.index)
                if len(common) < 30:
                    continue
                a, b = s.reindex(common), r.reindex(common)
                rank_ic.append(float(a.corr(b, method="spearman")))
                pear_ic.append(float(a.corr(b, method="pearson")))
            if len(rank_ic) < 8:
                continue
            arr = np.array(rank_ic, dtype=float)
            st = icir(arr, f_per_year)
            # horizon-h ICs overlap by h-1 periods -> tell Newey-West
            nw = newey_west_t(arr, lags=max(h - 1, 0) or None)
            rec[f"h{h}"] = {
                "rank_ic_mean": st["ic_mean"],
                "pearson_ic_mean": float(np.nanmean(pear_ic)),
                "ic_std": st["ic_std"],
                "icir_annual": st["icir_annual"],
                "t_naive": st["t_naive"],
                "t_newey_west": nw["t"],
                "nw_lags": nw["lags"],
                "hlz_threshold_icir": st["hlz_threshold_icir"],
                "passes_hlz_t3": bool(abs(nw["t"]) > 3.0),
                "hit_rate": float((arr > 0).mean()),
                "n_periods": int(arr.size),
                "ic_series": [round(float(x), 4) for x in arr],
            }
        if "h1" in rec:
            a = rec["h1"]
            say(f"  {FACTOR_EN[name]:16s} {a['rank_ic_mean']:8.4f} "
                f"{a['icir_annual']:9.3f} {a['t_newey_west']:7.2f} "
                f"{a['hlz_threshold_icir']:8.3f} {a['hit_rate']*100:5.1f}%")
        out["factors"][FACTOR_EN[name]] = rec

    # ---- pass 4: bucket portfolios + monotonicity ---------------------
    say("\n  [3/3] sorted-portfolio monotonicity")
    out["buckets"] = {}
    for j in args.buckets:
        out["buckets"][str(j)] = {}
        say(f"\n  --- J = {j} buckets ---")
        for name in FACTORS + ["综合"]:
            panel = []
            for i, d in enumerate(dates[:-1]):
                s = scores[name].get(d)
                r = fwd[1].get(d)
                if s is None or r is None or not len(r):
                    continue
                br = bucket_returns(s, r, j)
                if br is not None and all(np.isfinite(br)):
                    panel.append(br)
            if len(panel) < 12:
                continue
            P = np.array(panel, dtype=float)
            mr = mr_test(P, n_boot=args.boot)
            spread = P[:, -1] - P[:, 0]
            nw = newey_west_t(spread)
            ann = (1 + spread.mean()) ** f_per_year - 1
            out["buckets"][str(j)][FACTOR_EN[name]] = {
                "bucket_mean_returns": mr.get("bucket_means"),
                "top_minus_bottom_per_period": float(spread.mean()),
                "top_minus_bottom_annualised": float(ann),
                "spread_t_newey_west": nw["t"],
                "mr_test_p_value": mr.get("p_value"),
                "monotone_in_sample": mr.get("monotone_in_sample"),
                "n_steps_wrong_way": mr.get("n_steps_wrong_way"),
                "monotonic": mr.get("monotonic"),
                "verdict": mr.get("verdict"),
                "n_periods": int(P.shape[0]),
            }
            say(f"  {FACTOR_EN[name]:16s} spread/period {spread.mean()*100:6.2f}% "
                f"ann {ann*100:6.2f}%  t={nw['t']:5.2f}  "
                f"MR p={mr.get('p_value'):.3f}  "
                f"wrong-way {mr.get('n_steps_wrong_way')}/{j-1}  "
                f"-> {mr.get('verdict')}")

    path = os.path.join(RESULTS, "factor_eval.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    say(f"\n  written: {path}")

    try:
        _plot(out)
        say(f"  written: {os.path.join(RESULTS, 'factor_eval.png')}")
    except Exception as e:                                 # pragma: no cover
        say(f"  (chart skipped: {e})")

    say("=" * 70)
    say(f"  done in {time.time()-t0:.0f}s")
    say("=" * 70)
    return 0


def _plot(out: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))

    ax = axes[0]
    for en, rec in out.get("factors", {}).items():
        hs, ys = [], []
        for k, v in rec.items():
            if k.startswith("h") and isinstance(v, dict):
                hs.append(int(k[1:]))
                ys.append(v["rank_ic_mean"])
        if hs:
            order = np.argsort(hs)
            ax.plot(np.array(hs)[order], np.array(ys)[order],
                    marker="o", label=en)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("horizon (rebalance periods ahead)")
    ax.set_ylabel("mean Rank IC")
    ax.set_title("IC decay")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1]
    b = out.get("buckets", {}).get("10", {})
    for en, rec in b.items():
        m = rec.get("bucket_mean_returns")
        if m:
            ax.plot(range(1, len(m) + 1), [x * 100 for x in m],
                    marker="o", label=en)
    ax.set_xlabel("bucket (1 = lowest score)")
    ax.set_ylabel("mean forward return per rebalance (%)")
    ax.set_title("Decile monotonicity")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "factor_eval.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
