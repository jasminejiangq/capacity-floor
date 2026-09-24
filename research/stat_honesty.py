# -*- coding: utf-8 -*-
"""
stat_honesty.py -- What is left of the result after multiple testing.

Run:  python research/stat_honesty.py [--pbo] [--boot 1000]

The premise
-----------
A backtest Sharpe ratio is a maximum, not an estimate.  It is the best of
however many configurations were tried, and the more that were tried the
higher the best one is under the null of zero skill.  Reporting the raw
Sharpe without saying how many configurations produced it is not a minor
omission; Harvey, Liu & Zhu (RFS 2016) argue it is why most of the
published cross-sectional asset pricing literature does not replicate.

This script does four things:

  1. Reads research/trials.json, the registry of every configuration this
     project ran.  The count is the input to everything below.
  2. Converts the backtest Sharpe into a t-statistic and applies the
     Harvey & Liu (JPM 2015) haircut at two scales: this project's own
     trial count, and a literature-scale test count.
  3. Computes the Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014),
     which additionally corrects for the non-normality of the return
     distribution.
  4. Optionally estimates the Probability of Backtest Overfitting by
     sweeping factor weights and holding counts and running CSCV on the
     resulting panel.  PBO answers a question the Sharpe cannot: if I pick
     the best configuration in sample, how often is it below median out of
     sample?

The expected outcome for an honest retail strategy is that very little
survives.  That is the finding, not a failure of the finding.
"""

from __future__ import annotations

import argparse
import itertools
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

from stats_tools import (                       # noqa: E402
    deflated_sharpe, haircut_sharpe, newey_west_t, pbo_cscv,
)

RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(ROOT, "data", "cache")
OUTPUT = os.path.join(ROOT, "output")
os.makedirs(RESULTS, exist_ok=True)


def say(m=""):
    print(m, flush=True)


def load_backtest() -> dict:
    p = os.path.join(OUTPUT, "回测结果.json")
    if not os.path.exists(p):
        raise SystemExit(
            f"missing {p}\nRun 04_backtest.bat first -- this script grades "
            f"that backtest, it does not produce one.")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def daily_moments() -> dict:
    """Skewness and NON-EXCESS kurtosis of the daily strategy return.

    The Deflated Sharpe Ratio needs both.  scipy.stats.kurtosis returns
    EXCESS kurtosis by default (0.0 for a normal); passing that in place of
    non-excess kurtosis understates the correction and inflates the DSR.
    """
    p = os.path.join(OUTPUT, "净值曲线.csv")
    if not os.path.exists(p):
        return {}
    df = pd.read_csv(p, index_col=0, encoding="utf-8-sig")
    col = "策略" if "策略" in df.columns else df.columns[0]
    r = pd.to_numeric(df[col], errors="coerce").pct_change().dropna()
    if len(r) < 100:
        return {}
    try:
        from scipy import stats as st
        skew = float(st.skew(r))
        kurt = float(st.kurtosis(r, fisher=False))      # NON-excess
    except Exception:
        m = r.mean()
        sd = r.std(ddof=0)
        skew = float(((r - m) ** 3).mean() / sd ** 3)
        kurt = float(((r - m) ** 4).mean() / sd ** 4)   # NON-excess
    return {"n_days": int(len(r)), "daily_skew": skew,
            "daily_kurtosis_nonexcess": kurt,
            "daily_mean": float(r.mean()), "daily_std": float(r.std(ddof=1))}


def run_pbo(boot_configs: bool, say=say) -> dict:
    """Sweep configurations and run CSCV.

    Configurations are formed from the cached signal panel, so no full
    backtest is re-run: each configuration is "hold the top-N names by a
    weighted composite, equal weighted, rebalanced on schedule".  That is
    a deliberate simplification -- it strips out costs and caps -- but it
    is the right object for PBO, which asks whether SELECTING a
    configuration generalises, not whether any of them is profitable.
    """
    import engine as E
    import settings
    from signals import build_panel, weighted_score, top_n_return

    cfg = settings.读配置()
    E.应用配置(cfg)
    freq = cfg.get("调仓", {}).get("调仓频率", "季")
    say("  loading database for the configuration sweep ...")
    D = E.数据(说=lambda m: say("   " + m))
    cal = [d for d in E.调仓日历(D.交易日, freq) if d in D.交易日]
    panel = build_panel(D, cal, horizons=1, cache_dir=CACHE, say=say)
    dates = panel["dates"]
    fwd1 = panel["fwd"][1]

    weight_grid = [
        {"质量": 1, "红利": 1, "低波": 1, "估值": 1},
        {"质量": 2, "红利": 1, "低波": 1, "估值": 1},
        {"质量": 1, "红利": 2, "低波": 1, "估值": 1},
        {"质量": 1, "红利": 1, "低波": 2, "估值": 1},
        {"质量": 1, "红利": 1, "低波": 1, "估值": 2},
        {"质量": 1, "红利": 1, "低波": 0, "估值": 0},
        {"质量": 0, "红利": 1, "低波": 1, "估值": 0},
        {"质量": 1, "红利": 0, "低波": 1, "估值": 1},
    ]
    n_grid = [5, 10, 15, 25]
    configs = list(itertools.product(range(len(weight_grid)), n_grid))

    rows = []
    for d in dates[:-1]:
        if d not in fwd1:
            continue
        r = fwd1[d]
        row = []
        for wi, n in configs:
            s = weighted_score(panel, d, weight_grid[wi])
            row.append(top_n_return(s, r, n))
        rows.append(row)
    P = np.array(rows, dtype=float)
    say(f"  configuration panel: {P.shape[0]} periods x {P.shape[1]} configs")

    res = pbo_cscv(P, n_splits=12)
    res["configurations"] = [
        {"weights": weight_grid[wi], "n_holdings": n} for wi, n in configs]
    # in-sample best vs its own full-sample performance, for context
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(P, axis=0)
        sd = np.nanstd(P, axis=0, ddof=1)
    sr = np.where(sd > 0, mean / sd, 0.0)
    best = int(np.nanargmax(sr))
    res["best_config_full_sample"] = {
        "index": best,
        "weights": weight_grid[configs[best][0]],
        "n_holdings": configs[best][1],
        "mean_per_period": float(mean[best]),
        "spread_over_worst": float(mean[best] - np.nanmin(mean)),
    }
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbo", action="store_true",
                    help="also run the configuration sweep and CSCV "
                         "(needs the database; a few minutes)")
    args = ap.parse_args()

    t0 = time.time()
    say("=" * 70)
    say("  STATISTICAL HONESTY -- what survives multiple testing")
    say("=" * 70)

    with open(os.path.join(HERE, "trials.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    k_own = len(reg["trials"])
    k_lit = int(reg.get("literature_scale_tests", 316))

    bt = load_backtest()
    full = bt["全程"]
    oos = bt.get("样本外", {})
    years = float(full["年数"])
    sharpe_ann = float(full["夏普"])
    cagr = float(full["年化"])
    bench = float(full.get("基准年化", 0.0) or 0.0)

    mom = daily_moments()

    say(f"\n  sample            {full['起']} .. {full['止']}  ({years:.2f} years)")
    say(f"  strategy CAGR     {cagr*100:6.2f}%")
    say(f"  benchmark CAGR    {bench*100:6.2f}%")
    say(f"  annual Sharpe     {sharpe_ann:6.3f}")
    say(f"  max drawdown      {float(full['最大回撤'])*100:6.2f}%")
    say(f"  configurations this project ran: {k_own}")

    # --- t-statistic of the Sharpe ---------------------------------
    # For an annualised Sharpe measured over T years, t ~= SR * sqrt(T).
    t_obs = sharpe_ann * np.sqrt(years)
    say(f"\n  implied t-statistic of the Sharpe:  t = SR * sqrt(years) "
        f"= {sharpe_ann:.3f} * sqrt({years:.2f}) = {t_obs:.2f}")
    say(f"  conventional bar              t > 2.0   ->  "
        f"{'PASS' if t_obs > 2 else 'FAIL'}")
    say(f"  Harvey-Liu-Zhu (2016) bar     t > 3.0   ->  "
        f"{'PASS' if t_obs > 3 else 'FAIL'}")
    sr_needed_2 = 2.0 / np.sqrt(years)
    sr_needed_3 = 3.0 / np.sqrt(years)
    say(f"  Sharpe needed for t>2 over {years:.1f}y: {sr_needed_2:.3f}")
    say(f"  Sharpe needed for t>3 over {years:.1f}y: {sr_needed_3:.3f}")

    # --- haircuts ---------------------------------------------------
    hc_own = haircut_sharpe(t_obs, k_own, years)
    hc_lit = haircut_sharpe(t_obs, k_lit, years)
    say(f"\n  Harvey-Liu haircut (Bonferroni)")
    say(f"    vs this project's {k_own:>3d} trials : "
        f"t_adj {hc_own['t_adjusted']:.2f}, "
        f"{hc_own['haircut']*100:.0f}% of the Sharpe removed, "
        f"haircut Sharpe {sharpe_ann*hc_own['surviving_fraction']:.3f}")
    say(f"    vs literature-scale {k_lit:>3d}   : "
        f"t_adj {hc_lit['t_adjusted']:.2f}, "
        f"{hc_lit['haircut']*100:.0f}% removed, "
        f"haircut Sharpe {sharpe_ann*hc_lit['surviving_fraction']:.3f}")

    # --- deflated Sharpe -------------------------------------------
    # DSR works in the periodicity of the observations, so de-annualise.
    n_obs = mom.get("n_days", int(years * 252))
    sr_daily = sharpe_ann / np.sqrt(252)
    dsr_own = deflated_sharpe(
        sr_daily, n_obs, k_own,
        skew=mom.get("daily_skew", 0.0),
        kurt=mom.get("daily_kurtosis_nonexcess", 3.0))
    dsr_lit = deflated_sharpe(
        sr_daily, n_obs, k_lit,
        skew=mom.get("daily_skew", 0.0),
        kurt=mom.get("daily_kurtosis_nonexcess", 3.0))
    say(f"\n  Deflated Sharpe Ratio  (daily SR {sr_daily:.4f}, "
        f"n={n_obs}, skew {mom.get('daily_skew', float('nan')):.2f}, "
        f"kurtosis {mom.get('daily_kurtosis_nonexcess', float('nan')):.1f})")
    say(f"    vs {k_own} trials       DSR = {dsr_own['dsr']:.4f}")
    say(f"    vs {k_lit} trials      DSR = {dsr_lit['dsr']:.4f}")
    say(f"    (DSR is the probability the true Sharpe exceeds the best you "
        f"would expect from luck alone)")

    # --- out of sample ----------------------------------------------
    say("\n  Declared out-of-sample window")
    if oos:
        o_cagr = float(oos["年化"])
        o_bench = float(oos.get("基准年化", 0.0) or 0.0)
        say(f"    {oos['起']} .. {oos['止']} ({float(oos['年数']):.1f} years)")
        say(f"    strategy  {o_cagr*100:6.2f}%   benchmark {o_bench*100:6.2f}%"
            f"   excess {(o_cagr-o_bench)*100:+6.2f}pp")
        say(f"    in-sample excess was {(cagr-bench)*100:+.2f}pp")
        say(f"    decay: {((o_cagr-o_bench)-(cagr-bench))*100:+.2f}pp")
    else:
        say("    (not present in the backtest output)")

    luck = bt.get("运气分布")
    if luck:
        say("\n  Luck decomposition (same rules, random picks from the same "
            "eligible pool)")
        dist = luck["分布"]
        say("    random CAGR percentiles: " +
            "  ".join(f"{k}={float(v)*100:.2f}%" for k, v in dist.items()))
        say(f"    actual CAGR sits at the {float(luck['实际分位'])*100:.0f}th "
            f"percentile of {luck['样本数']} random draws")
        say("    -> the RANKING carries information; whether that information "
            "survives costs is a separate question, answered in capacity.py")

    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample_years": years,
        "sharpe_annual": sharpe_ann,
        "t_statistic": float(t_obs),
        "passes_t2": bool(t_obs > 2),
        "passes_t3_hlz": bool(t_obs > 3),
        "sharpe_needed_for_t2": float(sr_needed_2),
        "sharpe_needed_for_t3": float(sr_needed_3),
        "n_trials_own": k_own,
        "n_trials_literature_scale": k_lit,
        "haircut_own": hc_own,
        "haircut_literature": hc_lit,
        "daily_moments": mom,
        "deflated_sharpe_own": dsr_own,
        "deflated_sharpe_literature": dsr_lit,
        "in_sample_excess": float(cagr - bench),
        "out_of_sample": oos,
        "luck": luck,
        "oos_freeze": reg.get("oos_freeze"),
        "trials": reg["trials"],
    }

    if args.pbo:
        say("\n  Probability of Backtest Overfitting (CSCV)")
        try:
            res = run_pbo(True)
            out["pbo"] = res
            say(f"    PBO = {res['pbo']:.3f} over {res['n_partitions']} "
                f"partitions of {res['n_configs']} configurations")
            say(f"    median logit = {res['median_logit']:.3f} "
                f"(<=0 means the in-sample winner is a coin flip out of sample)")
        except Exception as e:
            say(f"    (skipped: {type(e).__name__}: {e})")

    path = os.path.join(RESULTS, "stat_honesty.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    say(f"\n  written: {path}")
    say("=" * 70)
    say(f"  done in {time.time()-t0:.0f}s")
    say("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
