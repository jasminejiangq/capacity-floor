"""
stats_tools.py -- Small, dependency-light statistics used across the
research layer.  Pure functions, no I/O, fully unit-tested.

Contents
  newey_west_t   heteroskedasticity- and autocorrelation-robust t-stat
  icir           information-coefficient information ratio, annualised
  deflated_sharpe  Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio
  haircut_sharpe   Harvey & Liu (JPM 2015) multiple-testing haircut
  mr_test        Patton & Timmermann (JFE 2010) monotonic-relationship test
  pbo_cscv       Bailey et al. (2017) Probability of Backtest Overfitting
"""

from __future__ import annotations

import math
import numpy as np

try:
    from scipy import stats as _st
except Exception:                                   # pragma: no cover
    _st = None


# ----------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(q: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, ~1e-9 accurate).
    Implemented locally so the module works without scipy."""
    if _st is not None:
        return float(_st.norm.ppf(q))
    if q <= 0.0:
        return -np.inf
    if q >= 1.0:
        return np.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if q < plow:
        r = math.sqrt(-2 * math.log(q))
        return (((((c[0]*r+c[1])*r+c[2])*r+c[3])*r+c[4])*r+c[5]) / \
               ((((d[0]*r+d[1])*r+d[2])*r+d[3])*r+1)
    if q > phigh:
        r = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0]*r+c[1])*r+c[2])*r+c[3])*r+c[4])*r+c[5]) / \
                ((((d[0]*r+d[1])*r+d[2])*r+d[3])*r+1)
    r = q - 0.5
    s = r * r
    return (((((a[0]*s+a[1])*s+a[2])*s+a[3])*s+a[4])*s+a[5])*r / \
           (((((b[0]*s+b[1])*s+b[2])*s+b[3])*s+b[4])*s+1)


# ----------------------------------------------------------------------
def newey_west_t(x, lags: int | None = None) -> dict:
    """t-statistic for mean(x) != 0, robust to serial correlation.

    Why it matters here: when factor returns are measured over OVERLAPPING
    horizons (horizon-h IC computed every rebalance), the series is
    mechanically autocorrelated and the naive t-stat is inflated -- often
    by a factor of sqrt(h).  Reporting a naive t on overlapping data is one
    of the most common errors in factor write-ups.

    lags defaults to the Newey-West (1994) plug-in rule
    floor(4*(T/100)^(2/9)).
    """
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    T = a.size
    if T < 3:
        return {"mean": float("nan"), "t": float("nan"), "se": float("nan"),
                "n": T, "lags": 0}
    if lags is None:
        lags = int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(int(lags), T - 2))

    e = a - a.mean()
    gamma0 = float(e @ e) / T
    var = gamma0
    for j in range(1, lags + 1):
        gj = float(e[j:] @ e[:-j]) / T
        var += 2.0 * (1.0 - j / (lags + 1.0)) * gj
    var = max(var, 1e-300)
    se = math.sqrt(var / T)
    t = a.mean() / se if se > 0 else float("nan")
    return {"mean": float(a.mean()), "t": float(t), "se": float(se),
            "n": int(T), "lags": int(lags)}


def icir(ic_series, periods_per_year: float) -> dict:
    """ICIR = mean(IC) / std(IC), annualised by sqrt(periods per year).

    The commonly quoted acceptance bar of ICIR > 0.5 has no statistical
    content.  A defensible bar follows from Harvey, Liu & Zhu (RFS 2016):
    with the number of factors that have been tested in the literature, a
    t-statistic of 3.0 -- not 2.0 -- is the right hurdle.  Since
        t  ~=  ICIR_annual * sqrt(years)
    that translates into
        ICIR_annual  >  3.0 / sqrt(years)
    which for a 15-year sample is 0.77, and for a 3-year sample is 1.73.
    A 3-year backtest showing ICIR 0.6 has not cleared anything.
    """
    a = np.asarray(ic_series, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 3 or a.std(ddof=1) == 0:
        return {"ic_mean": float("nan"), "icir_annual": float("nan"),
                "n": int(a.size)}
    raw = a.mean() / a.std(ddof=1)
    ann = raw * math.sqrt(periods_per_year)
    years = a.size / periods_per_year
    nw = newey_west_t(a)
    return {
        "ic_mean": float(a.mean()),
        "ic_std": float(a.std(ddof=1)),
        "icir_per_period": float(raw),
        "icir_annual": float(ann),
        "years": float(years),
        "t_naive": float(raw * math.sqrt(a.size)),
        "t_newey_west": nw["t"],
        "hlz_threshold_icir": 3.0 / math.sqrt(years) if years > 0 else float("nan"),
        "passes_hlz": bool(abs(nw["t"]) > 3.0),
        "n": int(a.size),
    }


# ----------------------------------------------------------------------
def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int,
                    skew: float = 0.0, kurt: float = 3.0,
                    sharpe_variance: float | None = None) -> dict:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Answers: given that I tried n_trials configurations, what is the
    probability that the best observed Sharpe is genuinely above zero?

    The expected maximum Sharpe under the null of zero true skill is

        E[max SR] ~= sqrt(V) * [ (1-g)*Z(1 - 1/K) + g*Z(1 - 1/(K*e)) ]

    with g = Euler-Mascheroni, V the cross-trial variance of the trial
    Sharpes.  DSR is then the probability that the observed SR exceeds that
    benchmark, using the Mertens (2002) standard error which corrects for
    skewness and kurtosis of returns.

    IMPORTANT: `kurt` is NON-EXCESS kurtosis (3.0 for a normal).  Passing
    scipy's default excess kurtosis here silently inflates the result --
    use scipy.stats.kurtosis(x, fisher=False).
    """
    K = max(int(n_trials), 1)
    if sharpe_variance is None:
        # Conservative default: trial Sharpes vary with the sampling error
        # of a single Sharpe estimate.
        sharpe_variance = 1.0 / max(n_obs - 1, 1)
    v = math.sqrt(max(sharpe_variance, 1e-18))
    gamma = 0.5772156649015329
    if K == 1:
        sr0 = 0.0
    else:
        z1 = _norm_ppf(1.0 - 1.0 / K)
        z2 = _norm_ppf(1.0 - 1.0 / (K * math.e))
        sr0 = v * ((1.0 - gamma) * z1 + gamma * z2)

    denom = 1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe ** 2
    denom = max(denom, 1e-12)
    se = math.sqrt(denom / max(n_obs - 1, 1))
    z = (sharpe - sr0) / se if se > 0 else float("nan")
    return {
        "sharpe_observed": float(sharpe),
        "n_trials": K,
        "expected_max_sharpe_under_null": float(sr0),
        "dsr": float(_norm_cdf(z)) if np.isfinite(z) else float("nan"),
        "z": float(z),
        "note": "kurt must be NON-excess (3.0 = normal)",
    }


def haircut_sharpe(t_stat: float, n_tests: int, n_years: float,
                   method: str = "bonferroni") -> dict:
    """Harvey & Liu (JPM 2015) haircut: how much of a reported Sharpe
    survives a multiple-testing correction.

    Converts the observed t to a p-value, adjusts it for n_tests, converts
    back to an adjusted t, and rescales the Sharpe by the ratio.
    Bonferroni is the most conservative of the three adjustments they use;
    it is the right default when you cannot enumerate every trial anyone
    has run on the same data.
    """
    t = abs(float(t_stat))
    p = 2.0 * (1.0 - _norm_cdf(t))
    p = min(max(p, 1e-300), 1.0)
    if method == "bonferroni":
        p_adj = min(p * max(int(n_tests), 1), 1.0)
    else:
        raise ValueError("only bonferroni implemented")
    # invert back to a t-statistic
    t_adj = abs(_norm_ppf(1.0 - p_adj / 2.0)) if p_adj < 1.0 else 0.0
    ratio = t_adj / t if t > 0 else 0.0
    return {
        "t_observed": t, "p_observed": p,
        "n_tests": int(n_tests), "p_adjusted": p_adj,
        "t_adjusted": float(t_adj),
        "haircut": float(1.0 - ratio),
        "surviving_fraction": float(ratio),
        "years": float(n_years),
    }


# ----------------------------------------------------------------------
def mr_test(bucket_returns, n_boot: int = 1000, seed: int = 20260924) -> dict:
    """Patton & Timmermann (JFE 2010) monotonic-relationship test.

    bucket_returns: array (T x J), column j = period returns of bucket j,
                    ordered from lowest factor score to highest.

    Null hypothesis: the pattern is FLAT or weakly decreasing.
    Statistic:  J = min_i ( mu_{i+1} - mu_i )
    A large positive J means every adjacent step goes the right way.

    This is the honest version of "the decile spread is positive".  A
    top-minus-bottom spread can be positive while six of the nine interior
    steps go the wrong way, which is what a spurious factor looks like.
    p-value by stationary block bootstrap on the de-meaned panel.
    """
    X = np.asarray(bucket_returns, dtype=float)
    if X.ndim != 2 or X.shape[1] < 2:
        return {"error": "need a T x J panel with J >= 2"}
    X = X[np.isfinite(X).all(axis=1)]
    T, J = X.shape
    if T < 10:
        return {"error": f"only {T} usable periods"}

    mu = X.mean(axis=0)
    diffs = np.diff(mu)
    stat = float(diffs.min())

    rng = np.random.default_rng(seed)
    Xc = X - mu                      # impose the null: all means equal
    block = max(1, int(round(T ** (1 / 3))))
    count = 0
    for _ in range(n_boot):
        idx = []
        while len(idx) < T:
            s = rng.integers(0, T)
            idx.extend(((s + np.arange(block)) % T).tolist())
        b = Xc[np.array(idx[:T])]
        d = np.diff(b.mean(axis=0))
        if d.min() >= stat:
            count += 1
    p_value = float((count + 1) / (n_boot + 1))
    monotone = bool((diffs > 0).all())

    # Guard against an incoherent verdict. The bootstrap is run under the
    # least-favourable null (every bucket mean equal), so the null
    # distribution of min-diff sits well below zero when J is large and T
    # is small. A slightly negative observed min-diff can then sit in the
    # upper tail of that distribution and produce p < 0.05 -- on a sample
    # whose pattern is not monotone at all. Patton & Timmermann reject for
    # LARGE positive J; a non-positive J means the sample does not even
    # exhibit the pattern being tested, so no conclusion of monotonicity
    # can be drawn regardless of the p-value. Both numbers are reported;
    # only the combination is a verdict.
    return {
        "bucket_means": [float(x) for x in mu],
        "adjacent_diffs": [float(x) for x in diffs],
        "statistic_min_diff": stat,
        "p_value": p_value,
        "n_periods": int(T), "n_buckets": int(J),
        "block_size": int(block), "n_boot": int(n_boot),
        "monotone_in_sample": monotone,
        "n_steps_wrong_way": int((diffs <= 0).sum()),
        "monotonic": bool(monotone and p_value < 0.05),
        "verdict": ("monotone" if (monotone and p_value < 0.05) else
                    "not monotone in sample" if not monotone else
                    "monotone in sample but not significant"),
    }


# ----------------------------------------------------------------------
def pbo_cscv(perf_matrix, n_splits: int = 16, seed: int = 20260924) -> dict:
    """Probability of Backtest Overfitting via Combinatorially Symmetric
    Cross-Validation (Bailey, Borwein, Lopez de Prado & Zhu, 2017).

    perf_matrix: array (T x M), column m = per-period performance of
                 configuration m.  M must be >= 2.

    Split the timeline into S blocks, take every balanced in-sample /
    out-of-sample partition, pick the configuration that wins in sample,
    and record its OUT-of-sample rank.  PBO is the frequency with which
    the in-sample winner lands in the bottom half out of sample.

    PBO near 0.5 means the selection procedure has no skill: choosing the
    best backtest is a coin flip out of sample.  This is the number that
    should accompany any "we picked the best parameters" claim.
    """
    from itertools import combinations

    X = np.asarray(perf_matrix, dtype=float)
    if X.ndim != 2 or X.shape[1] < 2:
        return {"error": "need a T x M panel with M >= 2"}
    X = X[np.isfinite(X).all(axis=1)]
    T, M = X.shape
    S = int(n_splits)
    if S % 2:
        S += 1
    if T < S * 2:
        S = max(2, (T // 2) * 2 // 1)
        S = min(S, 16)
        if S % 2:
            S -= 1
    if S < 2:
        return {"error": f"only {T} periods, cannot split"}

    blocks = np.array_split(np.arange(T), S)
    half = S // 2
    combos = list(combinations(range(S), half))
    rng = np.random.default_rng(seed)
    if len(combos) > 2000:
        pick = rng.choice(len(combos), 2000, replace=False)
        combos = [combos[i] for i in pick]

    def sharpe(a):
        sd = a.std(ddof=1)
        return a.mean() / sd if sd > 0 else 0.0

    logits, below = [], 0
    for cmb in combos:
        is_idx = np.concatenate([blocks[i] for i in cmb])
        oos_idx = np.concatenate([blocks[i] for i in range(S) if i not in cmb])
        is_perf = np.array([sharpe(X[is_idx, m]) for m in range(M)])
        oos_perf = np.array([sharpe(X[oos_idx, m]) for m in range(M)])
        star = int(np.argmax(is_perf))
        # relative rank of the in-sample winner out of sample, in (0,1)
        rank = (np.sum(oos_perf <= oos_perf[star])) / (M + 1.0)
        rank = min(max(rank, 1.0 / (M + 1.0)), M / (M + 1.0))
        if rank < 0.5:
            below += 1
        logits.append(math.log(rank / (1.0 - rank)))

    return {
        "pbo": float(below / len(combos)),
        "median_logit": float(np.median(logits)),
        "n_partitions": len(combos),
        "n_configs": int(M),
        "n_splits": int(S),
        "n_periods": int(T),
    }


__all__ = ["newey_west_t", "icir", "deflated_sharpe", "haircut_sharpe",
           "mr_test", "pbo_cscv"]
