"""
Daily job + cache for the All-Weather strategy tab.

Flow (once a day, alongside the market-picture refresh):

    download prices (Yahoo) + VIX (FRED)
        -> run the backtest over all available history
        -> write data/strategy.json

The web app then only ever reads that JSON, so page loads cost nothing and
the optimizer runs exactly once per day.

The equity curve, the benchmarks and the daily series are all shipped raw
(indexed to 100 at the first bar).  The browser slices and re-bases them for
whatever period the user picks, which is why the period control is instant.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import determinism, fred, settings, strategy as S

log = logging.getLogger(__name__)

# One cache per strategy kind. Separate files rather than one big payload so
# each page load only fetches the variant being viewed.
# `default_frac` is the fraction each tab OPENS on. It differs by kind: 0.75
# is the sweet spot for the plain sleeve, but with a 2x sleeve the drawdown
# grows fast enough past 0.50 that opening any higher would put the most
# flattering-looking curve in front of you by default.
KINDS = {
    # vt_table: brake target per sleeve fraction. Chosen by sweeping every
    # (kind, frac, target) cell and picking the monotone, round-valued table
    # maximising total UPI subject to MaxDD not exceeding the no-brake
    # baseline. UPI rather than Sharpe: Sharpe alone is maximised by pinning
    # the brake at its floor (70% cash forever), which costs 3-11pp of CAGR.
    # Values are deliberately coarse -- adjacent grid targets differ by ~0.05
    # UPI (p90 0.23), which is the same size as the gains, so finer tuning
    # would be fitting noise. 18/18 cells >= the previous linear rule.
    # ntb / w_smooth: no-trade band + weight smoothing on the optimizer book.
    # OFF on every kind, deliberately. On the 9-asset universe the band was a
    # consistent gain (base Sharpe 1.043 -> 1.065, leverage 0.994 -> 1.036),
    # which is why it was built. Adding VBR removed it: re-measured with the
    # 10-asset universe the band's sign FLIPS from cell to cell --
    #     Sharpe delta, band on vs off, all with VBR:
    #     base 0.00 -0.027 | base 0.40 +0.007 | base 0.80 +0.011
    #     leverage 0.40 -0.022 | leverage 0.60 +0.012
    # -- at a magnitude well under the spread between neighbouring cells, i.e.
    # nil. The 50% smoothing is worse than nil (base 0.80: 1.072 -> 1.032).
    #
    # That is the expected result, not a surprise. Both changes fix the SAME
    # defect: an optimizer over-reacting to short-window estimates drawn from
    # too narrow an opportunity set. The band damps the reaction; VBR removes
    # the cause by handing the estimator a genuinely different return stream.
    # Fix the cause and the damping is only lag. They do not add, so only the
    # cause-side fix ships.
    #
    # The mechanism stays wired (strategy.NTB, and the ntb/w_smooth arguments
    # to run_backtest) so this is a one-value change if it is ever wanted back.
    "base":     {"file": "strategy.json",
                 "sleeve": "QQQ",
                 "ntb": 0.0, "w_smooth": 0.0,
                 "title": "All Weather Dynamic",
                 "default_frac": "0.80",
                 # a 1x sleeve barely raises book vol -> flat
                 "vt_table": {"0.00": 0.10, "0.20": 0.10, "0.40": 0.10,
                              "0.60": 0.10, "0.80": 0.10, "1.00": 0.10}},
    "leverage3x": {"file": "strategy_leverage3x.json",
                   "sleeve": S.LEVERAGE3_SLEEVE,
                   "ntb": 0.0, "w_smooth": 0.0,
                   "title": "All Weather Dynamic High Leverage",
                   "default_frac": "0.60",
                   # Quoted at VT_FRAC_BASE (60%) and scaled per fraction by
                   # scaled_vt_target(). A TQQQ book runs far above the 10%
                   # the core book uses, which would pin the brake on and
                   # throttle the sleeve toward 1x.
                   "vt_table": {"0.00": 0.10, "0.20": 0.10, "0.40": 0.15,
                                "0.60": 0.20, "0.80": 0.25, "1.00": 0.35}},
    "leverage": {"file": "strategy_leverage.json",
                 "sleeve": S.LEVERAGE_SLEEVE,
                 "ntb": 0.0, "w_smooth": 0.0,
                 "title": "All Weather Dynamic Leverage",
                 "default_frac": "0.60",
                 "vt_table": {"0.00": 0.10, "0.20": 0.10, "0.40": 0.10,
                              "0.60": 0.12, "0.80": 0.18, "1.00": 0.18}},
}


# every non-core sleeve any kind needs, in a stable order
SLEEVE_EXTRAS = [v["sleeve"] for v in KINDS.values() if v["sleeve"] not in S.TICKERS]
SLEEVE_EXTRAS = list(dict.fromkeys(SLEEVE_EXTRAS))


def _vt_for(kind: str, frac: float) -> float:
    """Brake target for this kind at this sleeve fraction (table, else formula)."""
    k = KINDS[kind]
    tbl = k.get("vt_table")
    if tbl and _frac_key(frac) in tbl:
        return float(tbl[_frac_key(frac)])
    return S.scaled_vt_target(k.get("vt_target", S.VT_TARGET), frac)


def default_frac(kind: str = "base") -> str:
    return KINDS.get(kind, KINDS["base"]).get("default_frac", DEFAULT_FRAC)


def cache_path(kind: str = "base"):
    return settings.DATA_DIR / KINDS[kind]["file"]


CACHE_PATH = settings.DATA_DIR / "strategy.json"      # base, for compatibility
LOG_PATH = settings.DATA_DIR / "strategy_adjustments.log"

# How much history to pull.  BIL (the cash leg) only starts 2007-05-30, which
# is what actually binds the start of the backtest; asking for more is free.
DOWNLOAD_START = "2006-01-01"

# Default window the dashboard opens on.
DEFAULT_YEARS = 5


# =====================================================================
# Downloads
# =====================================================================
def fetch_prices(log_fn=log.info) -> dict[str, pd.DataFrame]:
    """Daily OHLC for the 9 ETFs + BIL, split- and dividend-adjusted.

    auto_adjust=True back-adjusts history from the latest bar, so the most
    recent close is the real traded price (what the share counts in the CSV
    export need) while the history is total-return consistent (what the .t6
    files the Zorro version reads are).
    """
    import yfinance as yf

    # QLD is downloaded alongside but deliberately kept OUT of the calendar
    # intersection below: if it ever started later than BIL it would silently
    # truncate the plain strategy's history too.
    syms = S.TICKERS + [S.CASH_TICKER] + SLEEVE_EXTRAS
    log_fn(f"Downloading {len(syms)} symbols from Yahoo: {', '.join(syms)}")
    # threads=False on purpose. A threaded multi-symbol fetch can return a
    # partial or rate-limited response for one symbol on one day; the
    # .dropna() below then removes that bar from that symbol, the calendar
    # intersection removes it from EVERY symbol, and because the rebalance
    # cadence counts BARS rather than dates (see run_backtest), every
    # subsequent rebalance for the next ~19 years lands on a different day.
    # One dropped bar is a visibly different equity curve. Serial fetching
    # is a few seconds slower once a day and removes the whole failure mode.
    raw = yf.download(syms, start=DOWNLOAD_START, auto_adjust=True,
                      progress=False, group_by="column", threads=False)
    if raw is None or raw.empty:
        raise RuntimeError("Yahoo returned no price data")

    frames: dict[str, pd.DataFrame] = {}
    for s in syms:
        df = pd.DataFrame({
            "open": raw["Open"][s], "high": raw["High"][s],
            "low": raw["Low"][s], "close": raw["Close"][s],
        }).dropna()
        if df.empty:
            raise RuntimeError(f"Yahoo returned no data for {s}")
        df.index = pd.to_datetime(df.index)
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.index = df.index.normalize()
        frames[s] = df

    # Trade only bars where every CORE instrument printed, mirroring the
    # "require all assets present" gate in the Zorro/QC versions. The
    # leveraged sleeve is aligned to that calendar afterwards rather than
    # being allowed to shorten it.
    core = S.TICKERS + [S.CASH_TICKER]
    common = None
    for s in core:
        common = frames[s].index if common is None \
            else common.intersection(frames[s].index)
    common = common.sort_values()
    for s in core:
        frames[s] = frames[s].loc[common]

    # Sleeve instruments are aligned to the core calendar afterwards rather
    # than being allowed to shorten it. A sleeve younger than the calendar
    # keeps its NaNs: run_backtest holds the sleeve off over that stretch
    # instead of the whole variant being dropped.
    for lev in SLEEVE_EXTRAS:
        aligned = frames[lev].reindex(common)
        missing = int(aligned["close"].isna().sum())
        if missing == len(common):
            log_fn(f"  {lev}: no overlapping history; variant unavailable")
            frames.pop(lev, None)
            continue
        if missing:
            log_fn(f"  {lev}: {missing} of {len(common)} bars before inception; "
                   f"sleeve held off there")
        frames[lev] = aligned

    log_fn(f"  {len(common)} aligned bars "
           f"{common[0].date()} .. {common[-1].date()}")
    return frames


# NBER-dated US recessions. Short, authoritative and rarely revised, so they
# are listed rather than downloaded; market drawdowns below are computed from
# the data so a future bear market needs no code change.
NBER_RECESSIONS = [("2001-03-01", "2001-11-30", "Dot-com"),
                   ("2007-12-01", "2009-06-30", "GFC"),
                   ("2020-02-01", "2020-04-30", "COVID")]

# Names for computed drawdowns, keyed by the year the fall began. Anything not
# listed falls back to "<year> bear", so a future episode is still labelled
# without a code change -- it just gets a generic name until someone adds one.
DRAWDOWN_NAMES = {2000: "Dot-com", 2007: "GFC", 2020: "COVID"}

# Named market events that fall UNDER the 20% drawdown threshold, so the
# automatic detector never sees them. Listed explicitly, with the dates the
# selloff ran rather than the whole episode.
#   Liberation Day: tariffs announced 2025-04-02; the S&P fell ~12% over the
#     next four sessions and bottomed 04-08, rebounding hard on the 04-09 pause.
#   Iran war: joint US-Israeli strikes on 2026-02-28 opened the conflict; the
#     band starts at the 02-27 close, the last session before it. The Strait of
#     Hormuz closed 03-04 and SPY bottomed 2026-03-30 at -8.9% from its 01-27
#     peak, recovering as an early-April ceasefire proposal emerged.
#     (An earlier Israel-Iran exchange in June 2025 is a separate, much smaller
#     episode and is not shaded.)
EVENTS = [("2025-04-02", "2025-04-08", "Liberation Day"),
          ("2026-02-27", "2026-03-30", "Iran war")]


def _episode(start, trough, worst) -> dict:
    yr = start.year
    return {"from": start.strftime("%Y-%m-%d"),
            "to": trough.strftime("%Y-%m-%d"),
            "depth": round(worst * 100.0, 1),
            "label": DRAWDOWN_NAMES.get(yr, f"{yr} bear")}


def drawdown_episodes(close: pd.Series, thresh: float = 0.20):
    """Peak-to-TROUGH spans where SPY fell more than `thresh` from its high.

    Ends at the trough rather than at full recovery: recovery from 2007 took
    until 2012, and shading that whole span would tint most of the chart
    instead of marking the drop. Derived from the price series, so a future
    bear market appears without a code change.
    """
    c = close.dropna()
    if c.empty:
        return []
    peak = c.cummax()
    dd = c / peak - 1.0
    out, inside, start, worst, trough = [], False, None, 0.0, None
    for dt, d in dd.items():
        if not inside:
            if d <= -thresh:
                inside = True
                start = c.loc[:dt].idxmax()      # the high the fall began from
                worst, trough = float(d), dt
        else:
            if d < worst:
                worst, trough = float(d), dt     # track the low water mark
            if d >= 0.0:                          # recovered -> close the span
                out.append(_episode(start, trough, worst))
                inside = False
    if inside:
        out.append(_episode(start, trough, worst))
    return out


# FRED's fredgraph.csv endpoint throttles bursts from one IP, and a full update
# hits it ~35 times. data_pipeline retries its own calls; these two need the
# same treatment or --strategy-only gets none of it.
def fetch_long_yield(log_fn=log.info) -> pd.Series | None:
    """DGS10 from FRED as a decimal (4.2% -> 0.042).

    Drives the rate-tied Sortino constant. Returning None is safe: the
    backtest then falls back to plain Sortino rather than failing.
    """
    try:
        s_ = fred.fetch_series("DGS10", DOWNLOAD_START, _utc_today(),
                               log=log_fn) / 100.0
        s_.index = pd.to_datetime(s_.index).normalize()
        log_fn(f"  yield: {len(s_)} FRED DGS10 observations, "
               f"last {s_.iloc[-1]*100:.2f}%")
        return s_
    except Exception as exc:                        # pragma: no cover
        log_fn(f"  yield: FRED DGS10 failed ({exc}); "
               f"falling back to plain Sortino")
        return None


def fetch_vix(log_fn=log.info) -> pd.Series:
    """VIXCLS from FRED -- the same series the Zorro build reads from
    History\\VIXCLS.csv, so the 18/25 regime thresholds fire on the same days.
    Falls back to Yahoo's ^VIX if FRED is unreachable."""
    try:
        s = fred.fetch_series("VIXCLS", DOWNLOAD_START, _utc_today(),
                              log=log_fn)
        s.index = pd.to_datetime(s.index).normalize()
        log_fn(f"  VIX: {len(s)} FRED VIXCLS observations")
        return s
    except Exception as exc:                       # pragma: no cover
        log_fn(f"  VIX: FRED failed ({exc}); falling back to Yahoo ^VIX")
        import yfinance as yf
        df = yf.download("^VIX", start=DOWNLOAD_START, auto_adjust=False,
                         progress=False)
        s = df["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.dropna()
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        s.index = s.index.normalize()
        return s


# =====================================================================
# Metrics  (mirrors the QC-style block in the .c: no risk-free rate,
# trading-day sampling, equity-to-equity drawdown)
# =====================================================================
def compute_stats(equity: np.ndarray) -> dict:
    eq = np.asarray(equity, dtype=float)
    if eq.size < 3:
        return {}
    r = eq[1:] / eq[:-1] - 1.0
    r = r[np.isfinite(r)]
    n = r.size
    years = n / 252.0
    total = eq[-1] / eq[0] - 1.0
    cagr = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    sd = r.std(ddof=1)
    down = np.minimum(r, 0.0)
    sd_down = math.sqrt(float((down * down).sum()) / n)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    ulcer = math.sqrt(float(((100.0 * dd) ** 2).mean()))
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": sd * math.sqrt(252.0),
        "down_volatility": sd_down * math.sqrt(252.0),
        "sharpe": (r.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0,
        "sortino": (r.mean() * math.sqrt(252.0) / sd_down) if sd_down > 0 else 0.0,
        "ulcer": ulcer,
        # Ulcer Performance Index, a.k.a. the Martin ratio: return per unit of
        # drawdown pain rather than per unit of volatility. Consistent with the
        # Sharpe and Sortino above, no risk-free rate is subtracted. CAGR is
        # scaled to percent because the Ulcer Index is already in percentage
        # points, and the ratio is only meaningful with matching units.
        "upi": ((cagr * 100.0) / ulcer) if ulcer > 0 else 0.0,
        "max_drawdown": float(dd.max()),
        "years": years,
    }


# =====================================================================
# Build the cached payload
# =====================================================================
# The sleeve fractions we precompute.  All three share one data download and
# one set of optimizer weights (the sleeve fraction does not feed back into
# the optimization -- see run_backtest's docstring), so the extra cost is just
# the position accounting.
SLEEVE_FRACS = (0.00, 0.20, 0.40, 0.60, 0.80, 1.00)
# 0.00 is a useful baseline: the sleeve gate still evaluates but tilts nothing,
# so that variant IS the plain AllWeather book. The list is shared by every
# kind, so a run costs len(KINDS) * len(SLEEVE_FRACS) backtests.
DEFAULT_FRAC = "0.75"

# Bump whenever the SHAPE or COMPLETENESS of the cached payload changes (new
# fields, a truncation lifted, a different variant set). The page compares the
# cache's stamp against this and says so if the cache is older, instead of
# silently serving stale data that looks fine -- which is exactly how a
# lifted 250-entry log cap went unnoticed.
PAYLOAD_VERSION = 6


def _frac_key(f: float) -> str:
    return f"{f:.2f}"


def _utc_today() -> date:
    """Today in UTC, not in the machine's local timezone.

    This is an INPUT to the backtest, not a display value: it becomes FRED's
    observation_end, which sets the tail of DGS10, which goes through a
    252-day rolling mean into the rate-tied Sortino constant, which sets the
    weights at the final rebalance -- the allocation actually traded.

    date.today() is the local civil date, so a UTC server and a US-Pacific
    desktop running at the same instant would ask FRED for different end
    dates and get different answers. UTC makes the request identical
    everywhere. (VIX was accidentally safe already: run_backtest reads it one
    bar lagged, so a missing final observation is never looked at.)
    """
    return datetime.now(timezone.utc).date()


_UNSET = object()      # distinguishes "not supplied" from "fetched and failed"


def build_payload(log_fn=log.info, kind: str = "base",
                  px: dict | None = None, vix=None, long_yield=_UNSET) -> dict:
    sleeve_symbol = KINDS[kind]["sleeve"]
    if px is None:
        px = fetch_prices(log_fn=log_fn)
    if vix is None:
        vix = fetch_vix(log_fn=log_fn)
    if long_yield is _UNSET:
        long_yield = fetch_long_yield(log_fn=log_fn)
    # a kind can opt out of the rate-tied objective entirely (v3.9.2 tab)
    if not KINDS[kind].get("rate_tied", True):
        long_yield = None
    # A missing yield silently reverts the objective to plain Sortino and the
    # numbers change, so say so in the payload rather than only in the log.
    # only warn when the yield was WANTED and missing; the v3.9.2 tab uses
    # plain Sortino by design, which is not a degradation
    warnings = []
    if KINDS[kind].get("rate_tied", True) and long_yield is None:
        warnings = ["DGS10 unavailable - rate-tied Sortino disabled "
                    "(plain Sortino used)"]
    if sleeve_symbol not in S.TICKERS and sleeve_symbol not in px:
        raise RuntimeError(
            f"No price history for {sleeve_symbol}; cannot build the "
            f"{kind} strategy.")

    # ---- benchmarks and the shared calendar, from the first run ----
    # Consolidation only bites when the sleeve is a SEPARATE leveraged leg;
    # the base kind's sleeve is QQQ itself, so there is nothing to convert.
    can_consolidate = sleeve_symbol in S.SLEEVE_LEVERAGE

    def run_set(yield_series, label, brake, consol):
        out, head = {}, None
        for frac in SLEEVE_FRACS:
            log_fn(f"[{kind}] backtesting sleeve fraction {frac:.2f} "
                   f"({label}) ...")
            res = S.run_backtest(px, vix, log_fn=log_fn, sleeve_frac=frac,
                                 sleeve_symbol=sleeve_symbol,
                                 long_yield=yield_series,
                                 vol_target=brake,
                                 vt_target=_vt_for(kind, frac),
                                 consolidate=consol,
                                 ntb=KINDS[kind].get("ntb", 0.0),
                                 w_smooth=KINDS[kind].get("w_smooth", 0.0))
            if head is None:
                head = res
            out[_frac_key(frac)] = res
        return out, head

    brake_on = KINDS[kind].get("vol_target", True)
    variants, first = run_set(long_yield, "rate-tied Sortino",
                              brake_on, can_consolidate)
    # Second pass with the brake off, for the panel toggle. Consolidation is
    # always on -- it is exposure-neutral and measured better in every window,
    # so it is simply part of the strategy rather than an option.
    variants_nobrake = (run_set(long_yield, "no vol brake", False,
                                can_consolidate)[0]
                        if (settings.STRATEGY_VT_AB and brake_on) else None)

    trim_from = first.dates[max(S.WARMUP, S.WIN_LONG + 1)]

    def trimmed(res):
        eq = pd.Series(res.equity, index=res.dates).dropna()
        return eq[eq.index >= trim_from]

    idx = trimmed(first).index
    spy = px["SPY"]["close"].reindex(idx)
    qqq = px["QQQ"]["close"].reindex(idx)

    def idx100(s):
        a = np.asarray(s, dtype=float)
        return np.round(100.0 * a / a[0], 4).tolist()

    def book_steps(res):
        """Step-encode the held book.

        held_hist only changes on adjustment bars, so a dense (bars x legs)
        matrix would be ~99% repeated rows. Emit [row, w0..wN] per CHANGE, in
        per-mille integers; the client forward-fills. Keeps the payload small
        enough that the band chart costs ~40 KB rather than ~350 KB.
        """
        w = (pd.DataFrame(res.weights, index=res.dates, columns=res.symbols)
             .reindex(idx).fillna(0.0).to_numpy(float))
        out, prev = [], None
        for i in range(w.shape[0]):
            row = np.round(w[i] * 1000.0).astype(int)
            if prev is None or not np.array_equal(row, prev):
                out.append([i] + row.tolist())
                prev = row
        return out

    last_px = {s: float(px[s]["close"].iloc[-1]) for s in first.symbols}

    # ---- per-fraction blocks ----
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    var_out = {}
    def serialise(vdict, write_logs):
        var_out = {}
        for key, res in vdict.items():
            eq = trimmed(res)
            alloc = [
                {"symbol": s, "name": S.HOLDING_NAMES.get(s, s),
                 "weight": float(w), "price": last_px[s]}
                for s, w in zip(res.symbols, res.target) if w > 0.0005
            ]
            alloc.sort(key=lambda a: a["symbol"])
            var_out[key] = {
                "series": idx100(eq.to_numpy()),
                "stats": compute_stats(eq.to_numpy()),
                "allocation": alloc,
                "allocation_date": res.target_date,
                "adjustments": [{k: v for k, v in a.items() if k != "sleeve"}
                                for a in res.adjustments],
                "n_adjustments": len(res.adjustments),
                # step-encoded weights driving the composition bands
                "book": book_steps(res),
            }
            if not write_logs:
                continue
            # full adjustment log per fraction, mirroring the Zorro [ADJ ...] lines
            path = (settings.DATA_DIR /
                    f"strategy_adjustments_{kind}_{key.replace('.', '')}.log")
            with path.open("w", encoding="utf-8") as fh:
                fh.write(f"# AllWeather9 v6.3.1  {kind}  SLEEVE_FRAC={key}  "
                         f"generated {datetime.now(timezone.utc).isoformat()}\n")
                for a in res.adjustments:
                    legs = " ".join(f"{k}={v*100:.0f}%" for k, v in a["weights"].items())
                    fh.write(f"[ADJ {a['tag']:<7}] {a['date']} H={a['hurst']:.2f} {legs}\n")

        return var_out

    var_out = serialise(variants, True)
    var_nobrake = (serialise(variants_nobrake, False)
                   if variants_nobrake else None)

    # ---- cash-carry sanity check --------------------------------------
    # auto_adjust=True back-adjusts for distributions, so BIL's series is a
    # TOTAL-return series and the residual cash weight really does earn the
    # bill rate.  Publishing the realised annualised figure makes that
    # checkable at a glance: it should track the average 1-3 month T-bill
    # yield over the window.  If it ever prints ~0%, the adjustment is not
    # coming through and the cash leg is silently earning nothing.
    bil = px[S.CASH_TICKER]["close"].reindex(idx).to_numpy(float)
    bil_years = len(bil) / 252.0
    bil_cagr = ((bil[-1] / bil[0]) ** (1.0 / bil_years) - 1.0) if bil_years > 0 else None

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": idx[-1].strftime("%Y-%m-%d"),
        "start": idx[0].strftime("%Y-%m-%d"),
        "default_years": DEFAULT_YEARS,
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        # benchmarks and everything the sleeve fraction cannot change are
        # stored once, not per variant
        "benchmarks": {"SPY": idx100(spy.to_numpy()), "QQQ": idx100(qqq.to_numpy())},
        "bench_stats": {"SPY": compute_stats(spy.to_numpy()),
                        "QQQ": compute_stats(qqq.to_numpy())},
        "fracs": [_frac_key(f) for f in SLEEVE_FRACS],
        "default_frac": KINDS[kind].get("default_frac", DEFAULT_FRAC),
        "payload_version": PAYLOAD_VERSION,
        "warnings": warnings,
        # Context bands for the charts, drawn beneath every trace. Recessions
        # are NBER-dated; drawdowns are computed from SPY so they stay current.
        "shades": {
            "recession": [{"from": a, "to": b, "label": t}
                          for a, b, t in NBER_RECESSIONS],
            # full history, not `idx`: the trimmed window starts after the
            # GFC's Oct-2007 peak, which would misdate it as a 2008 episode.
            # The client clips bands to whatever period is on screen.
            "drawdown": drawdown_episodes(px["SPY"]["close"]),
            "event": [{"from": a, "to": b, "label": t} for a, b, t in EVENTS],
        },
        # leg order for the "book" steps above; differs by kind (QLD only on
        # the leveraged variant), so the client reads it rather than assuming.
        "legs": list(first.symbols),
        "kind": kind,
        "title": KINDS[kind]["title"],
        "sleeve_symbol": sleeve_symbol,
        "variants": var_out,
        "variants_nobrake": var_nobrake,
        "can_consolidate": can_consolidate,
        "sleeve_on": bool(first.sleeve_on[-1]) if first.sleeve_on is not None else False,
        "hurst": (round(float(first.hurst[-1]), 3)
                  if first.hurst is not None and np.isfinite(first.hurst[-1]) else None),
        "bil_cagr": bil_cagr,
        "n_rebalances": first.n_rebalances,
        "n_sleeve_on": first.n_sleeve_on,
        "n_sleeve_off": first.n_sleeve_off,
        # The environment that produced these numbers. Stamped in so a cached
        # curve can always be attributed: if two machines disagree, diffing
        # this block says which layer to look at (versions, BLAS kernel, SIMD)
        # instead of guessing. Same dict the selftest prints.
        "environment": determinism.fingerprint(),
        "config": {
            "universe": S.TICKERS, "cash": S.CASH_TICKER,
            "max_weight": S.MAX_WEIGHT,
            "hurst_enter": S.H_ENTER, "hurst_exit": S.H_EXIT,
            "hurst_win": S.HURST_WIN, "ha_span": S.HA_SPAN_BARS,
            "vix_high": S.VIX_HIGH, "vix_mid": S.VIX_MID,
            "sleeve_symbol": sleeve_symbol,
        },
    }
    return payload


def run_strategy_update(log_fn=log.info) -> dict:
    """Build every strategy kind. The download and the VIX pull are shared, so
    the extra cost of the leveraged variant is backtest time only."""
    px = fetch_prices(log_fn=log_fn)
    vix = fetch_vix(log_fn=log_fn)
    long_yield = fetch_long_yield(log_fn=log_fn)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

    payloads = {}
    for kind in KINDS:
        sleeve = KINDS[kind]["sleeve"]
        if sleeve not in S.TICKERS and sleeve not in px:
            log_fn(f"  skipping '{kind}': no {sleeve} history")
            continue
        payload = build_payload(log_fn=log_fn, kind=kind, px=px, vix=vix,
                             long_yield=long_yield)
        cache_path(kind).write_text(json.dumps(payload, separators=(",", ":")),
                                    encoding="utf-8")
        payloads[kind] = payload
        log_fn(f"  {kind} cached -> {cache_path(kind)}  "
               f"(sleeve = {sleeve})")
        log_fn(f"  {payload['start']}..{payload['as_of']}  "
               f"{payload['n_rebalances']} rebalances")
        for key in payload["fracs"]:
            st = payload["variants"][key]["stats"]
            log_fn(f"    SLEEVE_FRAC {key}:  CAGR {st['cagr']*100:6.2f}%  "
                   f"Sharpe {st['sharpe']:.3f}  Sortino {st['sortino']:.2f}  "
                   f"MaxDD {st['max_drawdown']*100:6.2f}%")
    payload = payloads.get("base") or next(iter(payloads.values()))
    bc = payload.get("bil_cagr")
    if bc is not None:
        log_fn(f"  BIL cash carry over the window: {bc*100:.2f}%/yr "
               f"(should track the average 1-3 month T-bill yield; "
               f"~0% would mean distributions are not being adjusted in)")
    return payload


def load_cached(kind: str = "base") -> dict | None:
    path = cache_path(kind)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def is_fresh(payload: dict | None) -> bool:
    """True when the cache was built today (local time)."""
    if not payload:
        return False
    try:
        gen = datetime.fromisoformat(payload["generated_at"])
        return gen.astimezone().date() == date.today()
    except Exception:
        return False


# =====================================================================
# Logical Invest -- format allocation export
# =====================================================================
def allocations_csv(payload: dict, investment: float = 100_000.0,
                    frac: str | None = None) -> str:
    """Reproduce the Logical Invest "Allocations.csv" layout byte for byte:

        ""
        "Symbol","Holding","Weight","Amount","Price","Shares"
        "SPY","SPDR S&P 500 ETF Trust","5.0%","$5,000","$521.95","9"
        ...
        "Total Allocation","","(adjust leverage here)"

    Every field is quoted, lines are CRLF, weights carry one decimal, amounts
    are whole dollars with thousands separators, and share counts are floored
    -- all matching the sample file so the existing Python automation that
    reads it needs no changes.

    `frac` selects which sleeve-fraction variant to export; it defaults to the
    dashboard's default fraction.
    """
    key = frac or payload.get("default_frac", DEFAULT_FRAC)
    variant = payload.get("variants", {}).get(key)
    if variant is None:
        raise KeyError(f"no such sleeve fraction: {key}")

    buf = io.StringIO(newline="")
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow([""])
    w.writerow(["Symbol", "Holding", "Weight", "Amount", "Price", "Shares"])
    for a in variant.get("allocation", []):
        amount = round(investment * a["weight"])
        price = a["price"]
        shares = int(amount // price) if price > 0 else 0
        w.writerow([
            a["symbol"], a["name"],
            f"{a['weight']*100:.1f}%",
            f"${amount:,.0f}",
            f"${price:,.2f}",
            f"{shares:d}",
        ])
    # Trailing marker row: three fields, exactly as the sample emits it.
    w.writerow(["Total Allocation", "", "(adjust leverage here)"])
    return buf.getvalue()
