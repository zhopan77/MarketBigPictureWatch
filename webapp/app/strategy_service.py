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
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import settings, strategy as S

log = logging.getLogger(__name__)

CACHE_PATH = settings.DATA_DIR / "strategy.json"
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

    syms = S.TICKERS + [S.CASH_TICKER]
    log_fn(f"Downloading {len(syms)} symbols from Yahoo: {', '.join(syms)}")
    raw = yf.download(syms, start=DOWNLOAD_START, auto_adjust=True,
                      progress=False, group_by="column", threads=True)
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

    # Trade only bars where every instrument printed, mirroring the
    # "require all assets present" gate in the Zorro/QC versions.
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()
    for s in syms:
        frames[s] = frames[s].loc[common]
    log_fn(f"  {len(common)} aligned bars "
           f"{common[0].date()} .. {common[-1].date()}")
    return frames


def fetch_vix(log_fn=log.info) -> pd.Series:
    """VIXCLS from FRED -- the same series the Zorro build reads from
    History\\VIXCLS.csv, so the 18/25 regime thresholds fire on the same days.
    Falls back to Yahoo's ^VIX if FRED is unreachable."""
    try:
        from pandas_datareader import data as pdr
        v = pdr.DataReader("VIXCLS", "fred", DOWNLOAD_START, date.today())
        s = v["VIXCLS"].dropna()
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
SLEEVE_FRACS = (0.50, 0.75, 1.00)
DEFAULT_FRAC = "0.75"

# Bump whenever the SHAPE or COMPLETENESS of the cached payload changes (new
# fields, a truncation lifted, a different variant set). The page compares the
# cache's stamp against this and says so if the cache is older, instead of
# silently serving stale data that looks fine -- which is exactly how a
# lifted 250-entry log cap went unnoticed.
PAYLOAD_VERSION = 2


def _frac_key(f: float) -> str:
    return f"{f:.2f}"


def build_payload(log_fn=log.info) -> dict:
    px = fetch_prices(log_fn=log_fn)
    vix = fetch_vix(log_fn=log_fn)

    # ---- benchmarks and the shared calendar, from the first run ----
    variants, first = {}, None
    for frac in SLEEVE_FRACS:
        log_fn(f"Backtesting sleeve fraction {frac:.2f} ...")
        res = S.run_backtest(px, vix, log_fn=log_fn, sleeve_frac=frac)
        if first is None:
            first = res
        variants[_frac_key(frac)] = res

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

    last_px = {s: float(px[s]["close"].iloc[-1]) for s in first.symbols}

    # ---- per-fraction blocks ----
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    var_out = {}
    for key, res in variants.items():
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
        }
        # full adjustment log per fraction, mirroring the Zorro [ADJ ...] lines
        path = settings.DATA_DIR / f"strategy_adjustments_{key.replace('.', '')}.log"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(f"# AllWeather9 v3.9.2  SLEEVE_FRAC={key}  "
                     f"generated {datetime.now(timezone.utc).isoformat()}\n")
            for a in res.adjustments:
                legs = " ".join(f"{k}={v*100:.0f}%" for k, v in a["weights"].items())
                fh.write(f"[ADJ {a['tag']:<7}] {a['date']} H={a['hurst']:.2f} {legs}\n")

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
        "default_frac": DEFAULT_FRAC,
        "payload_version": PAYLOAD_VERSION,
        "variants": var_out,
        "sleeve_on": bool(first.sleeve_on[-1]) if first.sleeve_on is not None else False,
        "hurst": (round(float(first.hurst[-1]), 3)
                  if first.hurst is not None and np.isfinite(first.hurst[-1]) else None),
        "bil_cagr": bil_cagr,
        "n_rebalances": first.n_rebalances,
        "n_sleeve_on": first.n_sleeve_on,
        "n_sleeve_off": first.n_sleeve_off,
        "config": {
            "universe": S.TICKERS, "cash": S.CASH_TICKER,
            "max_weight": S.MAX_WEIGHT,
            "hurst_enter": S.H_ENTER, "hurst_exit": S.H_EXIT,
            "hurst_win": S.HURST_WIN, "ha_span": S.HA_SPAN_BARS,
            "vix_high": S.VIX_HIGH, "vix_mid": S.VIX_MID,
        },
    }
    return payload


def run_strategy_update(log_fn=log.info) -> dict:
    payload = build_payload(log_fn=log_fn)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, separators=(",", ":")),
                          encoding="utf-8")
    log_fn(f"  strategy cached -> {CACHE_PATH}")
    log_fn(f"  {payload['start']}..{payload['as_of']}  "
           f"{payload['n_rebalances']} rebalances")
    for key in payload["fracs"]:
        st = payload["variants"][key]["stats"]
        log_fn(f"    SLEEVE_FRAC {key}:  CAGR {st['cagr']*100:6.2f}%  "
               f"Sharpe {st['sharpe']:.3f}  Sortino {st['sortino']:.2f}  "
               f"MaxDD {st['max_drawdown']*100:6.2f}%")
    bc = payload.get("bil_cagr")
    if bc is not None:
        log_fn(f"  BIL cash carry over the window: {bc*100:.2f}%/yr "
               f"(should track the average 1-3 month T-bill yield; "
               f"~0% would mean distributions are not being adjusted in)")
    return payload


def load_cached() -> dict | None:
    if CACHE_PATH.is_file():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
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
