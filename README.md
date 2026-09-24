# The Capacity Floor

**Transaction-cost research has spent thirty years asking how *large* a
strategy can get before it stops working. For retail investors in markets
with a per-trade commission minimum, the binding question is how *small*.**

This repository measures that, for Chinese A-shares, on 15.6 years of
point-in-time data — and shows the bound disappearing in US retail after
the October 2019 commission-to-zero shift, which is the cleanest available
natural experiment on the mechanism.

---

## The result in one table

Same signal, same turnover, same 12 holdings, quarterly rebalance.
**Only the shape of the cost function changes.**

| cost regime | per-trade floor | minimum viable account |
|---|---|---|
| A-share retail | CNY 5.00 | ~CNY 5,300 |
| US retail, pre-Oct-2019 | $4.95 | ~$5,200 |
| US retail, post-Oct-2019 | $0.00 | **none — the bound does not exist** |

And the same mechanism, seen from the portfolio-construction side:

| account size | optimal number of holdings |
|---|---|
| CNY 3,000 | **2** |
| CNY 300,000 | **26** |

> **What is assumed and what is measured.** The two tables above are the
> closed form evaluated at illustrative inputs — 5% gross annual alpha, 50%
> one-way turnover, 12 holdings, quarterly, and for the second table 35%
> average name volatility with 35% average pairwise correlation. The third
> row is the only one that does not depend on those inputs: with no
> per-trade floor the cost function is scale-invariant and no lower bound
> exists at any parameter values. Gross alpha and turnover measured on the
> actual sample, and the full sensitivity grid over both, are produced by
> `research/capacity.py` and land in `results/capacity.json`.

Remove the per-trade floor and this dependence on account size vanishes
completely. That is asserted as a unit test, because it is the mechanism.

---

## Why this is not in the literature

Novy-Marx & Velikov (*RFS* 2016), Frazzini–Israel–Moskowitz (2018) and
Detzel–Novy-Marx–Velikov (*JF* 2023) all model trading costs as
**proportional** — basis points of notional. That is the right model for
institutional US execution, and it is **scale-invariant**: double the
capital and net return per unit of capital is unchanged. Under a
scale-invariant cost model the only thing that can bound capacity is
market impact, so capacity is always reported as a *ceiling*.

Chinese retail brokerage charges 1.5 bps **subject to a CNY 5.00 minimum
per trade.** That is a *fixed* cost. As a fraction of capital it behaves
like `1/A`, so it is not scale-invariant, and it produces a *floor*.

```
            2 · f · τ · N · F
A_min  =  ─────────────────────────
          g  −  f · τ · (d + 2u + 2s)
```

`A_min` is linear in the number of holdings and linear in the rebalance
frequency, and it exists only when gross alpha survives the proportional
costs at all. Derivation, the market-impact upper bound, and the optimal-N
trade-off: **[docs/02-capacity-framework.md](docs/02-capacity-framework.md)**

The commission floor stops binding above `N·F/c` = **CNY 400,000** for a
12-name book. Every Chinese retail account below roughly four hundred
thousand yuan sits entirely inside the fixed-cost regime, where the
standard model is not approximately right — it is the wrong shape.

---

## The strategy itself does not work, and that is reported first

| full sample, 2011-01 → 2026-09 (15.6y) | strategy | CSI 300 |
|---|---|---|
| CAGR | 4.67% | 2.44% |
| max drawdown | −47.6% | −46.7% |
| annual Sharpe | **0.348** | — |

* Implied `t` = 0.348 × √15.62 = **1.38**. Fails `t > 2`; fails the
  Harvey–Liu–Zhu (*RFS* 2016) `t > 3` bar.
* Against the **26 registered trials** in `research/trials.json`, the
  Harvey–Liu (*JPM* 2015) haircut removes **100%** of the Sharpe.
* Deflated Sharpe Ratio (Bailey & López de Prado 2014): **0.26** against
  26 trials, **0.06** against a literature-scale test count.
* Declared 3-year holdout: **−3.33pp** annual excess, versus +2.23pp in
  sample. Rolling 3-year win rate against the benchmark: **0%**.

**But the ranking is not noise.** Re-running the identical rules with
*random* selection from the same eligible pool, 40 times, gives a median
CAGR of **−4.13%** against the ranked strategy's **+4.67%** — the ranked
result sits above all 40 draws, a gap of 8.8pp a year.

So the cross-sectional signal does real work, and it still does not reach
the investor. Where it goes is the subject of the capacity analysis.
Full accounting: **[docs/03-what-does-not-work.md](docs/03-what-does-not-work.md)**

---

## Data integrity: three findings, none about the strategy

**`ann_date` is not the first-disclosure date.** Median gap between
`report_date` and the vendor's announcement date: **396 days**. The
dividend table's `plan_ann_date` shows 101 days, which is the normal
rhythm. The field is the date of the *most recent* filing mentioning the
period — the 2018 interim report re-dates the 2017 interim report. This
creates no look-ahead; it does the opposite, and would have computed every
quality factor from fundamentals more than a year stale. Fixed with
`min(ann_date, statutory deadline)`, bounded below by the period end.

Compustat's equivalent field for US filings behaves the way you would
expect it to; the A-share vendor field does not. That contrast is the
reason the problem was visible at all.

**A destructive look-ahead test, not an argument.** Every price, volume
and financial record at or after a rebalance date was corrupted — 6,546
future financial records overwritten — and the factors recomputed. All
eleven factor values were bit-identical.

**Three alarming numbers in a US control sample were all my own query
scopes.** Delisting returns looked badly incomplete until I noticed the
denominator included securities CRSP flags as *still trading*. The
universe looked like it was growing implausibly until I noticed the count
had no share-code or exchange filter and was picking up ETFs, ADRs, REITs
and SPACs — the largest year-on-year jump lands exactly on the SPAC boom.
Each looked like a property of the world and was a property of the
question. (Figures are omitted: that data is licensed. See
[docs/01](docs/01-data-integrity.md#15-redistribution-constraint).)

**[docs/01-data-integrity.md](docs/01-data-integrity.md)**

---

## A bug found by a property test

`tests/test_pit_and_execution.py` asserts that no financial report can
become usable before the period it describes has ended, over randomly
generated announcement offsets. It failed: a generated `ann_date` of
2009-11-11 on the 2010 annual report was accepted verbatim, which is a
genuine look-ahead path. Corrupt dates earlier than the period end are now
discarded in favour of the statutory deadline.

The same defect class exists in US vendor data: a small number of
Compustat rows carry a report date that precedes the period end.

---

## Layout

```
research/
  cost_model.py      analytic capacity model; no I/O, no data dependency
  capacity.py        empirical estimation: gross run, AUM grid, bounds
  factor_eval.py     IC, Rank IC, ICIR, IC decay, decile monotonicity
  stat_honesty.py    haircut Sharpe, Deflated Sharpe, PBO, trial registry
  stats_tools.py     Newey-West, DSR, Harvey-Liu, Patton-Timmermann, CSCV
  signals.py         cached point-in-time signal panel
  trials.json        every configuration evaluated, and the OOS freeze
tests/               49 tests, no third-party dependency required
docs/                the four chapters
code/                the working A-share retail tool: database build,
                     engine, backtest, screener, control panel (Chinese UI,
                     because its users are Chinese retail investors)
results/             generated aggregates and charts (no raw market data)
```

## Reproducing

```bash
pip install -r requirements.txt
python tests/run_tests.py          # 49 tests, ~2 seconds, no database needed
python research/capacity.py        # needs the database; ~60 minutes
python research/factor_eval.py     # ~15 minutes, reuses the cached panel
python research/stat_honesty.py --pbo
```

`research/cost_model.py` and the whole test suite run with nothing but
NumPy, so every claim in the "one table" section above is verifiable
without downloading any market data at all.

The A-share database is built from free public sources (Baostock,
AKShare) by `code/build_db.py`; it is about 5,500 names over 15.5 years
and takes several hours to fetch. **No market data is committed to this
repository.**

CRSP and Compustat are licensed through an institutional subscription, so
this repository applies a stricter rule than the licence requires: no
record-level extract, **and no WRDS-derived figures either**, even summary
ones that would ordinarily count as publishable research results. The
committed WRDS code writes nothing to disk and takes credentials only from
the environment or an interactive prompt. Nothing in the argument depends
on licensed data — the cross-market comparison is computed from published
retail commission schedules. Rationale:
[docs/01 §1.5](docs/01-data-integrity.md#15-redistribution-constraint).

---

## Method notes that a reviewer would check

* **Turnover is computed with drifted weights**,
  `w⁻ = w_{t-1}(1+r_i)/(1+r_p)`. Undrifted turnover charges the strategy
  for price moves it never traded; both are reported so the gap is visible.
* **Newey–West throughout.** Horizon-`h` ICs measured every rebalance
  overlap by `h−1` periods, so the naive `t` is inflated by roughly `√h`.
* **Sorted portfolios at J = 10 and J = 20.** Cattaneo, Crump, Farrell &
  Schaumburg (*REStat* 2020) show the universal choice of deciles is
  arbitrary; a result that exists at only one `J` is not a result.
* **Monotonicity is tested**, not eyeballed — Patton & Timmermann
  (*JFE* 2010). A top-minus-bottom spread can be strongly positive while
  most interior steps go the wrong way.
* **Kurtosis passed to the Deflated Sharpe Ratio is non-excess**
  (`scipy.stats.kurtosis(fisher=False)`). The default returns excess
  kurtosis and silently inflates the DSR.
* **Universe excludes the smallest 30% by float market cap**, following
  Liu, Stambaugh & Yuan (*JFE* 2019) on shell-value contamination in
  A-shares, and uses EP rather than book-to-market for the same reason.
* **Execution models T+1, price limits (±10% main board, ±20%
  ChiNext/STAR, ±5% → ±10% for main-board ST from 2026-07-06),
  suspensions, one-price limit days, and 100-share lots.**

Everything the project cannot do is in
**[docs/04-limitations.md](docs/04-limitations.md)**, stated specifically.

---

## References

Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, JPM.
Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*, J. Comput. Finance.
Cattaneo, Crump, Farrell & Schaumburg (2020), *Characteristic-Sorted Portfolios*, REStat.
Detzel, Novy-Marx & Velikov (2023), *Model Comparison with Transaction Costs*, JF.
Elton & Gruber (1977), *Risk Reduction and Portfolio Size*, J. Business.
Harvey & Liu (2015), *Backtesting*, JPM.
Harvey, Liu & Zhu (2016), *… and the Cross-Section of Expected Returns*, RFS.
Liu, Stambaugh & Yuan (2019), *Size and Value in China*, JFE.
Novy-Marx & Velikov (2016), *A Taxonomy of Anomalies and Their Trading Costs*, RFS.
Patton & Timmermann (2010), *Monotonicity in Asset Returns*, JFE.
Qian, Hua & Sorensen (2007), *Quantitative Equity Portfolio Management*.

---

## License and provenance

Code is MIT (`LICENSE`). Market data is not redistributed.

This project was developed with AI assistance (Claude) for implementation
and literature search. The research question, every design decision, and
every claim in this README are mine, and I can derive, defend or
re-run any of them.
