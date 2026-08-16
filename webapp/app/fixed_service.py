"""
Daily job + cache for the "All Weather Fixed" tab.

Two static, buy-and-hold-with-annual-rebalance portfolios that sit BEFORE the
dynamic All-Weather tabs. They exist for people who cannot (or would rather
not) let an optimizer move their book every week -- a 401(k), an IRA, or one
of the new "Trump accounts" where you might change the allocation once or
twice a YEAR rather than once or twice a day:

    Fixed A -- "Golden Butterfly"   (lowest maintenance, tightest drawdown)
        20% VTI  total US market
        20% IJS  small-cap value
        20% TLT  long-term Treasuries
        20% SHY  short-term Treasuries
        20% GLD  gold

    Fixed B -- "Equity-tilted All-Weather"  (reaches harder for ~10%)
        40% VTI  total US market
        15% IJS  small-cap value
        20% TLT  long-term Treasuries
        10% IEF  intermediate Treasuries
        10% GLD  gold
         5% DBC  broad commodities

Flow mirrors strategy_service: download once a day, backtest over all shared
history, cache the JSON.  The browser slices/re-bases for whatever period the
user picks, exactly like the dynamic tab, so the period control is instant.

Each portfolio carries its OWN calendar (the intersection of only the funds it
holds) so Fixed A is not shortened to Fixed B's start just because B also holds
a younger commodity fund.  Benchmarks (SPY, QQQ) and the SPY-derived drawdown
shading are therefore computed per section, over that section's window.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import settings, strategy as S
from .strategy_service import (
    DOWNLOAD_START, NBER_RECESSIONS, EVENTS, compute_stats, drawdown_episodes,
)

log = logging.getLogger(__name__)

VERSION = "v6.3.1"

# Bump whenever the SHAPE of the cached payload changes, so the page can tell a
# stale cache from a current one (same contract as PAYLOAD_VERSION next door).
# v2: each section now ships an equity curve per rebalance schedule.
PAYLOAD_VERSION = 2

# Rebalance schedules offered by the "for evaluation only" dropdown. The value
# is the set of MONTHS whose first trading day triggers a rebalance back to
# target; an empty set is pure buy-and-hold (weights drift forever). All four
# are precomputed so the dropdown switches instantly in the browser, exactly
# like the dynamic tab's sleeve-fraction variants. The schedule changes only
# the historical curve and its statistics -- never the target allocation or the
# CSV export, which are always the current book.
REBAL_MODES = {
    "none": set(),                # buy & hold, never rebalance
    "annual": {1},                # 1st trading day of Jan
    "semi": {1, 7},               # Jan, Jul
    "quarterly": {1, 4, 7, 10},   # Jan, Apr, Jul, Oct
}
REBAL_ORDER = ["none", "annual", "semi", "quarterly"]
DEFAULT_REBAL = "annual"

CACHE_PATH = settings.DATA_DIR / "strategy_fixed.json"

# Default window the dashboard opens on (years). Matches the dynamic tab.
DEFAULT_YEARS = 5

# Full names, for the Logical-Invest-format allocation export and the holdings
# table. Long-history proxies are chosen deliberately: IJS (small-cap value,
# 2000) over AVUV (2019) so the backtest can span 2008, and DBC (2006) for the
# commodity sleeve. The dashboard notes the tradeable alternatives (AVUV/VBR,
# GLDM, SCHP) in the UI.
HOLDING_NAMES = {
    "VTI": "Vanguard Total Stock Market ETF",
    "IJS": "iShares S&P Small-Cap 600 Value ETF",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "SHY": "iShares 1-3 Year Treasury Bond ETF",
    "GLD": "SPDR Gold Shares",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "DBC": "Invesco DB Commodity Index Tracking Fund",
    "BND": "Vanguard Total Bond Market ETF",
}

# Portfolios. Weights MUST sum to 1.0 (asserted below). Order here is the order
# shown in the pie and the holdings table.
PORTFOLIOS = {
    "A": {
        "name": "Classical Fixed A",
        "subtitle": "60/40",
        "blurb": "The textbook 60% stocks / 40% bonds balanced portfolio -- the "
                 "most common benchmark in the industry. Included for reference, "
                 "not as a recommended strategy; rebalanced once a year.",
        "rebalance": "annual",
        # The classic balanced portfolio: US total market + US aggregate bonds.
        "weights": [("VTI", 0.60), ("BND", 0.40)],
    },
    "B": {
        "name": "Classical Fixed B",
        "subtitle": "Golden Butterfly",
        "blurb": "Five equal fifths. The lowest-maintenance mix and the "
                 "tightest historical drawdown; rebalanced once a year.",
        "rebalance": "annual",
        "weights": [("VTI", 0.20), ("IJS", 0.20), ("TLT", 0.20),
                    ("SHY", 0.20), ("GLD", 0.20)],
    },
    "C": {
        "name": "Classical Fixed C",
        "subtitle": "Equity-tilted All-Weather",
        "blurb": "~55% US equity (with a small-cap value tilt), duration-"
                 "balanced Treasuries, and a 20% gold anchor. Weights optimized "
                 "on 2006-2026 history for a better risk-adjusted return "
                 "(Sharpe) than a plain 60/40; rebalanced once a year.",
        "rebalance": "annual",
        # Our optimized fixed mix. Optimized for long-run Sharpe on the
        # project's own price history (annual rebalance, 2006-2026). Two changes
        # did the work vs a plain equity-tilted mix: commodities (DBC) dropped
        # -- a persistent return/Sharpe drag over this window -- and gold raised
        # to 20%, whose risk-adjusted return and crisis diversification beat
        # commodities decisively. Duration is split between long (TLT) and
        # intermediate (IEF). An earlier international (EFA) sleeve was removed:
        # developed-international both lowered return AND failed to cut drawdown
        # (equity correlations spike in crises). Dominates a plain 60/40 on
        # return, Sharpe, Sortino and MaxDD.
        "weights": [("VTI", 0.45), ("IJS", 0.10), ("TLT", 0.10),
                    ("IEF", 0.15), ("GLD", 0.20)],
    },
}
SECTION_ORDER = ["A", "B", "C"]

# Benchmarks drawn on every section, same as the dynamic tab.
BENCHMARKS = ["SPY", "QQQ"]

for _k, _p in PORTFOLIOS.items():
    _tot = round(sum(w for _, w in _p["weights"]), 6)
    assert _tot == 1.0, f"portfolio {_k} weights sum to {_tot}, not 1.0"


def _all_tickers() -> list[str]:
    """Every symbol any section needs, plus benchmarks, de-duplicated."""
    syms: list[str] = []
    for p in PORTFOLIOS.values():
        syms += [s for s, _ in p["weights"]]
    syms += BENCHMARKS
    return list(dict.fromkeys(syms))


# =====================================================================
# Downloads
# =====================================================================
def fetch_prices(log_fn=log.info) -> dict[str, pd.Series]:
    """Adjusted daily CLOSE per symbol, split- and dividend-adjusted.

    auto_adjust=True back-adjusts from the latest bar, so the final close is
    the real traded price (what the CSV share counts need) while history is
    total-return consistent (what the equity curve needs). One Series per
    symbol, indexed by naive midnight timestamps.
    """
    import yfinance as yf

    syms = _all_tickers()
    log_fn(f"[fixed] downloading {len(syms)} symbols from Yahoo: "
           f"{', '.join(syms)}")
    # threads=False for the same reason as in strategy_service.fetch_prices:
    # a partial threaded response drops a bar from the shared calendar.
    raw = yf.download(syms, start=DOWNLOAD_START, auto_adjust=True,
                      progress=False, group_by="column", threads=False)
    if raw is None or raw.empty:
        raise RuntimeError("Yahoo returned no price data for the fixed tab")

    out: dict[str, pd.Series] = {}
    close = raw["Close"]
    for s in syms:
        ser = (close[s] if isinstance(close, pd.DataFrame) else close).dropna()
        if ser.empty:
            raise RuntimeError(f"Yahoo returned no data for {s}")
        ser.index = pd.to_datetime(ser.index)
        if getattr(ser.index, "tz", None) is not None:
            ser.index = ser.index.tz_localize(None)
        ser.index = ser.index.normalize()
        out[s] = ser.astype(float)
    return out


# =====================================================================
# Backtest: fixed weights, rebalanced on the first trading bar of each year
# =====================================================================
def _rebalance_bars(index: pd.DatetimeIndex, months: set[int]) -> set[int]:
    """Row positions to rebalance on, for a given set of trigger months.

    A bar rebalances when it is the FIRST trading day of a month in `months`
    (detected as the month changing from the previous bar). Bar 0 is always a
    rebalance -- it is the initial purchase. An empty `months` therefore yields
    just {0}: buy once and never rebalance.
    """
    bars = {0}
    if not months:
        return bars
    m = index.month.to_numpy()
    for i in range(1, len(m)):
        if m[i] != m[i - 1] and int(m[i]) in months:
            bars.add(i)
    return bars


def backtest_fixed(prices: pd.DataFrame, weights: np.ndarray,
                   rebal_bars: set[int]) -> np.ndarray:
    """Equity curve of a fixed-weight book for a given rebalance schedule.

    `prices` is [dates x assets] aligned and NaN-free; `weights` aligns to its
    columns and sums to 1; `rebal_bars` is the set of row positions to snap back
    to target on. Holdings are carried in shares so the book DRIFTS between
    rebalances (a runaway winner really does grow its share) and is reset to
    target on each rebalance bar -- which is the whole point of rebalancing and
    the reason the curve differs from a daily-reweighted one.
    """
    p = prices.to_numpy(float)
    n = p.shape[0]
    equity = np.empty(n, float)
    shares = weights / p[0]          # value starts at exactly 1.0
    equity[0] = float((shares * p[0]).sum())
    for i in range(1, n):
        val = float((shares * p[i]).sum())
        equity[i] = val
        if i in rebal_bars:
            shares = weights * val / p[i]
    return equity


def _idx100(a) -> list[float]:
    a = np.asarray(a, dtype=float)
    return np.round(100.0 * a / a[0], 4).tolist()


def _section_calendar(prices: dict[str, pd.Series],
                      symbols: list[str]) -> pd.DatetimeIndex:
    """Trading days on which EVERY symbol in this section printed."""
    common = None
    for s in symbols:
        idx = prices[s].index
        common = idx if common is None else common.intersection(idx)
    return common.sort_values()


def build_section(key: str, prices: dict[str, pd.Series],
                  log_fn=log.info) -> dict:
    p = PORTFOLIOS[key]
    syms = [s for s, _ in p["weights"]]
    weights = np.array([w for _, w in p["weights"]], float)

    # Calendar from THIS section's funds plus the benchmarks it draws, so the
    # strategy and its benchmarks share an x-axis and start together.
    cal = _section_calendar(prices, syms + BENCHMARKS)
    if len(cal) < 260:
        raise RuntimeError(
            f"[fixed] section {key}: only {len(cal)} shared bars; "
            f"need at least ~1y of overlap")

    frame = pd.DataFrame({s: prices[s].reindex(cal) for s in syms}).dropna()
    cal = frame.index

    # One equity curve per rebalance schedule, all indexed to 100 at the shared
    # start so the dropdown can switch instantly with no re-fetch.
    series_by_rebal = {}
    for mode, months in REBAL_MODES.items():
        bars = _rebalance_bars(cal, months)
        series_by_rebal[mode] = _idx100(backtest_fixed(frame, weights, bars))
    # The default schedule's curve is also published under "series" so any
    # reader that does not know about the dropdown still gets a sensible book.
    equity = np.asarray(series_by_rebal[DEFAULT_REBAL], float)

    last_px = {s: float(prices[s].reindex(cal).iloc[-1]) for s in syms}
    allocation = [
        {"symbol": s, "name": HOLDING_NAMES.get(s, s),
         "weight": float(w), "price": last_px[s]}
        for s, w in p["weights"]
    ]

    benches, bench_stats = {}, {}
    for b in BENCHMARKS:
        bser = prices[b].reindex(cal).to_numpy(float)
        benches[b] = _idx100(bser)
        bench_stats[b] = compute_stats(bser)

    spy_close = prices["SPY"].reindex(cal)
    log_fn(f"[fixed] section {key} ({p['subtitle']}): {len(cal)} bars "
           f"{cal[0].date()}..{cal[-1].date()}  "
           f"CAGR {compute_stats(equity)['cagr']*100:.2f}%  "
           f"MaxDD {compute_stats(equity)['max_drawdown']*100:.2f}%")

    return {
        "key": key,
        "name": p["name"],
        "subtitle": p["subtitle"],
        "blurb": p["blurb"],
        "rebalance": p["rebalance"],
        "start": cal[0].strftime("%Y-%m-%d"),
        "as_of": cal[-1].strftime("%Y-%m-%d"),
        "allocation_date": cal[-1].strftime("%Y-%m-%d"),
        "dates": [d.strftime("%Y-%m-%d") for d in cal],
        # default-schedule curve (kept for back-compat) + every schedule's curve
        "series": series_by_rebal[DEFAULT_REBAL],
        "series_by_rebal": series_by_rebal,
        "rebal_order": REBAL_ORDER,
        "default_rebal": DEFAULT_REBAL,
        "stats": compute_stats(equity),
        "benchmarks": benches,
        "bench_stats": bench_stats,
        "allocation": allocation,
        # SPY-derived drawdown shading over this section's own window, plus the
        # NBER recessions and named sub-threshold events that fall inside it.
        "shades": {
            "recession": [{"from": a, "to": b, "label": t}
                          for a, b, t in NBER_RECESSIONS],
            "drawdown": drawdown_episodes(spy_close),
            "event": [{"from": a, "to": b, "label": t} for a, b, t in EVENTS],
        },
    }


def build_payload(log_fn=log.info, prices: dict | None = None) -> dict:
    if prices is None:
        prices = fetch_prices(log_fn=log_fn)
    sections = {k: build_section(k, prices, log_fn=log_fn)
                for k in SECTION_ORDER}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "payload_version": PAYLOAD_VERSION,
        "version": VERSION,
        "title": "All Weather Fixed",
        "default_years": DEFAULT_YEARS,
        "section_order": SECTION_ORDER,
        "rebal_order": REBAL_ORDER,
        "default_rebal": DEFAULT_REBAL,
        "sections": sections,
    }


def run_fixed_update(log_fn=log.info) -> dict:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(log_fn=log_fn)
    CACHE_PATH.write_text(json.dumps(payload, separators=(",", ":")),
                          encoding="utf-8")
    log_fn(f"[fixed] cached -> {CACHE_PATH}")
    return payload


def load_cached() -> dict | None:
    if CACHE_PATH.is_file():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return None


# =====================================================================
# Logical Invest -- format allocation export (matches strategy_service)
# =====================================================================
def allocations_csv(payload: dict, section: str,
                    investment: float = 100_000.0) -> str:
    sec = payload.get("sections", {}).get(section)
    if sec is None:
        raise KeyError(f"no such fixed section: {section}")
    buf = io.StringIO(newline="")
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow([""])
    w.writerow(["Symbol", "Holding", "Weight", "Amount", "Price", "Shares"])
    for a in sec.get("allocation", []):
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
    w.writerow(["Total Allocation", "", "(rebalance annually)"])
    return buf.getvalue()
