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
gives `N*(A)`. With representative A-share inputs the answer is stark:

| account | optimal N |
|---|---|
| CNY 3,000 | 2 |
| CNY 300,000 | 26 |

Holding twelve names on three thousand yuan is not prudence. It is a
transfer to the broker.

Remove the floor and this dependence vanishes entirely — `N*` becomes
independent of `A`. That is asserted as a unit test
(`test_optimal_n_without_a_floor_ignores_capital`), because it is the
mechanism, and if it did not hold the model would not mean what this
chapter says it means.

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

With `g = 5%`, `N = 12`, `tau = 50%`, quarterly:

| cost regime | per-trade floor | `A_min` |
|---|---|---|
| CN retail | CNY 5.00 | ~CNY 5,300 |
| US retail, pre-2019 | $4.95 | ~$5,200 |
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
