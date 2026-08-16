# Continuous volatility brake, and an optimizer stability tie-break

**Date:** 2026-08-14 · Engine v6.2.1 + experiment flags · project CSVs,
history ends 2026-05-21 · **mean of 3 rebalance phases** throughout.

## Why phase averaging is not optional here

Shifting which bars the rebalances land on — same cadence, different alignment
— moves full-sample final equity from 1.06M to 0.97M to 0.89M across phases
0/3/6, about 0.9 pp of CAGR. That is larger than either effect tested below.
Single-phase numbers on changes this size are not interpretable, including the
"continuous brake looks good" single cell that prompted this work.

(The first attempt at the phase offset silently did nothing: seeding
`bars_since_rebal` has no effect because the first bar rebalances
unconditionally and resets the counter before it is compared. Fixed by
delaying the first rebalance instead.)

## 1. Continuous volatility brake — do not ship

Production: `k = 1` until realised vol exceeds `VT_HI * target` (1.5x), then
`k = target/v`. At the trigger `k` jumps from 1.00 to 0.667 — a 33%
instantaneous cut in gross exposure from an infinitesimal change in vol.

Four shapes tested. Note that continuity at the trigger FORCES "where braking
starts" to equal "what it brakes toward", so the two simple continuous forms
each give something up; `smoothstep` is the design that avoids that, easing
`k` from 1.0 at `v = target` down to `target/v` by `v = hi*target`.

| kind | variant | CAGR% | Sharpe | MaxDD% | CAGR/DD | braked | mean k |
|---|---|---|---|---|---|---|---|
| base | production | 12.72 | 1.0350 | −17.31 | 0.75 | 174 | 0.887 |
| base | smoothstep | 12.28 | **1.0391** | −17.41 | 0.71 | 440 | 0.856 |
| base | continuous, 1.5x target | **13.51** | 1.0337 | −17.42 | **0.79** | 231 | 0.945 |
| base | continuous, 1.0x target | 11.86 | 1.0323 | −17.34 | 0.69 | 456 | 0.836 |
| leverage | production | 15.05 | 0.9974 | −19.57 | 0.77 | 175 | 0.878 |
| leverage | smoothstep | 14.38 | 1.0045 | **−18.74** | 0.78 | 455 | 0.839 |
| leverage | continuous, 1.5x | **16.34** | **1.0203** | −19.96 | **0.82** | 225 | 0.935 |
| leverage | continuous, 1.0x | 13.83 | 0.9940 | −19.17 | 0.73 | 472 | 0.818 |
| leverage3x | production | **19.66** | **1.0021** | −26.42 | **0.75** | 74 | 0.946 |
| leverage3x | smoothstep | 19.08 | 0.9952 | **−26.29** | 0.73 | 222 | 0.931 |
| leverage3x | continuous, 1.5x | 19.38 | 0.9652 | −29.69 | 0.65 | 81 | 0.976 |
| leverage3x | continuous, 1.0x | 18.44 | 0.9842 | −25.76 | 0.72 | 254 | 0.916 |

**The headline gain was a confound.** "Continuous, 1.5x" scored +1.29 CAGR on
QLD, but its asymptotic vol target is `hi*target` = 15% rather than 10% — it
is partly just braking less (mean k 0.878 → 0.935). The control isolates it:
same 15% target, production's DISCONTINUOUS rule.

| kind | continuous 1.5x | discontinuous 1.5x | continuity alone |
|---|---|---|---|
| base | Sh 1.0337, DD 17.42 | Sh 1.0160, DD 18.56 | **+0.018 Sh, −1.14 pp DD** |
| leverage | Sh 1.0203, DD 19.96 | Sh 0.9875, DD 22.56 | **+0.033 Sh, −2.60 pp DD** |
| leverage3x | Sh 0.9652, DD 29.69 | Sh 0.9374, DD 31.80 | **+0.028 Sh, −2.11 pp DD** |

So at a MATCHED risk target, continuity genuinely helps — better Sharpe and
materially better drawdown on 3/3 sleeves. That is a real finding.

**But it does not survive against production.** `smoothstep` is the clean
test — continuity with the original target and the deadband's intent intact —
and it is worth +0.004 Sharpe on base, +0.007 on QLD, −0.007 on TQQQ, for
−0.44 to −0.67 pp of CAGR. Sub-period consistency is **1/5 CAGR and 2/5 Sharpe
on all three sleeves**, against the 5/5-on-both bar this project used to accept
VBR. That is noise.

**Verdict.** The 33% jump is real and ugly, and fixing it buys nothing
material. Consistent with the determinism result: the brake is not where this
strategy's problems are. If more return is wanted, the sleeve fraction is the
honest knob — it does not disguise a risk increase as a shape improvement.

## 2. Optimizer stability tie-break — works, modestly

Replaces `if cur_obj > best_obj` in the restart argmax. A restart now wins
outright only by a relative margin; inside the margin the candidates are
treated as tied and resolved by (1) smallest L1 distance from the book already
held, then (2) largest SPY+QQQ weight. Distances differ by ~1e-2, so a
last-bit difference in the objective cannot flip the choice.

Sensitivity to arithmetic noise (identical run under two OpenBLAS kernels):

| variant | divergence | vs production |
|---|---|---|
| production | 4.97e-04 | — |
| margin 1e-8 | 5.91e-05 | 8x better |
| margin 1e-6 | 6.42e-05 | 8x better |
| margin 1e-4 | 1.72e-03 | **3.5x worse** |

Performance, mean of 3 phases, margin 1e-6: **+0.01 pp CAGR, +0.001 Sharpe,
identical MaxDD, identical adjustment count (616/616), identical turnover** on
all three sleeves. Free, and consistently non-negative.

**Three things it does not do.**

1. **It does not reduce turnover.** Genuine near-ties at 1e-6 are rarer than
   expected, so no adjustments are eliminated. The mechanism that does reduce
   turnover is the no-trade band (`claude/Bull2012_study_2026-08.md`), which
   was measured and withdrawn once VBR was in the universe.
2. **A wider margin backfires** — 1e-4 is 3.5x worse than production. Whether
   a candidate falls inside the margin is itself a threshold on a noisy
   quantity, so widening it relocates the knife-edge instead of removing it.
   Same lesson as smoothing the sleeve and the brake.
3. **8x, not 8000x.** Other float branches remain (the convergence test
   `cur_obj - prev_obj < 1e-6`, the cap projection's comparisons).

**Verdict.** Inside the webapp it is redundant — dispatch pinning already
gives exact reproducibility, so the residual is zero, not small. Its value is
for the QuantConnect and Zorro ports, where BLAS dispatch cannot be pinned and
an 8x-less-noise-sensitive optimizer is worth having for free.

### A bug worth recording

The first `_beats` seeded the incumbent at `-inf`; `-inf + margin` is NaN, so
every comparison returned False and `w_prev` won permanently. The optimizer
froze: final equity 306,617 vs production's 1,062,832. It would have read as a
spectacular determinism win — the two CPUs agreed exactly — while being a dead
strategy. Caught only because the flags-off regression hash was checked after
every edit.
