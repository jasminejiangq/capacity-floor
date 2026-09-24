# -*- coding: utf-8 -*-
"""
signals.py -- Build (and cache) the point-in-time signal panel.

Computing cross-sectional factors for every rebalance date is the single
most expensive step in the research layer, and three different scripts
need exactly the same panel.  So it is built once and cached.

The cache key includes every parameter that can change the numbers.  If
you edit the universe filters in engine.py the key changes and the panel
is rebuilt -- a stale cache silently producing old numbers is the kind of
bug that survives all the way into a paper.

What the panel contains, per rebalance date:
    pool       tradable universe AFTER all screens
    parts      the four raw factor-group scores (pre-neutralisation blend)
    composite  the equal-weighted, industry- and size-neutralised score
    neutral    each factor group AFTER neutralisation, so alternative
               weightings can be formed without recomputing anything
    fwd[h]     forward simple return to the h-th following rebalance date
"""

from __future__ import annotations

import hashlib
import os
import pickle
import time

import numpy as np
import pandas as pd

import engine as E

FACTORS = ["质量", "红利", "低波", "估值"]


def _key(cal, horizons: int) -> str:
    parts = [
        str(len(cal)), str(cal[0]), str(cal[-1]), str(horizons),
        str(E.最少上市天数), str(E.市值剔除分位), str(E.流动性剔除分位),
        str(E.估值剔除分位), str(E.剔除ST), str(E.波动率门槛分位),
        str(sorted(E.门槛开关.items())),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def forward_returns(D, d0: str, d1: str) -> pd.Series:
    """Simple return from d0 to d1 on back-adjusted closes (dividends in).

    A name that stops printing prices inside the window keeps its last
    valid observation rather than being dropped.  Dropping it would quietly
    reintroduce survivorship bias, which is the exact failure this project
    spends most of its effort avoiding.
    """
    close = D.收盘
    if d0 not in close.index or d1 not in close.index:
        return pd.Series(dtype=float)
    i0 = close.index.get_loc(d0)
    i1 = close.index.get_loc(d1)
    p0 = close.iloc[i0]
    p1 = close.iloc[i0:i1 + 1].ffill().iloc[-1]
    r = p1 / p0 - 1.0
    return r[np.isfinite(r) & np.isfinite(p0) & (p0 > 0)]


def build_panel(D, cal, horizons: int = 6, cache_dir: str | None = None,
                say=print, use_cache: bool = True) -> dict:
    key = _key(cal, horizons)
    path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"_panel_{key}.pkl")
        if use_cache and os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    panel = pickle.load(fh)
                say(f"  panel cache hit ({len(panel['dates'])} dates)  {path}")
                return panel
            except Exception:
                say("  (cache unreadable, rebuilding)")

    t0 = time.time()
    dates, pool, parts, neutral, composite = [], {}, {}, {}, {}
    for k, d in enumerate(cal):
        F = E.截面因子(D, d)
        if not len(F):
            continue
        p, _ = E.建股票池(F, D, d)
        if len(p) < 50:
            continue
        comp, raw = E.打分(F, p)
        f = F.loc[p]
        neu = pd.DataFrame(
            {c: E._中性化(raw[c], f["行业"], f["流通市值"]) for c in raw.columns})
        dates.append(d)
        pool[d] = p
        parts[d] = raw
        neutral[d] = neu
        composite[d] = comp
        if k % 10 == 0:
            say(f"    {k+1}/{len(cal)}  {d}  universe {len(p)}")

    fwd = {h: {} for h in range(1, horizons + 1)}
    for i, d in enumerate(dates):
        for h in range(1, horizons + 1):
            if i + h < len(dates):
                fwd[h][d] = forward_returns(D, d, dates[i + h])

    panel = {"key": key, "dates": dates, "pool": pool, "parts": parts,
             "neutral": neutral, "composite": composite, "fwd": fwd,
             "horizons": horizons,
             "built": time.strftime("%Y-%m-%d %H:%M:%S"),
             "seconds": round(time.time() - t0, 1)}
    say(f"  panel built: {len(dates)} dates in {panel['seconds']}s")
    if path:
        try:
            with open(path, "wb") as fh:
                pickle.dump(panel, fh, protocol=4)
            say(f"  panel cached: {path}")
        except Exception as e:
            say(f"  (cache write failed: {e})")
    return panel


def weighted_score(panel: dict, d: str, weights: dict) -> pd.Series:
    """Form a composite from the NEUTRALISED factor groups under arbitrary
    weights.  Used by the overfitting analysis to sweep configurations
    without recomputing any factor."""
    neu = panel["neutral"][d]
    w = pd.Series({c: float(weights.get(c, 0.0)) for c in neu.columns})
    if w.sum() <= 0:
        w = pd.Series(1.0, index=neu.columns)
    return (neu * w).sum(axis=1) / w.sum()


def top_n_return(score: pd.Series, fwd: pd.Series, n: int) -> float:
    """Equal-weighted forward return of the top-n names by score."""
    s = score.dropna()
    common = s.index.intersection(fwd.index)
    if len(common) < n:
        return float("nan")
    s = s.reindex(common).sort_values(ascending=False)
    picks = s.index[:n]
    return float(fwd.reindex(picks).mean())


__all__ = ["build_panel", "weighted_score", "top_n_return",
           "forward_returns", "FACTORS"]
