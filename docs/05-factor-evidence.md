# 5. What the signal is worth, measured on the signal

A backtest equity curve cannot tell you whether a signal has information. It
entangles the signal with the position cap, the liquidity screen, the lot-size
constraint and the cost model, and reports one number for all of it. This
chapter evaluates the raw cross-sectional score, separately from any portfolio,
on exactly the same point-in-time data the backtest uses.

Sample: 64 quarterly rebalance dates, 2010-12-31 to 2026-09-16, median tradable
universe 1,432 names after the size, liquidity and valuation screens.

## 5.1 Information coefficients

Rank IC (Spearman) is the headline rather than Pearson IC, because A-share
cross-sectional returns have fat tails and a single limit-up name can drive a
Pearson correlation in any given quarter. It is computed on the universe the
strategy can actually trade, not the whole market — reporting IC on names you
would never buy flatters the signal.

| factor | Rank IC | ICIR (ann.) | t (Newey–West) | hit rate |
|---|---|---|---|---|
| **low volatility** | 0.0886 | 1.559 | **6.61** | 77.8% |
| **composite** | 0.0687 | 1.356 | **5.59** | 69.8% |
| **dividend** | 0.0521 | 1.305 | **4.49** | 73.0% |
| value | 0.0348 | 0.610 | 2.77 | 58.7% |
| quality | 0.0055 | 0.124 | 0.49 | 49.2% |

### On the acceptance bar

The commonly quoted threshold of ICIR > 0.5 has no statistical content. A
defensible bar follows from Harvey, Liu & Zhu (*RFS* 2016), who argue that given
the number of factors the literature has tested, a t-statistic of 3.0 — not 2.0
— is the right hurdle. Since

```
t  ≈  ICIR_annual · √years
```

that translates into `ICIR_annual > 3.0/√years`, which for this 16-year sample
is **0.756**. Three of the five clear it. Value clears 2.0 but not 3.0. Quality
clears nothing.

All t-statistics are Newey–West. Horizon-`h` ICs measured at every rebalance
overlap by `h−1` periods, so the naive t-statistic is inflated by roughly `√h`;
reporting a naive t on overlapping data is among the most common errors in
factor write-ups.

## 5.2 Two horizon curves, and why conflating them matters

An earlier version of this analysis computed one curve and labelled it "IC
decay". The curve rose with horizon, which would have read as a claim that the
signal gets *stronger* with age. It does not. The two quantities are different:

**Cumulative horizon IC** — the score at date `d` against the return from `d` to
`d+h`. It rises with `h` for any persistent signal, because the cumulative
return accumulates the same edge repeatedly. It answers *how long does the
ranking keep paying*.

**Marginal IC** — the score at date `d` against the return of quarter `h`
alone, backed out as `(1+r_h)/(1+r_{h−1}) − 1`. This is the quantity that
decays, and the one Qian, Hua & Sorensen (2007) mean by IC decay.

Marginal Rank IC, quarter `h` alone:

| factor | q1 | q2 | q3 | q4 | q5 | q6 | q6 / q1 |
|---|---|---|---|---|---|---|---|
| low volatility | 0.0886 | 0.0814 | 0.0697 | 0.0565 | 0.0530 | 0.0482 | **54%** |
| dividend | 0.0521 | 0.0427 | 0.0438 | 0.0437 | 0.0414 | 0.0356 | **68%** |
| composite | 0.0687 | 0.0535 | 0.0502 | 0.0453 | 0.0442 | 0.0410 | **60%** |
| value | 0.0348 | 0.0151 | 0.0168 | 0.0209 | 0.0274 | 0.0237 | 68% |
| quality | 0.0055 | 0.0033 | 0.0028 | −0.0059 | −0.0050 | 0.0002 | — |

Cumulative horizon IC, `d` to `d+h`:

| factor | h1 | h2 | h3 | h4 | h5 | h6 |
|---|---|---|---|---|---|---|
| low volatility | 0.0886 | 0.1161 | 0.1306 | 0.1371 | 0.1425 | 0.1470 |
| dividend | 0.0521 | 0.0628 | 0.0752 | 0.0866 | 0.0955 | 0.1016 |
| composite | 0.0687 | 0.0820 | 0.0934 | 0.1014 | 0.1085 | 0.1138 |
| value | 0.0348 | 0.0305 | 0.0338 | 0.0400 | 0.0472 | 0.0515 |
| quality | 0.0055 | 0.0071 | 0.0067 | 0.0007 | −0.0026 | −0.0040 |

**These are slow signals.** None of the three significant factors has halved by
quarter six. That has a direct consequence for chapter 2: `A_min` is linear in
rebalance frequency, so rebalancing a signal four times a year when it decays
over six or more quarters raises the minimum viable account without buying much
freshness. The falsifiable prediction that follows is stated in the README and
in §5.5.

## 5.3 Sorted portfolios

Equal-weighted, low score first, at J = 10 and J = 20. Cattaneo, Crump, Farrell
& Schaumburg (*REStat* 2020) show that the universal choice of deciles is
arbitrary and often statistically inefficient; a result that exists at only one
`J` is not a result, so both are reported.

**J = 10**, per quarter:

| factor | top − bottom | annualised | t (NW) | MR p-value | steps inverted |
|---|---|---|---|---|---|
| low volatility | 3.19% | **13.4%** | 4.53 | **0.007** | 1 of 9 |
| composite | 1.74% | 7.2% | 2.47 | **0.002** | 2 of 9 |
| dividend | 1.54% | 6.3% | 2.35 | 0.589 | 4 of 9 |
| quality | 0.41% | 1.7% | 0.58 | 0.199 | 4 of 9 |
| value | 0.30% | 1.2% | 0.55 | 0.883 | 4 of 9 |

**J = 20**: nothing clears the monotonicity test — the best p-value is 0.205.
The spreads survive (low volatility 15.6% annualised, t = 4.71) but the interior
ordering does not. With 64 quarters and 20 buckets there are roughly 70 names
per bucket per date, and the interior steps are inside the noise. The honest
reading is not that the factor fails at J = 20; it is that this sample cannot
resolve 20 buckets.

### The monotonicity verdict reports two things

Patton & Timmermann (*JFE* 2010) test the null that the pattern is flat or
weakly decreasing, with statistic `J = min_i (μ_{i+1} − μ_i)`. Rejecting it
means the relationship is increasing. That is a *different* claim from
"every adjacent step is positive". Low volatility rejects flatness at p = 0.007
while inverting one of nine steps, and an earlier version of this code collapsed
the two into a single label that printed "not monotone in sample" — a decisive
result displayed as a negative one. The two facts are now reported separately.

## 5.4 The bottom decile is most of the effect

Low-volatility decile means, per quarter, decile 1 = most volatile:

```
 -0.06   1.39   1.84   1.75   2.06   2.11   2.68   2.69   2.72   3.12
```

The step from decile 1 to decile 2 is **1.45 percentage points of the 3.18-point
total spread — 46% of the signal, in one of nine steps.** The remaining nine
deciles span 1.73 points between them, and the one inverted step (decile 3 to 4)
sits inside that flat region.

This is not a ranking signal so much as an exclusion signal, and that
distinction is worth money at retail scale. Capturing a ranking requires holding
a graded portfolio and rebalancing it; capturing an exclusion requires not
buying the most volatile tenth of the market, which costs nothing and turns over
slowly. Chapter 2 says the expensive part of a retail strategy is the trading;
this says most of the edge does not require it.

## 5.5 What I did not do

The quality factor has `t = 0.49`, a hit rate indistinguishable from a coin, and
a marginal IC that turns negative by quarter four. It carries one quarter of the
weight in the equal-weighted composite.

The obvious move is to drop it. **I did not**, for one reason: the quality result
was measured on the same sample that would justify removing it. Dropping it now
and then reporting the improved composite would be fitting the data twice and
presenting the second fit as a discovery — which is precisely the failure the
rest of this repository is built to avoid. The configuration was frozen on
2026-09-24 with a declared holdout, and this change was not part of it.

It is registered in `research/trials.json` as **trial 27**, to be evaluated on
the frozen holdout. Registering it has a cost, because the trial count feeds the
multiple-testing corrections in chapter 3 — which is the point of keeping a
register rather than a memory.

Two further changes are registered the same way and not run:

* **trial 28** — annual rather than quarterly rebalancing, motivated by §5.2.
  The prediction is that `A_min` falls below CNY 2,000; the test measures `τ₁`
  rather than assuming it.
* **trial 29** — low volatility as an exclusion rule (drop the most volatile
  decile) instead of a ranking, motivated by §5.4.

Both are stated before being run, with the predicted direction, so both can
fail.
