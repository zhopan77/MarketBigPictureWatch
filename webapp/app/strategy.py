"""
All-Weather 9 + QQQ-sleeve strategy engine.

A Python port of ZP_AllWeather9_v3_9_2_Cap_LiveETF.c (Zorro Lite-C), built so
the web app can rerun the whole history once a day and cache the result.

WHAT IT IS
    Long-only rotation over 9 ETFs, with residual cash parked in BIL.
    At each rebalance a projected-gradient optimizer picks simplex weights
    maximising a blended short/long Sortino ratio plus a regime-conditioned
    200-day momentum tilt, minus an L1 turnover penalty, subject to a
    per-asset cap.  Rebalance cadence and lookback windows adapt to the VIX
    regime.  A QQQ sleeve tilts SLEEVE_FRAC of the book into QQQ while QQQ
    trends (rolling Heikin-Ashi candle green) AND its returns are persistent
    (DFA-Hurst above a hysteresis band).

PARITY WITH THE ZORRO ORIGINAL  --  read this before trusting the numbers
    Every constant, the objective, the cap projection, the DFA-Hurst, the
    rolling-HA trend test, the hysteresis and the bar-counted cadence are
    transcribed 1:1.  Four things cannot be identical, and all four are
    deliberate:

    1. RANDOM RESTARTS.  Restarts 1..4 start from a uniform Dirichlet draw.
       Zorro's random() and numpy's generator produce different streams, so
       the optimizer can land on a different local optimum.  Restart 0 is
       deterministic (anchored on the previous weights) and dominates in
       practice, but expect close-not-identical weights.  Seeded here so the
       dashboard is at least reproducible day to day.
    2. FILLS.  Zorro places market orders that fill on the NEXT bar.  We
       model exactly that: a target set at the close of day t is applied at
       day t+1's OPEN.  Zorro additionally rounds to whole shares; we hold
       fractional shares, so tiny lot-rounding cash drag is absent here.
    3. DATA.  Yahoo (auto_adjust=True) rather than the local .t6 files.
       Both are split+dividend adjusted, but the vendors differ slightly.
    4. FLOATING POINT.  Different summation order in the vectorised
       objective; irrelevant except that a gradient optimizer can amplify
       last-bit differences into slightly different weights.

    Net: treat this as an independent re-implementation for monitoring and
    allocation generation, not as a bit-exact replica of the Zorro backtest.

NO LOOK-AHEAD
    Every decision at bar t reads only bars <= t (returns, prices, MA, HA
    candle, Hurst) and yesterday's VIX, and is executed at t+1's open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# =====================================================================
# Configuration  --  mirrors the #defines in the .c one for one
# =====================================================================

# Universe.  Index order MUST match the Lite-C IDX_* constants, so anything
# new is APPENDED -- SPY..XLE keep indices 0..8 and IDX_QQQ stays 1.
#
# VBR (v6.1.6): small-cap VALUE. The equity sleeve was SPY, QQQ and IWM, all
# cap-weighted and all growth-tilted or blend, so the book had no value/size
# exposure at all. Added as a structural gap, not because of any one period:
# tested against four candidate gaps (real estate, inflation-linked, broad
# commodities, small-cap value) it was the only one to improve BOTH CAGR and
# Sharpe in 5 of 5 sub-periods. Real estate looked good too but only in
# 2008-2012 and it worsened full-sample drawdown; TIP and DBC were dilutive.
# See research/Bull2012_study.md.
TICKERS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "XLE",
           "VBR"]
CASH_TICKER = "BIL"          # residual cash weight is held here (cash carry)
# The leveraged variant swaps the sleeve's instrument. The SIGNAL still comes
# from QQQ -- QLD is 2x QQQ's daily return, so it carries no extra information
# about trend or persistence, only extra noise and decay.
LEVERAGE_SLEEVE = "QLD"          # 2x QQQ
LEVERAGE3_SLEEVE = "TQQQ"       # 3x QQQ; history starts 2010-02

# Daily-reset multiple of each leveraged sleeve instrument, used by the
# consolidation step below. A symbol absent from this map cannot be
# consolidated (there is no unlevered equivalent to convert it into).
SLEEVE_LEVERAGE = {"QLD": 2.0, "TQQQ": 3.0}

N_ASSETS = len(TICKERS)
N_DIMS = N_ASSETS + 1        # risk assets + 1 cash dimension
IDX_CASH = N_ASSETS
IDX_QQQ = TICKERS.index("QQQ")
IDX_SPY = TICKERS.index("SPY")

# Full names, for the Logical-Invest-format allocation export.
HOLDING_NAMES = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000 ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "GLD": "SPDR Gold Shares",
    "XLE": "Energy Select Sector SPDR Fund",
    "BIL": "SPDR Bloomberg 1-3 Month T-Bill ETF",
    "QLD": "ProShares Ultra QQQ (2x)",
    "VBR": "Vanguard Small-Cap Value ETF",
}

# ---- objective / optimizer ----
WIN_LONG = 252               # buffer depth; every adaptive long window <= this
BLEND_SHORT = 0.6
BLEND_LONG = 0.4
N_RESTARTS = 5
# ---- Restart tie-break (v6.2.2) -------------------------------------------
# Relative margin inside which two restarts count as TIED. Set to 0 to restore
# the pre-6.2.2 behaviour exactly.
#
# optimize_weights runs N_RESTARTS gradient ascents and used to keep the best
# by a strict comparison, `if cur_obj > best_obj`. Near-ties are common --
# restart 0 anchors on the previous weights and usually lands close to the
# global optimum -- and a near-tie between LOCAL OPTIMA selects a materially
# different weight vector, not a nearby one. So that one comparison was
# resolving real allocation decisions on whichever last bit the CPU produced.
# Measured: it accounted for essentially all of the cross-machine divergence
# (4.97e-04 with it, 6.03e-08 with a single restart).
#
# Inside the margin the candidates are ranked by _stability_key instead:
# closest to the book already held, then most SPY+QQQ. Those quantities differ
# by ~1e-2, so arithmetic noise cannot flip the choice.
#
# 1e-6 is ~1e10 times the noise floor, so a genuine improvement still wins.
# Do NOT widen it: measured at 1e-4 the divergence is 1.72e-03, 3.5x WORSE
# than production, because "is this candidate inside the margin" is itself a
# threshold on a noisy quantity -- widening relocates the knife-edge rather
# than removing it.
#
# Effect on results, mean of 3 rebalance phases, all three sleeves:
# +0.01 pp CAGR, +0.001 Sharpe, identical MaxDD, identical adjustment count.
# It does NOT reduce turnover -- genuine near-ties are rarer than that would
# need. Its value is robustness, and mainly for the QuantConnect and Zorro
# ports, where BLAS dispatch cannot be pinned the way app/determinism.py pins
# it here.
RESTART_TIE_REL = 1e-6
MAX_ITERS = 200
STEP_SIZE = 0.02
LAMBDA_CHURN = 0.05
SIGD_FLOOR = 0.0001
# Additive constant on the Sortino denominator (DAILY units; multiply by
# sqrt(252) for the annualised equivalent). 0.0 = plain Sortino.
#
# mu / (sigD + c) is a continuous dial between risk-adjusted and absolute
# return: at c=0 it is Sortino, and as c grows the denominator stops varying
# so the optimizer tends toward maximising mu alone. It dilutes a small sigD
# far more than a large one, which is exactly the bias needed when a very
# low-volatility asset (long bonds under ZIRP) wins on Sortino despite a
# mediocre absolute return.
# Default Sortino denominator constant. run_backtest computes the real
# per-rebalance value and PASSES it into optimize_weights; this is only the
# fallback for a direct _objective call. It used to be assigned as a module
# global mid-solve, which was safe only because the daily job happens to run
# its 36 backtests serially -- parallelising the kind loop, the obvious
# optimisation, would have let one sleeve's constant land inside another
# sleeve's objective. Same reasoning as the NTB note below.
SIGD_CONST = 0.0             # set per-rebalance by run_backtest when a yield
                             # series is supplied; see rate_tied_sigd()

# ---- Rate-tied Sortino constant (v5.2) ------------------------------------
# c is scaled by how far the 10-year yield sits below SIGD_RATE_REF, because a
# bond's forward expected return is roughly its starting yield: trailing
# Sortino credits it with capital gains from a rate decline that cannot repeat
# once yields are already near zero. High yields -> c ~ 0 -> plain Sortino.
#
# The yield is smoothed over SIGD_SMOOTH days. That matters more than it looks:
# unsmoothed, or measured on BILLS instead of the 10-year, the penalty spikes
# during a flight to quality and strips the book of ballast in the middle of a
# crash. With this configuration the 2008 multiplier is ~0.04.
#
# SIGD_SMOOTH selects between the two configurations that were tested. Only the
# smoothing window differs; SIGD_RATE_REF and SIGD_CMAX are the same for both.
#
#   252 (current) -- the strongest of the 7 dose-matched variants:
#       2008-2019 CAGR 6.41% -> 7.82%   Sharpe 0.630 -> 0.711
#       full      CAGR 12.31% -> 13.19%  Sharpe 1.032 -> 1.061  MaxDD 17.08 -> 17.57%
#   504 -- the conservative one, lowest drawdown rather than highest Sharpe:
#       2008-2019 CAGR 6.41% -> 7.28%   Sharpe 0.630 -> 0.670
#       full      CAGR 12.31% -> 12.80%  Sharpe 1.032 -> 1.034  MaxDD 17.08 -> 17.36%
#
# 252 is also the variant that was TUNED, so its edge carries more fitting risk
# than the sweep's other six: full-sample Sharpe across all seven ranged
# +0.029 down to -0.017 against a noise floor of 0.013, and only this one sat
# clearly above it. The 2008-2019 CAGR gain is robust in a way the Sharpe gain
# is not -- all seven improved that window.
# CAVEAT: ZIRP occurs once in the sample, so every bit of this evidence comes
# from one regime, and the 2000-2005 OOS window cannot test it (yields were
# 4-6%, leaving the term inactive). Set SIGD_CMAX = 0.0 to disable.
SIGD_RATE_REF = 0.04         # 10y yield at/above which no penalty applies
SIGD_CMAX     = 0.151 / 15.874507866387544    # 15.1% annualised -> daily
                                              # (0.151 is a FRACTION, not a percent)
SIGD_SMOOTH   = 252          # trading days of smoothing; 504 = conservative
WARMUP = 260                 # > WIN_LONG so both Sortinos are computable
MAX_WEIGHT = 0.7             # v3.9 per-asset cap
CAP_PASSES = 10              # clip-and-redistribute iterations
ANN = np.sqrt(252.0)

# ---- VIX regime thresholds and the parameters each regime selects ----
VIX_HIGH, VIX_MID = 25.0, 18.0
INTERVAL_FAST, INTERVAL_NORMAL, INTERVAL_SLOW = 5, 10, 15
WIN_SHORT_FAST, WIN_LONG_FAST = 60, 120
WIN_SHORT_NORMAL, WIN_LONG_NORMAL = 120, 252
WIN_SHORT_SLOW, WIN_LONG_SLOW = 180, 252
LAMBDA_MOM_NORMAL = 8.0
LAMBDA_MOM_SLOW = 12.0       # FAST regime is always 0: no chasing in a selloff

# ---- momentum tilt ----
MA_BARS = 200

# ---- QQQ sleeve ----
HA_SPAN_BARS = 21            # rolling Heikin-Ashi candle length (~1 month)
SLEEVE_FRAC = 0.5            # fraction of the book tilted into QQQ when ON

# ---- Conditional volatility targeting (PRODUCTION since v5.0) -------------
# Scales the whole book down when the strategy's own trailing realised
# volatility runs hot, and leaves it alone otherwise. "Conditional" is the
# important word: plain volatility targeting adjusts exposure continuously and
# can INCREASE drawdowns, whereas intervening only in the high-volatility
# extreme improves risk-adjusted return with far less turnover.
#
# k <= 1 ALWAYS. The account is a cash IRA, so the brake can de-risk but must
# never lever up; the freed weight goes to the BIL cash leg.
#
# Study result (project CSVs, zero-carry cash, phase-averaged over the 5
# rebalance phases, QQQ sleeve at 0.75, in-sample 2006-01..2026-05):
#   control          Sharpe 0.9339  CAGR 12.42%  MaxDD 19.90%
#   + vol brake      Sharpe 1.0095  CAGR 11.99%  MaxDD 17.13%
# 5/5 paired wins, paired sd 0.026; every sub-period improves; the brake
# engages on ~19% of order bars (mean k 0.92). OOS 2000-10..2005-12 agreed
# (Sharpe 0.447 -> 0.528, drawdown flat).
# The brake target is a per-(kind, sleeve_frac) TABLE, not a formula. See
# "vt_table" in KINDS. A linear rule -- target = clip(base*frac/0.60, .10, .40)
# -- was used first and got the SHAPE wrong: it applied the same scaling to
# every kind, but the book's own volatility rises with the sleeve fraction only
# as fast as the sleeve instrument is levered. Measured, no brake:
#
#     sleeve_frac      0%    20%    40%    60%    80%   100%
#     base   (QQQ 1x) 11.9%  12.1%  12.4%  12.9%  13.5%  14.2%
#     lever  (QLD 2x) 11.9%  12.9%  14.6%  16.7%  19.0%  21.4%
#     lev3x (TQQQ 3x) 11.9%  14.0%  17.2%  21.0%  24.8%  28.5%
#
# So the 1x sleeve barely moves book vol and its target should stay flat, while
# the 3x sleeve nearly triples it. The linear rule loosened the base kind's
# target to 17% at frac 1.00, which simply switched the brake off.
#
# scaled_vt_target() is kept as the fallback for a fraction absent from a
# kind's table.
VT_FRAC_BASE = 0.60          # sleeve fraction a scalar target is quoted at
VT_MIN       = 0.10
VT_MAX       = 0.40


def scaled_vt_target(base: float, sleeve_frac: float) -> float:
    """Fallback when a kind has no table entry for this fraction."""
    if VT_FRAC_BASE <= 0:
        return base
    return float(min(VT_MAX, max(VT_MIN, base * sleeve_frac / VT_FRAC_BASE)))


VT_TARGET = 0.10             # annualised vol the brake aims for (per-kind;
                             # see the "vt_target" entry in KINDS)
#
# The target must match the RISK THE BOOK IS MEANT TO RUN, not be a constant.
# A QQQ or QLD-at-0.50 book runs ~15-20% vol, so 10% engages the brake
# meaningfully but not constantly. A 100% TQQQ book runs 40-60%, where a 10%
# target pins the brake on permanently and throttles the sleeve to little more
# than 1x -- which is the whole reason to hold a 3x fund. Measured on the 3x
# sleeve over 15 years:
#     target 10%  CAGR 15.12%  Sharpe 0.84  MaxDD 36.2%
#     target 30%  CAGR 26.09%  Sharpe 0.95  MaxDD 39.9%
#     no brake    CAGR 25.59%  Sharpe 0.89  MaxDD 49.8%
# 30% dominates no-brake on all three, so the brake still earns its keep --
# it just has to be sized to the book. On the 2x sleeve 10% remains best
# (Sharpe 1.10 vs 1.01 unbraked), so only the 3x kind differs.
#
# NOTE: the target is per KIND, not per sleeve fraction. Selecting 0.50 on the
# 3x tab halves the book's vol, so the 30% target will rarely engage there.
VT_WIN    = 60               # trailing window of realised strategy returns
VT_HI     = 1.5              # only de-risk once realised vol > VT_HI * VT_TARGET
VT_FLOOR  = 0.30             # never scale gross exposure below this
H_ENTER = 0.55               # Hurst: switch sleeve ON above this
H_EXIT = 0.45                # Hurst: switch sleeve OFF below this
HURST_WIN = 100              # returns in the DFA window
DFA_SCALES = (10, 15, 25, 30, 50)

# ---- No-trade band (v6.1.6) ----------------------------------------------
# NTB is a per-asset half-width, in weight units; W_SMOOTH blends each new
# solution with the one actually held. Both default to 0 here and are set
# PER KIND by strategy_service.KINDS, then passed into run_backtest as
# arguments -- never read from these globals during a run, because the daily
# job builds every kind in one process and a global would carry one kind's
# band silently into the next.
#
# SHIPPED OFF on every kind. It was a clear gain on the 9-asset universe, and
# adding VBR took the gain away -- the band and the wider universe fix the
# same defect, so they do not add. Kept wired because the reasoning below is
# sound and the mechanism may matter again if the universe narrows. The
# measured numbers are in the KINDS comment in strategy_service.py.
#
# This is not a new heuristic. The objective already carries an L1 churn
# penalty, and an L1 kink IS a no-trade region -- the same mechanism that makes
# LASSO produce exact zeros. The finite-difference optimizer cannot see it: the
# central difference of |w - w_prev| AT w_prev is (|+h| - |-h|)/2h = 0 in every
# direction, so the penalty exerts no force at exactly the point where its true
# subgradient is widest ([-LAMBDA_CHURN, +LAMBDA_CHURN]) and the book is never
# allowed to sit still. Soft-thresholding the deviation is that same term's
# proximal operator -- how an L1 penalty is meant to be solved.
#
# Trading stops AT the band boundary rather than continuing to the target
# (Leland): the last increment of a move is worth less than it costs. Measured,
# that distinction is the whole effect -- plain all-or-nothing thresholding
# leaves turnover and returns unchanged.
NTB = 0.0
W_SMOOTH = 0.0

CAPITAL = 100_000.0
RNG_SEED = 12345


# =====================================================================
# DFA-Hurst  (Peng et al. 1994)
# =====================================================================
def dfa_hurst(x: np.ndarray) -> float:
    """Detrended fluctuation analysis exponent of a return series.

    (a) profile Y[k] = cumsum(x - mean(x))
    (b) for each scale s: split Y into nb = floor(N/s) non-overlapping boxes,
        least-squares detrend each box, F(s) = sqrt(mean box residual MS)
    (c) H = slope of log F(s) vs log s

    Returns 0.5 (neutral) when the window is short or degenerate, matching
    the Lite-C guards exactly.
    """
    n = x.size
    if n < HURST_WIN:
        return 0.5

    y = np.cumsum(x - x.mean())

    log_s, log_f = [], []
    for s in DFA_SCALES:
        nb = n // s                      # number of non-overlapping boxes
        if nb < 2:
            continue
        # (nb, s) view of the profile; least-squares line fit per row.
        boxes = y[: nb * s].reshape(nb, s)
        t = np.arange(s, dtype=float)
        st, stt = t.sum(), (t * t).sum()
        sy = boxes.sum(axis=1)
        sty = boxes @ t
        denom = s * stt - st * st
        if denom == 0:
            slope = np.zeros(nb)
            intercept = sy / s
        else:
            slope = (s * sty - st * sy) / denom
            intercept = (sy - slope * st) / s
        resid = boxes - (intercept[:, None] + slope[:, None] * t[None, :])
        ms = (resid * resid).sum(axis=1) / s      # residual MS per box
        ms_mean = ms.mean()
        if ms_mean <= 0:
            continue
        log_s.append(np.log(s))
        log_f.append(np.log(np.sqrt(ms_mean)))

    if len(log_s) < 2:
        return 0.5
    ls = np.asarray(log_s)
    lf = np.asarray(log_f)
    cnt = ls.size
    num = cnt * (ls * lf).sum() - ls.sum() * lf.sum()
    den = cnt * (ls * ls).sum() - ls.sum() ** 2
    if den == 0:
        return 0.5
    return float(num / den)


def rolling_ha_green(o: np.ndarray, h: np.ndarray, l: np.ndarray,
                     c: np.ndarray) -> np.ndarray:
    """Rolling Heikin-Ashi trend candle, recomputed every bar.

    The candle spans the trailing HA_SPAN_BARS daily bars:
        O = open of the OLDEST bar in the window,  C = today's close
        H = highest high, L = lowest low over the window
        HA_Close = (O + H + L + C) / 4
    The HA recursion is stepped by HA_SPAN_BARS, NOT by one bar:
        HA_Open(n) = (HA_Open(n-SPAN) + HA_Close(n-SPAN)) / 2
    so it chains to the previous, non-overlapping window -- what a true
    monthly HA does, but evaluated on every bar.  (Stepping it daily would
    collapse HA_Open into an EMA(0.5) of HA_Close and whipsaw badly.)

    Returns a bool array, True where the candle is green (HA_Close > HA_Open).
    Bars before the window is full are False, matching the Lite-C early-out.
    """
    n = c.size
    span = HA_SPAN_BARS
    green = np.zeros(n, dtype=bool)
    if n < span:
        return green

    # Rolling extremes over the trailing `span` bars (inclusive of today).
    hi = pd.Series(h).rolling(span).max().to_numpy()
    lo = pd.Series(l).rolling(span).min().to_numpy()

    ha_o_hist: list[float] = []          # one entry per bar that stores
    ha_c_hist: list[float] = []
    for t in range(span - 1, n):
        o_old = o[t - span + 1]          # open of the oldest bar in the window
        if not (o_old > 0):
            continue
        ha_c = (o_old + hi[t] + lo[t] + c[t]) / 4.0
        k = len(ha_o_hist)               # this bar's store index
        if k >= span:
            ha_o = (ha_o_hist[k - span] + ha_c_hist[k - span]) / 2.0
        else:
            ha_o = (o_old + c[t]) / 2.0  # seed the recursion
        ha_o_hist.append(ha_o)
        ha_c_hist.append(ha_c)
        green[t] = ha_c > ha_o
    return green


# =====================================================================
# Optimizer
# =====================================================================
def _objective(W: np.ndarray, R: np.ndarray, win_short: int, win_long: int,
               mom: np.ndarray | None, lam: float,
               w_prev: np.ndarray | None,
               sigd_const: float) -> np.ndarray:
    """Objective for a BATCH of weight vectors.

        obj(w) = BLEND_SHORT * Sortino_short + BLEND_LONG * Sortino_long
                 + lambda_mom * sum_i w_i * (price_i / MA200_i - 1)
                 - LAMBDA_CHURN * ||w - w_prev||_1

    W is (m, N_DIMS); R is (win_long, N_ASSETS) with row 0 = TODAY's return,
    so the short window is simply the first `win_short` rows.  Batching lets
    one matmul cover all 20 central-difference evaluations of a gradient.
    Returns an (m,) array.
    """
    rpf = R @ W[:, :N_ASSETS].T                    # (win_long, m)
    neg = np.minimum(rpf, 0.0)

    mu_l = rpf.sum(axis=0) / win_long
    sd_l = np.sqrt((neg * neg).sum(axis=0) / win_long)
    mu_s = rpf[:win_short].sum(axis=0) / win_short
    sd_s = np.sqrt((neg[:win_short] ** 2).sum(axis=0) / win_short)
    sd_l = np.maximum(sd_l, SIGD_FLOOR)
    sd_s = np.maximum(sd_s, SIGD_FLOOR)

    out = (BLEND_SHORT * (mu_s * ANN / (sd_s + sigd_const))
           + BLEND_LONG * (mu_l * ANN / (sd_l + sigd_const)))
    if lam > 0 and mom is not None:
        out = out + lam * (W[:, :N_ASSETS] @ mom)
    if w_prev is not None:
        out = out - LAMBDA_CHURN * np.abs(W - w_prev).sum(axis=1)
    return out


def project_simplex(w: np.ndarray) -> np.ndarray:
    """Clip to non-negative, renormalise to sum 1, then enforce the per-asset
    cap by iterative clip-and-redistribute (water filling).

    Clipping one weight to MAX_WEIGHT frees weight that must go somewhere, and
    redistributing it can push other names over the cap -- hence the loop.
    The cap applies to risk assets only; cash is a residual, never capped, and
    absorbs the remainder if every risk asset is already pinned.
    """
    w = np.where(w < 0, 0.0, w)
    total = w.sum()
    if total < 1e-9:                     # degenerate: fall back to all cash
        w = np.zeros(N_DIMS)
        w[IDX_CASH] = 1.0
        return w
    w = w / total

    for _ in range(CAP_PASSES):
        over = w[:N_ASSETS] > MAX_WEIGHT
        excess = float((w[:N_ASSETS][over] - MAX_WEIGHT).sum())
        w[:N_ASSETS] = np.where(over, MAX_WEIGHT, w[:N_ASSETS])
        # STRICTLY below the cap can still absorb.  A weight sitting exactly
        # AT the cap must be excluded, because the redistribution below skips
        # it too -- counting it would under-distribute and break the sum.
        free = w[:N_ASSETS] < MAX_WEIGHT
        free_sum = float(w[:N_ASSETS][free].sum()) + float(w[IDX_CASH])
        if excess < 1e-12:
            break
        if free_sum < 1e-12:
            w[IDX_CASH] += excess
            break
        scale = 1.0 + excess / free_sum
        w[:N_ASSETS] = np.where(free, w[:N_ASSETS] * scale, w[:N_ASSETS])
        w[IDX_CASH] *= scale
    return w


def optimize_weights(R, win_short, win_long, mom, lam, w_prev, has_prev, rng,
                     sigd_const=0.0):
    """Projected gradient ascent with N_RESTARTS.

    Restart 0 anchors on the previous weights (deterministic and usually the
    winner); the rest are uniform Dirichlet draws on the simplex.
    """
    churn_ref = w_prev if has_prev else None
    h = 1e-4
    # Central-difference scaffold: row 2k is +h on dim k, row 2k+1 is -h.
    bump = np.zeros((2 * N_DIMS, N_DIMS))
    for k in range(N_DIMS):
        bump[2 * k, k] = h
        bump[2 * k + 1, k] = -h

    best_obj, best_w = -np.inf, w_prev.copy()
    for restart in range(N_RESTARTS):
        if restart == 0:
            w = w_prev.copy()
        else:
            # -log(U) normalised == Dirichlet(1,...,1) == uniform on simplex
            u = rng.uniform(1e-9, 1.0 - 1e-9, N_DIMS)
            w = -np.log(u)
            w /= w.sum()

        prev_obj = float(_objective(w[None, :], R, win_short, win_long,
                                    mom, lam, churn_ref, sigd_const)[0])
        for it in range(MAX_ITERS):
            f = _objective(w[None, :] + bump, R, win_short, win_long,
                           mom, lam, churn_ref, sigd_const)
            grad = (f[0::2] - f[1::2]) / (2.0 * h)
            w = project_simplex(w + STEP_SIZE * grad)
            cur_obj = float(_objective(w[None, :], R, win_short, win_long,
                                       mom, lam, churn_ref, sigd_const)[0])
            if cur_obj - prev_obj < 1e-6 and it > 10:
                break
            prev_obj = cur_obj

        cur_obj = float(_objective(w[None, :], R, win_short, win_long,
                                   mom, lam, churn_ref, sigd_const)[0])
        if _restart_wins(cur_obj, w, best_obj, best_w, w_prev, has_prev):
            best_obj, best_w = cur_obj, w.copy()
    return best_w, best_obj


def _stability_key(w, w_prev, has_prev):
    """Tie-break ranking, most significant first. Lower is better.

    1. L1 distance from the book already held. Between two solutions that
       score the same, the nearer one is the better trade, and picking it is
       what makes the choice deterministic -- these distances differ by ~1e-2,
       so a last-bit difference in the OBJECTIVE cannot flip the ranking.
    2. Negative SPY+QQQ weight, i.e. prefer the large-cap core. Only reached
       when two candidates are equally good AND equally close to the current
       book. It exists so the rule is total, leaving no genuine coin-flip.
    """
    d = float(np.abs(w - w_prev).sum()) if has_prev else 0.0
    return (d, -float(w[IDX_SPY] + w[IDX_QQQ]))


def _restart_wins(cur_obj, w, best_obj, best_w, w_prev, has_prev) -> bool:
    """Does this restart replace the incumbent? See RESTART_TIE_REL."""
    # No incumbent yet. best_w is seeded with w_prev so there is always
    # something to return, but best_obj is -inf -- and -inf + margin is NaN,
    # which makes every comparison below False and leaves w_prev the winner
    # forever. That is not a small bug: it freezes the optimizer completely,
    # and it cost 3.5x of final equity before it was caught. It also LOOKS
    # like a perfect reproducibility result, because two machines then agree
    # exactly on a dead strategy.
    if not np.isfinite(best_obj):
        return True
    if RESTART_TIE_REL <= 0.0:
        return cur_obj > best_obj
    margin = RESTART_TIE_REL * max(abs(cur_obj), abs(best_obj), 1e-12)
    if cur_obj > best_obj + margin:
        return True
    if cur_obj < best_obj - margin:
        return False
    return _stability_key(w, w_prev, has_prev) < \
        _stability_key(best_w, w_prev, has_prev)


# =====================================================================
# Backtest
# =====================================================================
@dataclass
class BacktestResult:
    dates: pd.DatetimeIndex
    equity: np.ndarray                       # strategy equity, starts at CAPITAL
    weights: np.ndarray                      # (n_bars, N_DIMS+1) effective book
    adjustments: list = field(default_factory=list)   # [ADJ ...] log lines
    sleeve_on: np.ndarray | None = None
    hurst: np.ndarray | None = None
    regime: np.ndarray | None = None         # 0 fast, 1 normal, 2 slow
    n_rebalances: int = 0
    n_sleeve_on: int = 0
    n_sleeve_off: int = 0
    target: np.ndarray | None = None         # the book to hold right now
    target_date: str | None = None           # date it was last adjusted
    symbols: list = field(default_factory=list)   # legs, parallel to target


def rate_tied_sigd(long_yield: pd.Series | None, idx) -> np.ndarray:
    """Per-bar Sortino denominator constant from the smoothed 10-year yield.

    Returns zeros when no yield series is supplied, which reproduces plain
    Sortino exactly (pre-v5.2 behaviour).
    """
    n = len(idx)
    if long_yield is None or SIGD_CMAX <= 0:
        return np.zeros(n)
    y = long_yield.reindex(idx).ffill()
    y = y.rolling(SIGD_SMOOTH, min_periods=20).mean().to_numpy(float)
    mult = np.clip((SIGD_RATE_REF - y) / SIGD_RATE_REF, 0.0, 1.0)
    return SIGD_CMAX * np.nan_to_num(mult)


def _log_book(syms, held) -> dict:
    """The book as the adjustment log renders it: legs above 0.5%."""
    return {s: round(float(w), 4) for s, w in zip(syms, held) if w > 0.005}


def _log_shape(syms, held) -> tuple:
    """What the log actually PRINTS -- percents to ONE DECIMAL. Used to decide
    whether a before/after pair is worth showing: comparing the stored
    4-decimal weights would keep pairs that render identically. Must track the
    renderer's precision, so update both together."""
    return tuple((s, round(float(w) * 100, 1))
                 for s, w in zip(syms, held) if w > 0.005)


def _consolidate(held: np.ndarray, lev_i: int, qqq_i: int,
                 lev: float) -> tuple[np.ndarray, float]:
    """Spend cash to convert leveraged sleeve exposure into plain QQQ.

    Holding D of an L-times fund alongside (L-1)*D of cash carries exactly the
    same L*D of QQQ exposure as holding L*D of QQQ outright:

        before   D of the L-x fund                     -> L*D exposure
        after    L*D of QQQ                            -> L*D exposure
        funded   D (from the sleeve) + (L-1)*D (cash)  = L*D

    so the weights still sum to 1 and market exposure is UNCHANGED. What the
    swap removes is the daily-reset volatility decay on that slice and the
    expense-ratio gap (QLD 0.95% / TQQQ 0.86% against QQQ 0.20%); what it costs
    is the BIL yield on the cash spent. The first two win, but only by a
    little, and only as far as the available cash reaches:

        D = min(w_sleeve, w_cash / (L - 1))

    Always taken in full. A rate-scaled variant was tried -- the swap gives up
    cash yield, so in principle it is worth less when cash pays well -- but
    measurement did not support it: always-on beat both a throttled and a
    gated version in every window tested.

    A 3x sleeve therefore consolidates far less than a 2x one for the same
    cash -- it needs two units of cash per unit converted rather than one.

    Runs AFTER the volatility brake on purpose. The brake parks weight in cash
    and this step is exposure-neutral, so the brake's risk reduction survives
    intact; the freed cash is simply used to de-lever instead of sitting idle.

    Returns the new book and the fraction of the sleeve that was converted.
    """
    w_lev, w_cash = held[lev_i], held[IDX_CASH]
    if w_lev <= 1e-9 or w_cash <= 1e-9 or lev <= 1.0:
        return held, 0.0
    d = min(w_lev, w_cash / (lev - 1.0))
    out = held.copy()
    out[lev_i] -= d
    out[qqq_i] += lev * d
    out[IDX_CASH] -= (lev - 1.0) * d
    return out, d / w_lev


def _vt_scale(equity: np.ndarray, t: int,
              target: float = VT_TARGET, win: int = VT_WIN,
              hi: float = VT_HI, floor: float = VT_FLOOR) -> float:
    """Conditional volatility brake -> gross-exposure multiplier k in [floor, 1].

    Reads the strategy's OWN realised daily returns over the trailing `win`
    bars up to and including t. equity[t] is already marked when this is
    called, so the estimate is causal -- no bar beyond t is touched.

    Returns 1.0 (no action) unless realised vol exceeds hi * target.
    """
    e = equity[max(0, t - win): t + 1]
    e = e[np.isfinite(e)]
    if e.size < 4:
        return 1.0
    r = e[1:] / e[:-1] - 1.0
    if r.size < 3:
        return 1.0
    v = float(np.std(r, ddof=1)) * np.sqrt(252.0)
    if v <= 0.0 or v < hi * target:
        return 1.0
    return float(min(1.0, max(floor, target / v)))


def _effective_book(weight: np.ndarray, sleeve_on: bool,
                    sleeve_frac: float = SLEEVE_FRAC,
                    n_legs: int = N_ASSETS + 1,
                    sleeve_leg: int = IDX_QQQ) -> np.ndarray:
    """Optimizer weights -> the book actually held.

    The AllWeather book (9 ETFs + the BIL cash leg) is scaled uniformly by
    aw_frac so every leg keeps its RELATIVE proportion -- the optimizer's
    solution is untouched, the whole book is just levered down to make room
    for the sleeve.  Weights sum to exactly 1: aw_frac * 1 + sleeve_frac = 1,
    so the ACCOUNT is never levered.

    `sleeve_leg` says where the sleeve's weight goes. For the plain strategy
    that is QQQ's own index, so the sleeve simply adds on top of the QQQ the
    optimizer already holds. For the leveraged variant it is a separate QLD
    leg appended after cash -- QQQ keeps whatever the optimizer gave it, and
    the sleeve buys QLD alongside. Note that while the account holds no
    margin, holding a 2x fund means the BOOK's economic exposure exceeds
    100% whenever that sleeve is on.
    """
    sleeve = sleeve_frac if sleeve_on else 0.0
    aw = 1.0 - sleeve
    held = np.zeros(n_legs)
    held[:N_ASSETS] = aw * weight[:N_ASSETS]
    held[N_ASSETS] = aw * weight[IDX_CASH]        # the BIL leg
    held[sleeve_leg] += sleeve
    return held


def run_backtest(px: dict[str, pd.DataFrame], vix: pd.Series,
                 log_fn=log.info,
                 sleeve_frac: float = SLEEVE_FRAC,
                 sleeve_symbol: str = "QQQ",
                 vol_target: bool = True,
                 long_yield: pd.Series | None = None,
                 vt_target: float = VT_TARGET,
                 consolidate: bool = True,
                 ntb: float | None = None,
                 w_smooth: float | None = None) -> BacktestResult:
    """Run the strategy over every bar for which all instruments have data.

    px: {ticker: DataFrame with open/high/low/close}, all sharing one index.
    vix: VIX close indexed by the same trading calendar (already forward
         filled); read one bar lagged, exactly like Zorro's GateVIX[1].
    sleeve_frac: fraction of the book tilted into the sleeve while it is ON.
    sleeve_symbol: what the sleeve buys. "QQQ" (default) folds into the
        existing QQQ leg; anything else (e.g. "QLD") becomes an extra leg.
    long_yield: 10-year Treasury yield (as a decimal, e.g. 0.042). When given,
        the Sortino denominator constant varies with it (see rate_tied_sigd).
        Omit to reproduce pre-v5.2 behaviour exactly.
    consolidate: spend cash to convert leveraged sleeve exposure into plain
        QQQ (see _consolidate). ON by default; exposure-neutral, and a no-op
        unless the sleeve is a separate leveraged leg in SLEEVE_LEVERAGE.
    vt_target: annualised vol the brake aims for. Must be sized to the book
        the kind actually runs; see the VT_TARGET comment.
    vol_target: apply the conditional volatility brake (see _vt_scale) to
        the book at order time. ON by default since v5.0 -- pass False to
        reproduce the pre-v5.0 (v3.9.2) behaviour for comparison.

    NOTE: sleeve_frac affects ONLY the effective book, never the optimizer.
    The optimizer reads returns, momentum and VIX; the sleeve ON/OFF state
    comes from the Hurst band and the HA trend candle. Neither depends on
    sleeve_frac, and equity never feeds back into sizing (positions are
    fractional, so there is no lot-rounding path either). So the optimizer
    weights and the sleeve timeline are IDENTICAL across fractions -- the
    variants differ purely in how much of the book the sleeve claims.
    """
    # Per-run, never from the module globals -- see the NTB comment above.
    ntb = NTB if ntb is None else float(ntb)
    w_smooth = W_SMOOTH if w_smooth is None else float(w_smooth)

    idx = px[TICKERS[0]].index
    # per-bar Sortino denominator constant; all zeros when no yield is supplied
    sigd_vec = rate_tied_sigd(long_yield, idx)
    n = len(idx)
    rng = np.random.default_rng(RNG_SEED)

    # ---- price matrices, columns in IDX_* order, cash leg, then any
    #      separate sleeve instrument ----
    extra_sleeve = sleeve_symbol not in TICKERS
    all_syms = TICKERS + [CASH_TICKER] + ([sleeve_symbol] if extra_sleeve else [])
    n_legs = len(all_syms)
    sleeve_leg = (len(all_syms) - 1) if extra_sleeve else TICKERS.index(sleeve_symbol)
    if extra_sleeve and sleeve_symbol not in px:
        raise ValueError(f"no price data supplied for sleeve symbol {sleeve_symbol}")
    close = np.column_stack([px[s]["close"].to_numpy(float) for s in all_syms])
    open_ = np.column_stack([px[s]["open"].to_numpy(float) for s in all_syms])

    # A sleeve instrument can be younger than the core calendar (TQQQ starts
    # 2010-02 against a calendar from 2007-05). Rather than shortening every
    # kind to the youngest one, mark those bars unavailable so the sleeve
    # simply cannot switch on, and give the gap a flat placeholder price so
    # the mark-to-market arithmetic stays finite. The placeholder is never
    # traded because sleeve_ok gates it.
    sleeve_ok = np.ones(len(idx), dtype=bool)
    if extra_sleeve:
        sleeve_ok = np.isfinite(close[:, sleeve_leg])
        if not sleeve_ok.all():
            first = int(np.argmax(sleeve_ok)) if sleeve_ok.any() else len(idx)
            log_fn(f"  {sleeve_symbol}: no history before "
                   f"{idx[first].date() if first < len(idx) else 'ever'}; "
                   f"sleeve held off until then ({int((~sleeve_ok).sum())} bars)")
            for m in (close, open_):
                col = m[:, sleeve_leg]
                col[~np.isfinite(col)] = 1.0
        rets_guard = ~np.isfinite(close[:, sleeve_leg])
        close[rets_guard, sleeve_leg] = 1.0

    # Daily close-to-close returns; row 0 is undefined and never read.
    rets = np.zeros_like(close)
    rets[1:] = close[1:] / close[:-1] - 1.0

    # 200-day simple moving average per asset (risk assets only).
    ma = pd.DataFrame(close[:, :N_ASSETS]).rolling(MA_BARS).mean().to_numpy()

    # QQQ sleeve inputs: plain close returns feed the DFA, rolling HA gives
    # the trend test.  Both are computed over the full history so the sleeve
    # is warm by the time trading starts.
    q = px["QQQ"]
    green = rolling_ha_green(q["open"].to_numpy(float), q["high"].to_numpy(float),
                             q["low"].to_numpy(float), q["close"].to_numpy(float))
    q_ret = np.zeros(n)
    q_ret[1:] = q["close"].to_numpy(float)[1:] / q["close"].to_numpy(float)[:-1] - 1.0

    vix_lag = vix.reindex(idx).ffill().shift(1).to_numpy(float)

    # ---- state ----
    weight = np.zeros(N_DIMS); weight[IDX_CASH] = 1.0
    weight_prev = weight.copy()
    has_prev = False
    initialized = False
    bars_since_rebal = 0
    cur_interval = INTERVAL_NORMAL
    sleeve_on = False
    cur_hurst = 0.5

    pos = np.zeros(n_legs)            # dollar position per leg (incl. BIL)
    cash = CAPITAL                    # uninvested dollars
    pending: np.ndarray | None = None  # book to establish at the next open
    current_target = np.zeros(n_legs)  # book from the last adjustment
    last_adj_date: str | None = None

    equity = np.full(n, np.nan)
    held_hist = np.zeros((n, n_legs))
    sleeve_hist = np.zeros(n, dtype=bool)
    hurst_hist = np.full(n, np.nan)
    regime_hist = np.full(n, -1, dtype=int)
    adjustments: list[dict] = []
    n_rebal = n_on = n_off = 0
    last_printed: np.ndarray | None = None

    first_live = max(WARMUP, WIN_LONG + 1)
    log_fn(f"Backtest: {n} bars {idx[0].date()}..{idx[-1].date()}, "
           f"trading from bar {first_live} ({idx[first_live].date()})")

    for t in range(n):
        # -------- 1. mark the book to this bar --------
        if t > 0:
            if pending is not None:
                # Order placed at the close of t-1 fills at THIS bar's open.
                op = open_[t] / close[t - 1]                 # close -> open
                pos *= op
                equity_at_open = pos.sum() + cash
                pos = pending * equity_at_open               # establish target
                cash = equity_at_open - pos.sum()
                pos *= close[t] / open_[t]                   # open -> close
                pending = None
            else:
                pos *= 1.0 + rets[t]
        eq = pos.sum() + cash
        equity[t] = eq

        if t < first_live:
            held_hist[t] = 0.0
            continue

        # -------- 2. QQQ sleeve signal (evaluated on the QQQ pass) --------
        cur_hurst = dfa_hurst(q_ret[max(0, t - HURST_WIN + 1): t + 1])
        trend_up = bool(green[t])
        want_on = sleeve_on
        if not sleeve_on:
            # currently off: turn on only if BOTH conditions are strong
            if trend_up and cur_hurst > H_ENTER:
                want_on = True
        else:
            # currently on: off if trend lost OR persistence weak
            if (not trend_up) or cur_hurst < H_EXIT:
                want_on = False
        if not sleeve_ok[t]:
            want_on = False      # instrument does not exist yet. Must come
                                 # AFTER the entry test: placed before it, the
                                 # entry branch re-enables the sleeve and it
                                 # thrashes on/off every bar.
        flipped = want_on != sleeve_on
        if flipped:
            sleeve_on = want_on
            if sleeve_on:
                n_on += 1
            else:
                n_off += 1

        # -------- 3. scheduled rebalance (evaluated on the XLE pass) --------
        do_rebal = False
        if not initialized:
            do_rebal, initialized = True, True
        else:
            bars_since_rebal += 1
            if bars_since_rebal >= cur_interval:
                do_rebal = True

        if do_rebal:
            bars_since_rebal = 0
            n_rebal += 1
            # Regime FIRST: it sets the windows that govern THIS optimization
            # and the interval that governs the NEXT hold period.
            v = vix_lag[t]
            if not np.isfinite(v):
                v = VIX_MID              # neutral if VIX is missing
            if v > VIX_HIGH:
                regime, cur_interval = 0, INTERVAL_FAST
                win_s, win_l, lam = WIN_SHORT_FAST, WIN_LONG_FAST, 0.0
            elif v > VIX_MID:
                regime, cur_interval = 1, INTERVAL_NORMAL
                win_s, win_l, lam = WIN_SHORT_NORMAL, WIN_LONG_NORMAL, LAMBDA_MOM_NORMAL
            else:
                regime, cur_interval = 2, INTERVAL_SLOW
                win_s, win_l, lam = WIN_SHORT_SLOW, WIN_LONG_SLOW, LAMBDA_MOM_SLOW
            regime_hist[t] = regime

            # R[j, i] = asset i's return j bars back; row 0 is TODAY.
            R = rets[t - win_l + 1: t + 1, :N_ASSETS][::-1]
            m = ma[t]
            mom = np.where(m > 0, close[t, :N_ASSETS] / np.where(m > 0, m, 1.0) - 1.0, 0.0)
            if not np.all(np.isfinite(mom)):
                mom = np.nan_to_num(mom)

            # rate-tied Sortino constant for THIS rebalance, computed
            # immediately before the solve and passed IN, so it cannot drift
            # out of step with the bar and cannot leak between concurrent runs
            cur_sigd = float(sigd_vec[t])
            weight, _ = optimize_weights(R, win_s, win_l, mom, lam,
                                         weight_prev, has_prev, rng,
                                         cur_sigd)
            # No-trade band: soft-threshold the deviation from the book we are
            # actually holding, then stop at the boundary rather than going all
            # the way to the new optimum.
            if ntb > 0.0 and has_prev:
                d = weight - weight_prev
                d = np.sign(d) * np.maximum(0.0, np.abs(d) - ntb)
                weight = project_simplex(weight_prev + d)
            if w_smooth > 0.0 and has_prev:
                weight = project_simplex((1.0 - w_smooth) * weight
                                         + w_smooth * weight_prev)
            weight_prev = weight.copy()
            has_prev = True

        # -------- 4. place orders if anything changed --------
        if do_rebal or (flipped and has_prev):
            held = _effective_book(weight, sleeve_on, sleeve_frac,
                                   n_legs, sleeve_leg)
            # Conditional volatility brake. Scales every non-cash leg
            # by k and parks the freed weight in BIL, so relative proportions
            # inside the risk book are preserved and the account stays 1x.
            vt_k = 1.0
            if vol_target:
                vt_k = _vt_scale(equity, t, target=vt_target)
                if vt_k < 1.0:
                    risk = held.copy()
                    risk[IDX_CASH] = 0.0
                    held = risk * vt_k
                    held[IDX_CASH] = max(0.0, 1.0 - held.sum())
            # Cash -> unlevered QQQ swap, after the brake so it uses whatever
            # cash the brake has just freed.
            cons_share = 0.0
            held_pre = None
            if consolidate and extra_sleeve and sleeve_symbol in SLEEVE_LEVERAGE:
                held_pre = held.copy()          # for the before/after log line
                held, cons_share = _consolidate(
                    held, sleeve_leg, TICKERS.index("QQQ"),
                    SLEEVE_LEVERAGE[sleeve_symbol])
            pending = held
            current_target = held
            last_adj_date = idx[t].strftime("%Y-%m-%d")
            tag = ("REBAL" if do_rebal
                   else (f"to {sleeve_symbol}" if sleeve_on else "to PORT"))
            # Only log when the book actually changed at display precision.
            rounded = np.round(held * 100).astype(int)
            if last_printed is None or not np.array_equal(rounded, last_printed):
                adjustments.append({
                    "date": idx[t].strftime("%Y-%m-%d"),
                    "tag": tag,
                    # gross-exposure multiplier applied by the volatility
                    # brake; 1.0 (absent) means it did not engage. Kept as its
                    # own field rather than folded into `tag`, which the log
                    # renderer matches on exactly.
                    "vt": round(float(vt_k), 3),
                    # share of the sleeve swapped into plain QQQ, 0 = none
                    "cons": round(float(cons_share), 3),
                    "hurst": round(float(cur_hurst), 3),
                    "sleeve": bool(sleeve_on),
                    "weights": _log_book(all_syms, held),
                    # Book as it stood BEFORE the cash -> QQQ swap. Emitted
                    # only when the swap changes what the log actually PRINTS
                    # -- the log rounds to whole percent, and a swap of a few
                    # basis points would otherwise render "A --> A".
                    **({"weights_pre": _log_book(all_syms, held_pre)}
                       if (held_pre is not None
                           and _log_shape(all_syms, held_pre)
                               != _log_shape(all_syms, held)) else {}),
                })
                last_printed = rounded

        held_hist[t] = current_target
        sleeve_hist[t] = sleeve_on
        hurst_hist[t] = cur_hurst

    return BacktestResult(
        dates=idx, equity=equity, weights=held_hist, adjustments=adjustments,
        sleeve_on=sleeve_hist, hurst=hurst_hist, regime=regime_hist,
        n_rebalances=n_rebal, n_sleeve_on=n_on, n_sleeve_off=n_off,
        target=current_target, target_date=last_adj_date, symbols=all_syms,
    )
