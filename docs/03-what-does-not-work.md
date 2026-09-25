# 3. The gap between the signal and the portfolio

This chapter exists because the alternative — quietly reporting the in-sample
equity curve and moving on — is the most common failure in retail quantitative
work and the easiest for a reader to catch.

The summary is two numbers that look contradictory and are not:

| | measured | t |
|---|---|---|
| low-volatility signal, Rank IC, 64 quarters | 0.0886 | **6.61** |
| portfolio built on the composite, Sharpe, 15.6 years | 0.348 | **1.38** |

The signal clears the Harvey–Liu–Zhu bar by a factor of two. The portfolio fails
the conventional bar. Chapter 5 establishes the first number; this chapter
establishes the second; chapter 2 explains the distance.

## 3.1 The portfolio numbers

Full sample, 2011-01-31 to 2026-09-15 (15.62 years), quarterly rebalance, all
costs on:

| | strategy | CSI 300 |
|---|---|---|
| CAGR | 4.67% | 2.44% |
| max drawdown | −47.6% | −46.7% |
| annual Sharpe | 0.348 | — |
| rolling 3-year win rate vs benchmark | 49.2% | — |

Declared out-of-sample window, 2023-09-15 to 2026-09-15, frozen before it was
evaluated:

| | strategy | CSI 300 |
|---|---|---|
| CAGR | 3.17% | 6.50% |
| excess | **−3.33pp** | — |
| rolling 3-year win rate | **0%** | — |

In-sample excess was +2.23pp a year. Out of sample it is −3.33pp.

## 3.2 The Sharpe is not distinguishable from zero

For an annualised Sharpe `SR` measured over `T` years, `t ≈ SR · √T`:

```
t = 0.348 · √15.62 = 1.38
```

* Conventional bar, `t > 2` — **fails**.
* Harvey, Liu & Zhu (*RFS* 2016) bar, `t > 3` — **fails**.
* Sharpe required for `t > 2` over 15.6 years: 0.506.
* Sharpe required for `t > 3` over 15.6 years: 0.759.

Fifteen and a half years is a long sample and it is still not enough to call a
Sharpe of 0.35 anything. "I backtested fifteen years" carries much less
information than it sounds like it does.

## 3.3 Multiple testing removes what little is left

`research/trials.json` registers **26** distinct configurations evaluated on this
data, recorded as they were run. Applying the Harvey & Liu (*JPM* 2015)
Bonferroni haircut:

* Observed `t` = 1.38 → p = 0.167.
* Against 26 trials: adjusted p = 1.0, adjusted `t` = 0, **100% of the Sharpe
  removed**.
* Against a literature-scale test count (316 published factors, HLZ 2016): the
  same answer, more emphatically.

Deflated Sharpe Ratio (Bailey & López de Prado 2014), which also corrects for
the skewness and fat tails of daily A-share returns:

* vs 26 trials: **DSR ≈ 0.26**
* vs 316 trials: **DSR ≈ 0.06**

A quarter, or a sixteenth. Not a result.

## 3.4 The ranking is nevertheless not noise

The backtest was re-run 40 times with identical rules — same universe, same
screens, same position count, same costs — replacing the factor ranking with
**random selection from the eligible pool**:

| random-selection CAGR | |
|---|---|
| 5th percentile | −6.93% |
| 25th | −5.99% |
| median | −4.13% |
| 75th | −2.74% |
| 95th | +1.61% |
| **actual (ranked) CAGR** | **+4.67%** |

The ranked result sits above all 40 draws, 8.8 percentage points a year above
the median draw. Combined with the `t = 6.61` on the signal itself, there is no
serious doubt that the cross-section carries information.

## 3.5 So where does it go?

Three places, in order of size.

**Costs, and specifically their shape.** Chapter 2 measures the fee burden
rising from 0.48% of assets a year at CNY 2 million to 5.41% at CNY 1,000 — an
elevenfold increase driven by a CNY 5 per-trade minimum. At the account sizes
this tool was built for, fees are a first-order term, not a correction.

**Position-count collapse.** The lot-size constraint and the minimum-ticket rule
together drive the holding count from 12 down to 1 at CNY 2,000. A one-name book
does not express a cross-sectional signal; it expresses one company. Chapter 2
§2.7 shows the shipped rule costing 10.8 percentage points a year against simply
removing it.

**Constraints that are not in the IC.** The IC is computed on the tradable
universe; the portfolio additionally faces the 10% position cap, the 30%
industry cap, the absolute ROE and dividend gates, price limits, suspensions and
T+1. Each is defensible on its own and each costs something, and their combined
drag is not separately identified here. That is a limitation, recorded in
chapter 4.

## 3.6 Why the out-of-sample decay is not surprising

−5.56pp of decay from in-sample to out-of-sample excess is large but unremarkable
in this literature. Three mechanisms, none of which require the strategy to be
fake:

1. **Selection.** Even with 26 registered trials, the reported configuration is a
   maximum.
2. **Regime.** The holdout window is 2023–2026, during which large-cap quality
   and dividend names in China repriced in a way the 2011–2023 sample does not
   contain.
3. **Crowding.** Dividend and low-volatility strategies in A-shares became
   heavily marketed products over exactly this window.

The data cannot separate these three. Saying which one it was would be a story,
not a finding.

## 3.7 The acceptance criterion was too lenient, and this is the correction

The original acceptance rule passed an out-of-sample result that was "not worse
than 10 percentage points below the full-sample result". An excess of −0.00%
cleared it. A criterion that a coin flip clears is not a criterion. It is
recorded here rather than quietly rewritten, because the revision history of an
acceptance rule is exactly where researcher degrees of freedom hide.

The replacement, declared in `research/trials.json` under `oos_freeze`: the
configuration is frozen as of 2026-09-24, any future change must be registered
*before* it is run, and the frozen configuration's record continues to be
reported alongside whatever replaces it. Trials 27 to 29 are registered under
that rule and have not been run.
