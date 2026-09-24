# 3. What does not work, and how I know

This chapter exists because the alternative — quietly reporting the
in-sample equity curve and moving on — is the single most common failure
in retail quantitative work, and the easiest one for a reader to catch.

## 3.1 The headline numbers

Full sample, 2011-01-31 to 2026-09-15 (15.62 years), quarterly rebalance,
all costs on:

| | strategy | CSI 300 |
|---|---|---|
| CAGR | 4.67% | 2.44% |
| max drawdown | −47.6% | −46.7% |
| annual Sharpe | 0.348 | — |
| rolling 3-year win rate vs benchmark | 49.2% | — |

Declared out-of-sample window, 2023-09-15 to 2026-09-15 (3 years), frozen
before it was evaluated:

| | strategy | CSI 300 |
|---|---|---|
| CAGR | 3.17% | 6.50% |
| excess | **−3.33pp** | — |
| rolling 3-year win rate | **0%** | — |

In-sample excess was +2.23pp per year. Out of sample it is −3.33pp.

## 3.2 The Sharpe is not distinguishable from zero

For an annualised Sharpe `SR` measured over `T` years, `t ≈ SR * sqrt(T)`:

```
t = 0.348 * sqrt(15.62) = 1.38
```

* Conventional bar, `t > 2` — **fails**.
* Harvey, Liu & Zhu (*RFS* 2016) bar, `t > 3` — **fails**.
* Sharpe required for `t > 2` over 15.6 years: 0.506.
* Sharpe required for `t > 3` over 15.6 years: 0.759.

Fifteen and a half years is a long sample, and it still is not enough to
call a Sharpe of 0.35 anything. That is worth internalising: the
statement "I backtested fifteen years" carries much less information than
it sounds like it does.

## 3.3 Multiple testing removes what little is left

`research/trials.json` is a registry of **26** distinct configurations
this project evaluated, recorded as they were run. Applying the Harvey &
Liu (*JPM* 2015) Bonferroni haircut:

* Observed `t` = 1.38 → p = 0.167.
* Against 26 trials: adjusted p = 1.0, adjusted `t` = 0, **100% of the
  Sharpe is removed**.
* Against a literature-scale test count (316 published factors, HLZ 2016):
  same answer, more emphatically.

The Deflated Sharpe Ratio (Bailey & López de Prado 2014), which also
corrects for the skewness and fat tails of daily A-share returns:

* vs 26 trials: **DSR ≈ 0.26**
* vs 316 trials: **DSR ≈ 0.06**

DSR is the probability that the true Sharpe exceeds the best you would
expect from luck alone given the number of things tried. A quarter, or a
sixteenth. Not a result.

## 3.4 But the ranking does carry information

This is the part that would be lost if the project stopped at "it does not
work."

The backtest was re-run 40 times with the identical rules — same universe,
same screens, same position count, same costs — replacing the factor
ranking with **random selection from the eligible pool**:

| random-selection CAGR | |
|---|---|
| 5th percentile | −6.93% |
| 25th | −5.99% |
| median | −4.13% |
| 75th | −2.74% |
| 95th | +1.61% |
| **actual (ranked) CAGR** | **+4.67%** |

The ranked result sits above all 40 random draws. The gap to the median
random draw is **8.8 percentage points a year**.

So the cross-sectional signal is doing real work. What it is not doing is
enough work to clear (a) the benchmark, out of sample, and (b) the
statistical bar that the number of trials imposes.

Those are two different findings and they are both true. The reason they
can coexist is the subject of chapter 2: most of what the signal earns is
handed to the broker before it reaches the investor, and how much is
handed over depends on the size of the account.

## 3.5 Why the out-of-sample decay is not surprising

−5.56pp of decay from in-sample to out-of-sample excess is large but
unremarkable in this literature. Three mechanisms, none of which require
the strategy to be fake:

1. **Selection.** Even with only 26 registered trials, the reported
   configuration is a maximum.
2. **Regime.** The holdout window is 2023–2026, during which large-cap
   quality and dividend names in China were repriced in a way the
   2011–2023 sample does not contain.
3. **Crowding.** Dividend and low-volatility strategies in A-shares became
   heavily marketed products over exactly this window.

The honest position is that the data cannot separate these three. Saying
which one it was would be a story, not a finding.

## 3.6 The acceptance criterion was too lenient, and this is the correction

The original acceptance rule passed an out-of-sample result that was "not
worse than 10 percentage points below the full-sample result". An excess
of −0.00% cleared it. A criterion that a coin flip clears is not a
criterion. It is recorded here rather than quietly rewritten, because the
revision history of an acceptance rule is exactly where researcher
degrees of freedom hide.

The replacement, declared in `research/trials.json` under `oos_freeze`:
the configuration is frozen as of 2026-09-24, any future change must be
registered *before* it is run, and the frozen configuration's live record
continues to be reported alongside whatever replaces it.
