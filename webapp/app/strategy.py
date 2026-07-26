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

# Universe.  Index order MUST match the Lite-C IDX_* constants.
TICKERS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "XLE"]
CASH_TICKER = "BIL"          # residual cash weight is held here (cash carry)
N_ASSETS = 9
N_DIMS = 10                  # 9 ETFs + 1 cash dimension
IDX_CASH = 9
IDX_QQQ = 1

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
}

# ---- objective / optimizer ----
WIN_LONG = 252               # buffer depth; every adaptive long window <= this
BLEND_SHORT = 0.6
BLEND_LONG = 0.4
N_RESTARTS = 5
MAX_ITERS = 200
STEP_SIZE = 0.02
LAMBDA_CHURN = 0.05
SIGD_FLOOR = 0.0001
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
H_ENTER = 0.55               # Hurst: switch sleeve ON above this
H_EXIT = 0.45                # Hurst: switch sleeve OFF below this
HURST_WIN = 100              # returns in the DFA window
DFA_SCALES = (10, 15, 25, 30, 50)

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
               w_prev: np.ndarray | None) -> np.ndarray:
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

    out = BLEND_SHORT * (mu_s * ANN / sd_s) + BLEND_LONG * (mu_l * ANN / sd_l)
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


def optimize_weights(R, win_short, win_long, mom, lam, w_prev, has_prev, rng):
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
                                    mom, lam, churn_ref)[0])
        for it in range(MAX_ITERS):
            f = _objective(w[None, :] + bump, R, win_short, win_long,
                           mom, lam, churn_ref)
            grad = (f[0::2] - f[1::2]) / (2.0 * h)
            w = project_simplex(w + STEP_SIZE * grad)
            cur_obj = float(_objective(w[None, :], R, win_short, win_long,
                                       mom, lam, churn_ref)[0])
            if cur_obj - prev_obj < 1e-6 and it > 10:
                break
            prev_obj = cur_obj

        cur_obj = float(_objective(w[None, :], R, win_short, win_long,
                                   mom, lam, churn_ref)[0])
        if cur_obj > best_obj:
            best_obj, best_w = cur_obj, w.copy()
    return best_w, best_obj


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


def _effective_book(weight: np.ndarray, sleeve_on: bool,
                    sleeve_frac: float = SLEEVE_FRAC) -> np.ndarray:
    """Optimizer weights -> the book actually held, length N_ASSETS+1.

    The AllWeather book (9 ETFs + the BIL cash leg) is scaled uniformly by
    aw_frac so every leg keeps its RELATIVE proportion -- the optimizer's
    solution is untouched, the whole book is just levered down to make room
    for the sleeve.  The sleeve then adds on TOP of QQQ's scaled weight (it
    holds the same QQQ the optimizer already trades).  Weights sum to exactly
    1: aw_frac * 1 + sleeve_frac = 1, so there is never account leverage.
    """
    sleeve = sleeve_frac if sleeve_on else 0.0
    aw = 1.0 - sleeve
    held = np.empty(N_ASSETS + 1)
    held[:N_ASSETS] = aw * weight[:N_ASSETS]
    held[IDX_QQQ] += sleeve
    held[N_ASSETS] = aw * weight[IDX_CASH]        # the BIL leg
    return held


def run_backtest(px: dict[str, pd.DataFrame], vix: pd.Series,
                 log_fn=log.info,
                 sleeve_frac: float = SLEEVE_FRAC) -> BacktestResult:
    """Run the strategy over every bar for which all instruments have data.

    px: {ticker: DataFrame with open/high/low/close}, all sharing one index.
    vix: VIX close indexed by the same trading calendar (already forward
         filled); read one bar lagged, exactly like Zorro's GateVIX[1].
    sleeve_frac: fraction of the book tilted into QQQ while the sleeve is ON.

    NOTE: sleeve_frac affects ONLY the effective book, never the optimizer.
    The optimizer reads returns, momentum and VIX; the sleeve ON/OFF state
    comes from the Hurst band and the HA trend candle. Neither depends on
    sleeve_frac, and equity never feeds back into sizing (positions are
    fractional, so there is no lot-rounding path either). So the optimizer
    weights and the sleeve timeline are IDENTICAL across fractions -- the
    variants differ purely in how much of the book the sleeve claims.
    """
    idx = px[TICKERS[0]].index
    n = len(idx)
    rng = np.random.default_rng(RNG_SEED)

    # ---- price matrices, columns in IDX_* order, cash leg last ----
    all_syms = TICKERS + [CASH_TICKER]
    close = np.column_stack([px[s]["close"].to_numpy(float) for s in all_syms])
    open_ = np.column_stack([px[s]["open"].to_numpy(float) for s in all_syms])

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

    pos = np.zeros(N_ASSETS + 1)      # dollar position per leg (incl. BIL)
    cash = CAPITAL                    # uninvested dollars
    pending: np.ndarray | None = None  # book to establish at the next open
    current_target = np.zeros(N_ASSETS + 1)   # book from the last adjustment
    last_adj_date: str | None = None

    equity = np.full(n, np.nan)
    held_hist = np.zeros((n, N_ASSETS + 1))
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

            weight, _ = optimize_weights(R, win_s, win_l, mom, lam,
                                         weight_prev, has_prev, rng)
            weight_prev = weight.copy()
            has_prev = True

        # -------- 4. place orders if anything changed --------
        if do_rebal or (flipped and has_prev):
            held = _effective_book(weight, sleeve_on, sleeve_frac)
            pending = held
            current_target = held
            last_adj_date = idx[t].strftime("%Y-%m-%d")
            tag = "REBAL" if do_rebal else ("to QQQ" if sleeve_on else "to PORT")
            # Only log when the book actually changed at display precision.
            rounded = np.round(held * 100).astype(int)
            if last_printed is None or not np.array_equal(rounded, last_printed):
                adjustments.append({
                    "date": idx[t].strftime("%Y-%m-%d"),
                    "tag": tag,
                    "hurst": round(float(cur_hurst), 3),
                    "sleeve": bool(sleeve_on),
                    "weights": {s: round(float(w), 4)
                                for s, w in zip(all_syms, held) if w > 0.005},
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
