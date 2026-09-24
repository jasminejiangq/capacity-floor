# 1. Data integrity: three findings, none of them about the strategy

Before any of the return numbers in this repository mean anything, the
data underneath them has to be what it claims to be. This chapter records
what was actually found. All three findings have the same shape: a number
looked alarming, and the alarming part turned out to be how the number was
produced rather than what it described.

---

## 1.1 `ann_date` is not the first-disclosure date

**Where it came from.** The A-share financial statement table stores an
`ann_date` per company-period, sourced from the vendor's "announcement
date" field. The obvious point-in-time rule is: a report is usable from
`ann_date` onward.

**What was measured.** The median gap between `report_date` and
`ann_date` across the whole financials table is **396 days**.

For comparison, the same measurement on the dividend table — where the
anchor is `plan_ann_date`, the date the board's distribution proposal was
announced — gives a median of **101 days**, which is the normal Chinese
reporting rhythm.

**Diagnosis.** The vendor field is the date of the *most recent* filing
that mentions the period, not the first one. The 2017 interim report is
re-dated to August 2018, because the 2018 interim report restates the
prior-year comparatives and the vendor overwrites the field.

**Why it matters, and why it is not what people assume.** This does *not*
create look-ahead bias. Using a late date only makes information arrive
later than it really did. The damage is subtler and worse for the
strategy: every quality factor would have been computed from fundamentals
that were, on average, more than a year stale. A factor evaluated on
eighteen-month-old ROE is not a weak factor; it is a different factor.

**Fix.** The usable date is

```
available = min(ann_date, statutory filing deadline)
```

bounded below by the period end. Both terms are upper bounds on the true
first-disclosure date:

* `ann_date` is the *latest* mention, so it is at or after the first one.
* The CSRC statutory deadline (Q1 by 30 Apr, interim by 31 Aug, Q3 by
  31 Oct, annual by 30 Apr of the following year) is at or after the first
  disclosure for any company that files on time.

The minimum of two upper bounds is still an upper bound, so the rule
cannot look ahead, while pulling the mis-dated records back to something
sane.

**Residual risk, stated plainly.** Companies that file *late*, past the
statutory deadline, are treated as if they filed on time. Almost all of
them are ST or delisting-risk names, and the universe excludes ST names —
but this is a real, un-eliminated bias, not a solved problem.

**A defect this uncovered.** A property test
(`tests/test_pit_and_execution.py::test_availability_is_never_before_the_period_end`)
generates random announcement offsets and asserts that no report can ever
become usable before the period it describes has ended. It failed: a
generated `ann_date` of 2009-11-11 on the 2010 annual report was accepted
verbatim, which *is* a look-ahead path. Corrupt dates earlier than the
period end are now discarded in favour of the deadline. The interesting
part is that the bug was found by a property nobody had written down
before, not by inspection.

---

## 1.2 A destructive look-ahead test

Arguing that code has no look-ahead bias is weak. Demonstrating it is
better.

Every price, volume and financial record at or after a chosen rebalance
date was **corrupted** — 6,546 future financial records overwritten — and
the factor computation re-run. If any factor value changed, the pipeline
was reading the future.

All eleven factor values were bit-identical.

This is the strongest statement available: not "I checked the code", but
"the future was replaced with garbage and the answer did not move."

---

## 1.3 Three alarming numbers in the US data that were all my own query scopes

Setting up a US control sample through WRDS (CRSP + Compustat) produced
three summary statistics that looked like data-quality disasters. None of
them were. All three were artifacts of how I had written the query.

**Delisting returns appeared to be missing for a large share of records.**
They were not missing. CRSP assigns a delisting code of 100 to securities
that are *still trading*; those rows have no delisting return because
there was no delisting. My query had not excluded them, so non-delisted
securities were sitting in the denominator. Restricted to genuine
delistings, coverage is essentially complete.

**The monthly universe appeared to grow implausibly.** Both ends of the
series were far above the number of US listed common stocks, which should
have been the first clue. The query counted distinct `permno` in
`crsp.msf` with no share-code or exchange filter, which sweeps in ETFs,
closed-end funds, ADRs, REITs, SPACs, preferred shares, units and
warrants. The shape of the series corroborated it: the largest
year-on-year jump lands exactly on the SPAC boom, which is issuance of
something that is not common stock. The standard academic filter is
`shrcd IN (10,11)` and `exchcd IN (1,2,3)`.

**`rdq` coverage on `comp.fundq` appeared low, with a handful of rows
where `rdq` precedes `datadate`.** The second part is the US analogue of
the defect in §1.1 — announcement dates that predate the period end — and
it is a vanishing fraction of rows. The first part is a sampling
constraint rather than an error: `rdq` coverage is known to be weak in the
early history and on small exchanges, so it constrains the usable study
window and has to be broken down by year and exchange before it means
anything.

**What the three have in common.** Each looked like a property of the
world and was in fact a property of the question. The working rule that
came out of it: *before trusting a number, find out how it was produced.*
It is the same rule that produced §1.1, and it is the part of this chapter
worth keeping.

> **Why no figures appear in this section.** The A-share numbers elsewhere
> in this repository come from free public sources and are quoted freely.
> CRSP and Compustat are licensed through a university subscription. The
> summary statistics above would almost certainly qualify as research
> results rather than redistributed data, but "almost certainly" is not a
> standard worth holding a licensed database to, and nothing in this
> project's argument depends on them. So they are omitted, and the
> methodological point — which is mine, not the vendor's — is not.

## 1.4 The finding buried in the schema list

The WRDS schema enumeration includes **`comp_pit`** — Compustat
Point-in-Time. That database stores what was visible at each moment,
including original pre-restatement values, which is strictly more rigorous
than reconstructing point-in-time alignment from `fundq` plus `rdq`. Where
it is available it should be used in preference to the self-aligned
version, and the difference between the two is itself a measurable
quantity worth reporting.

## 1.5 Redistribution constraint

CRSP and Compustat are licensed through an institutional subscription, not
public data. The rule this repository follows is deliberately stricter
than the one the licence requires:

* **No record-level extract is committed.** `data/us/`, `data/wrds/` and
  every `crsp*` / `comp*` file pattern are excluded in `.gitignore`.
* **No WRDS-derived figures are published either** (§1.3), even summary
  ones that would ordinarily count as research results.
* **The WRDS code that is committed writes nothing to disk.** It opens a
  connection, runs queries and prints; credentials come from the
  environment or an interactive prompt and are never stored in a file.
* Nothing in the project's argument depends on licensed data. The
  cross-market comparison in chapter 2 is computed from published retail
  commission schedules, which are public.

The reason for the stricter rule is simple: a licence breach here would
not be a personal problem, it would affect an entire university's access.
That asymmetry justifies giving up a few numbers.
