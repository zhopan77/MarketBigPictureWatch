"""
FRED access.

`pandas_datareader` fetches `fredgraph.csv`, which is unauthenticated and
throttled per IP. A full update pulls ~35 series back to back, which is exactly
the burst that makes that endpoint start timing out. The official API at
api.stlouisfed.org takes a key, has published rate limits, and returns JSON.

Set MW_FRED_API_KEY (or FRED_API_KEY) to use it. Without a key this falls back
to pandas_datareader, so the app still runs unconfigured -- just less reliably.

One retry policy lives here and is shared by the macro pipeline and the
strategy service, which previously had separate (and unequal) handling.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from . import settings

API_URL = "https://api.stlouisfed.org/fred/series/observations"
# Retrying these just burns the backoff four times over: they cannot succeed on
# a second attempt. A type error in this module once cost 85s per series.
NON_RETRYABLE = (TypeError, AttributeError, NameError, ImportError)
BACKOFF = (5, 20, 60)          # seconds before attempts 2, 3, 4
TIMEOUT = 30


def have_key() -> bool:
    return bool(settings.FRED_API_KEY)


def _via_api(series_id: str, start, end) -> pd.Series:
    """One request to the official API. Raises on any failure."""
    # callers pass strings ("2006-01-01"), date, datetime or Timestamp --
    # pandas_datareader accepted all of them, so this must too
    r = requests.get(API_URL, timeout=TIMEOUT, params={
        "series_id": series_id,
        "api_key": settings.FRED_API_KEY,
        "file_type": "json",
        "observation_start": pd.Timestamp(start).strftime("%Y-%m-%d"),
        "observation_end": pd.Timestamp(end).strftime("%Y-%m-%d"),
    })
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    idx, vals = [], []
    for o in obs:
        raw = o.get("value", ".")
        if raw in (".", "", None):      # FRED's missing-value marker
            continue
        try:
            vals.append(float(raw))
        except ValueError:
            continue
        idx.append(pd.Timestamp(o["date"]))
    if not vals:
        raise RuntimeError(f"FRED returned only missing values for {series_id}")
    return pd.Series(vals, index=pd.DatetimeIndex(idx), name=series_id)


def _via_datareader(series_id: str, start, end) -> pd.Series:
    from pandas_datareader import data as pdr
    v = pdr.DataReader(series_id, "fred", start, end)
    return v[series_id].dropna()


def fetch_series(series_id: str, start, end, log=print) -> pd.Series:
    """A FRED series as a float Series indexed by date.

    Tries the keyed API when configured, otherwise pandas_datareader, retrying
    each with a widening backoff. Raises if every attempt fails; callers decide
    whether that is fatal.
    """
    getter = _via_api if have_key() else _via_datareader
    how = "api" if have_key() else "fredgraph"
    for attempt in range(len(BACKOFF) + 1):
        try:
            return getter(series_id, start, end)
        except NON_RETRYABLE as exc:
            raise RuntimeError(
                f"FRED {series_id} ({how}): {type(exc).__name__}: {exc} "
                f"-- not retrying, this is a bug not an outage") from exc
        except Exception as exc:
            if attempt == len(BACKOFF):
                raise RuntimeError(
                    f"FRED {series_id} ({how}) failed after "
                    f"{attempt + 1} attempts: {exc}") from exc
            wait = BACKOFF[attempt]
            log(f"  FRED {series_id}: {type(exc).__name__}, retrying in "
                f"{wait}s (attempt {attempt + 2}/{len(BACKOFF) + 1})")
            time.sleep(wait)
