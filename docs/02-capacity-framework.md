# 2. The capacity window

## 2.1 What the literature assumes

Every serious study of whether a factor survives trading costs models
those costs as **proportional**: some number of basis points of notional
traded. Novy-Marx & Velikov (*RFS* 2016) build their whole taxonomy of
anomalies this way. Frazzini, Israel & Moskowitz (2018) use live
institutional execution data, also proportional. Detzel, Novy-Marx &
Velikov (*JF* 2023) refine the estimates; still proportional.

Proportional costs are **scale-invariant**. Double the capital and both
the gross P&L and the cost double, so net return per unit of capital is
unchanged. Under a purely proportional cost model, nothing about being
small can hurt you. The only force that can bound capacity is market
impact, which grows with size. That is why the literature always reports
capacity as a **ceiling**: "this anomaly survives up to $X billion."

For institutional US equity execution, this is the right model. There is
no per-ticket minimum worth modelling.

## 2.2 What Chinese retail brokerage actually charges

| component | rate | side | fixed part |
|---|---|---|---|
| commission | 1.5 bps | both | **CNY 5.00 minimum per trade** |
| stamp duty | 5 bps | sell only | — |
| transfer fee | 0.1 bps | both | — |
| slippage (modelled) | 10 bps | both | — |

The commission floor is the entire story. It is a **fixed** cost. As a
fraction of capital it behaves like `1/A`.

## 2.3 The model

Notation: `A` assets, `N` positions, `tau` one-way turnover per rebalance,
`f` rebalances per year, `c` commission rate, `F` commission floor, `d`
stamp duty, `u` transfer fee, `s` slippage, `g` gross annual excess
return.

A rebalance with one-way turnover `tau` trades `tau*N` names on the sell
side and `tau*N` on the buy side, each of notional `A/N`. So

```
commission per rebalance  = 2 * tau * N * max(A/N * c, F)
commission RATE           = 2 * tau * N * max(A/N * c, F) / A
```

Two regimes:

```
A >= N*F/c    ->  rate = 2*tau*c              constant in A   (scale-invariant)
A <  N*F/c    ->  rate = 2*tau*N*F / A        proportional to 1/A
```

The breakpoint `N*F/c` with `N = 12`, `F = 5`, `c = 1.5bps` is
**CNY 400,000**. Every Chinese retail account below roughly four hundred
thousand yuan is entirely inside the fixed-cost regime. For that
population, the standard cost model is not approximately right; it is
qualitatively the wrong shape.

The scale-invariant terms are

```
prop = tau * (d + 2u + 2s)
```

and total annual cost is `f * (commission_rate + prop + impact)`.

## 2.4 Lower bound — closed form

Inside the floor-binding regime, break-even is

```
g = f * [ 2*tau*N*F/A + tau*(d + 2u + 2s) ]
```

which solves directly:

```
              2 * f * tau * N * F
A_min  =  ---------------------------
           g  -  f * tau * (d+2u+2s)
```

Three things follow immediately, and all three are testable:

1. **`A_min` is linear in `N`.** Holding twice as many names doubles the
   minimum viable account. Diversification is not free.
2. **`A_min` is linear in `f`.** Monthly rebalancing needs three times the
   capital that quarterly does, for the same signal.
3. **`A_min` exists only if `g > f*tau*(d+2u+2s)`.** If the proportional
   costs alone exceed gross alpha, the strategy is dead at every size and
   the floor never gets a chance to matter.

## 2.4b Two floors, not one

`A_min` is linear in `N`. That is not a footnote -- it means the bound is
really a **per-position** requirement, and that quoting `A_min` without
saying how many positions it assumes is meaningless:

```
A_min(N)  =  N  ·  2·f·τ·F / (g − f·τ·(d+2u+2s))
          =  N  ·  CNY 303.6          for this strategy
```

Written that way, it lands in the same units as a second requirement that is
easy to overlook and, in this market, usually binds harder.

**A-shares trade in lots of 100 shares.** One position costs `100 × price`
whether or not you want that much of it. There is no averaging it away and no
partial lot. So there are two floors on capital per position:

| | fee floor | lot floor |
|---|---|---|
| requirement | `2·f·τ·F / (g − f·τ·prop)` | `100 × price` |
| nature | economic | mechanical |
| hardness | soft — the trade clears, you lose money on it | hard — the broker rejects the order |
| visible without measuring | no | yes |
| constrains | whether `N` positions are **worth holding** | whether `N` positions are **holdable** |
| for this strategy | CNY 304 | CNY 250 – 2,500 |

The minimum account is `N` times **whichever is larger**, never the sum:
they are alternative requirements on the same capital, and adding them would
double-count. That is asserted as a test
(`test_minimum_account_is_the_larger_of_the_two_never_the_sum`).

### What the backtest actually did

| account (CNY) | positions | capital per position | binding |
|---|---|---|---|
| 1,000 | 3 | 333 | lot |
| 2,000 | 8 | **250** | **fee** |
| 3,000 | 9 | 333 | lot |
| 5,000 | 11 | 455 | lot |
| 8,000 | 11 | 727 | lot |
| 15,000 | 12 | 1,250 | the 12-position cap |

The lot constraint binds at five of six sizes. The exception is instructive:
at CNY 2,000 the selection rule found eight affordable names and bought all
eight, putting CNY 250 into each -- **below the CNY 304 a position needs to
pay for its own fees.** The book was over-diversified relative to what the
fee schedule could support, which is the failure mode the fee floor exists to
name.

So the practical minimum for running this strategy as designed is not
CNY 3,643 but about **CNY 15,000**, where the lot constraint stops limiting
the book.

### Why this does not collapse the result

An obvious objection: if the lot constraint usually binds harder, is the fee
floor just a by-product of A-share lot sizes?

No, and the US case is what separates them. US retail has **no lot
constraint** -- fractional shares are routine -- but carried a $4.95
per-trade commission until October 2019, which is a fee floor with no lot
floor:

| | lot floor | fee floor |
|---|---|---|
| A-share retail | yes | yes |
| US retail, pre-Oct-2019 | no | yes ($296 per position) |
| US retail, post-Oct-2019 | no | no |

The two mechanisms are independently present and independently removable.
A-shares happen to carry both at once, which is exactly why they are easy to
conflate there, and why the cross-market comparison is doing real work rather
than decorating the result.

What the lot constraint does change is the *interpretation* of the damage. At
CNY 2,000 under the shipped sizing rule the book collapses to one name and
loses 2.99% a year -- but its zero-cost twin loses 2.82%, so at that point
the loss is concentration, not fees. Both floors push in the same direction:
they limit how many positions a small account can carry, and the cost of that
is borne as idiosyncratic risk rather than as a fee line. The fee floor is
the one you cannot see without computing it.

## 2.5 Upper bound

Above the breakpoint, commission is proportional and the binding
constraint is market impact. Using the square-root law
`impact = Y * sigma_daily * sqrt(Q/ADV)`:

```
A_max  =  N * ADV * [ (g/f - 2*tau*c - tau*(d+2u+2s)) / (2*tau*Y*sigma_d) ]^2
```

A practitioner's hard constraint is also reported: never take more than
10% of one day's ADV in a name, giving `A_max = 0.10 * ADV * N`. The
binding bound is the smaller of the two.

## 2.6 Capacity is a window

```
A_min  <  A  <  A_max
  |                |
  |                +-- market impact (the classical bound)
  +------------------- per-trade commission floor (absent from the literature
                       because the literature models institutional execution)
```

## 2.7 Optimal N

At a given `A`, more names lower idiosyncratic risk but raise fixed cost.
Under a constant-correlation model (Elton & Gruber 1977),

```
sigma_p(N) = sigma_bar * sqrt( rho + (1-rho)/N )
```

and net Sharpe is `(g - cost(A,N)) / sigma_p(N)`. Maximising over `N`
gives `N*(A)`. With the measured inputs for this strategy -- gross alpha
6.64%, one-way turnover 46.8%, average name volatility 35.9%, average
pairwise correlation 27.0%, quarterly rebalancing -- the answer is stark:

| account (CNY) | 2,000 | 5,000 | 20,000 | 50,000 | 100,000 | 200,000 | 400,000+ |
|---|---|---|---|---|---|---|---|
| optimal N | 2 | 3 | 8 | 13 | 20 | 29 | 40 |

Holding twelve names on two thousand yuan is not prudence. It is a
transfer to the broker. The shipped tool does something worse: its
minimum-ticket rule combined with 100-share lots leaves it holding a
single name at that account size, and the realised result over 16.5 years
is -2.99% a year against +2.00% gross.

Remove the floor and this dependence vanishes entirely -- `N*` becomes
independent of `A`. That is asserted as a unit test
(`test_optimal_n_without_a_floor_ignores_capital`), because it is the
mechanism, and if it did not hold the model would not mean what this
chapter says it means.

## 2.7b Does the model survive contact with the backtest?

Each account size is run twice: once with costs, once with every cost set
to zero, holding the account size and the position-count rule identical.
The difference is the cost effect and nothing else.

The first version of this test compared every run against a *single*
zero-cost run at N=12. That is not a control. At CNY 2,000 the lot-size
constraint forces N down to 8, and an 8-name book is a different portfolio
with a different gross return -- the confound was larger than the effect.

A second error mattered more. Realised fees were divided by the *opening*
balance, but the account compounds; over 16.5 years at these returns it
grows about 3.5x, so fees paid late are levied on a much larger book. The
correct denominator is the mean account value. With the opening balance
the model looked wrong by several percentage points; with the mean account
value, at the account sizes where the holding count is stable at 12:

| account (CNY) | holdings | measured annual cost | closed form | error |
|---|---|---|---|---|
| 2,000,000 | 12 | 0.48% | 0.53% | -0.05pp |
| 400,000 | 12 | 0.48% | 0.53% | -0.05pp |
| 100,000 | 12 | 0.52% | 0.56% | -0.04pp |
| 30,000 | 12 | 0.69% | 0.75% | -0.06pp |
| 15,000 | 12 | 0.91% | 1.05% | -0.14pp |
| 8,000 | 11 | 1.60% | 1.74% | -0.14pp |
| 5,000 | 11 | 2.17% | 2.94% | -0.77pp |
| 3,000 | 9 | 3.13% | 3.77% | -0.64pp |
| 2,000 | 8 | 3.67% | 4.04% | -0.38pp |
| 1,000 | 3 | 5.41% | 4.32% | +1.09pp |

Within 0.14 percentage points wherever the holding count is stable at 12;
up to about one point below CNY 8,000, where the count drifts between 3
and 11 and a single median value is a coarse summary of a book whose size
changed every quarter. The fee rate rises elevenfold from the largest
account to the smallest with no change to the signal.

One thing the paired design does *not* deliver. The difference between a
run and its zero-cost twin was supposed to isolate the fee effect exactly.
It does not, at small size: with fees switched off the account carries more
cash, can afford different names, and drifts into a different portfolio.
At CNY 8,000 the gross-minus-net CAGR gap is 3.34 points while the measured
fee rate is 1.60% -- the remainder is selection, not fees. So the cost-rate
comparison above is the validation; the CAGR difference is reported but is
contaminated, and saying otherwise would be claiming a control that the
experiment does not have.

Both errors were mine, both were found by checking arithmetic that looked
wrong rather than by assuming the model was, and both are recorded here
rather than silently corrected.

## 2.8 The cross-market natural experiment

The cleanest test of the mechanism is not another market; it is the same
market before and after a change in the cost *function*.

In **October 2019**, Schwab, TD Ameritrade, E\*TRADE and Fidelity moved US
retail equity commission to zero within days of each other. Before that, a
representative online broker charged about **$4.95 flat per trade** — a
fixed cost, structurally identical to the A-share CNY 5 floor. After, the
fixed component was **gone**, and the retail cost function became purely
proportional for the first time.

So the prediction is sharp and falsifiable:

* US retail **before** Oct 2019: a lower capacity bound exists, of the same
  order as the A-share one.
* US retail **after** Oct 2019: the lower bound does not exist at all —
  costs are scale-invariant and small accounts are not structurally
  disadvantaged.
* A-share retail throughout: the lower bound exists and has never gone
  away.

With the measured `g = 6.64%`, `N = 12`, `tau = 46.8%`, quarterly:

| cost regime | per-trade floor | `A_min` |
|---|---|---|
| CN retail | CNY 5.00 | **CNY 3,643** |
| US retail, pre-2019 | $4.95 | **$3,554** |
| US retail, post-2019 | $0.00 | **does not exist** |

The near-equality of the first two is not the point; the floors happen to
be similar in size. The point is the third row, and that it is a
*structural* difference rather than a difference of degree.

## 2.9 What this framework does not claim

It does not claim the strategy in this repository is profitable. It is
not: see [03-what-does-not-work.md](03-what-does-not-work.md). `g` is an
input to the model, measured with costs switched off, and a reader who
believes a different `g` can read their own `A_min` off the sensitivity
grid in `results/capacity.json`. The contribution is the shape of the cost
function and what follows from it, not this particular signal.
