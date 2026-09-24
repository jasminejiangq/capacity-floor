# 4. Limitations

Stated as specifically as possible, because vague limitation sections are
a way of appearing careful without being careful.

## Data

* **Late filers are treated as on-time.** The point-in-time rule uses
  `min(ann_date, statutory deadline)`. A company that files after the
  deadline becomes visible in the backtest before it was visible in
  reality. Most late filers are ST or delisting-risk names and the
  universe excludes ST, but the bias is real and not quantified.
* **Delisted names.** The A-share database is built from a full historical
  name list rather than a current-constituents list, and progress markers
  are never filtered by status, so delisted names are present. What is
  *not* modelled is the terminal return of a delisting — there is no
  A-share equivalent of CRSP's `dlret`. Suspended names are carried at
  their last valid price, which is conservative for a halt and optimistic
  for a name that never reopens.
* **`turn` (turnover rate) drives the float market-cap calculation**
  (`float mktcap = amount * 100 / turn`). Where `turn` is zero or missing
  the value is forward-filled up to 20 days and is otherwise absent, which
  removes the name from the size screen for that date.
* **Dividends are aggregated by fiscal year and assumed additive across
  interim periods.** This was tested rather than assumed: if the annual
  figure contained the interim figure, `interim <= annual` would have to
  hold always, and it is violated in 26.7% of pairs. Two hand-checked
  cases and an independent cross-check agreed. It is still an inference
  about vendor semantics, not documentation.

## Cost model

* **Slippage is a flat 10 bps per side**, not estimated per name or per
  regime. For the small and mid-cap names this strategy often selects,
  that is probably optimistic in stressed markets and pessimistic in calm
  ones.
* **Market impact uses the square-root law with a coefficient of 1.0.**
  This is the standard calibration but it is calibrated on US and European
  institutional flow. No A-share-specific calibration was performed.
* **The upper capacity bound is therefore much softer than the lower
  one.** The lower bound depends only on an exchange-published fee
  schedule and arithmetic. The upper bound depends on an impact model
  imported from another market.

## Execution

* Price limits, suspensions and one-price limit days are modelled, and
  orders that would have been impossible are blocked. What is not modelled
  is **partial fills**, queue position on a limit day, or the intraday
  path. Trades execute at the open.
* **T+1 is enforced**; intraday round trips are impossible by
  construction, which matches Chinese rules.

## Statistics

* The trial registry covers configurations **this project** ran. It cannot
  cover what the rest of the world has run on the same data since 1991,
  which is why a literature-scale count is reported alongside.
* The out-of-sample window is **three years**, which is short. It is a
  genuine holdout in the sense that the configuration was fixed before it
  was evaluated, but three years of one regime is not a strong test.
* PBO is computed over a simplified configuration space (factor weights
  and holding count, no costs or caps). It measures whether *selecting* a
  configuration generalises, which is the right question for PBO, but it
  is not the same object as the full backtest.

## Scope

* **A-shares only.** The US analysis in this repository is a cost-function
  counterfactual computed analytically, plus the data-integrity work in
  chapter 1. A full US replication using CRSP and Compustat is specified
  but not run.
* The retail tool in `code/` is a working product with a Chinese-language
  interface, because its users are Chinese retail investors. It is
  included because the research question came out of building it, not as a
  separate contribution.

## Things that would change the conclusions

* A properly calibrated A-share impact model would move the upper bound,
  possibly by an order of magnitude.
* A longer holdout, or a second market with a per-trade floor, would make
  the lower-bound result much stronger than a single closed form plus one
  grid.
* Access to `comp_pit` (Compustat Point-in-Time) would replace the
  reconstructed US point-in-time alignment with the industry-standard one,
  and the difference between them is itself worth measuring.
