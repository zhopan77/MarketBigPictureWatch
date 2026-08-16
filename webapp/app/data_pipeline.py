"""
Data collection.  This is the verified download logic from
MarketBigPictureWatch.py, packaged so it can be run:

  - by the in-process daily scheduler (app/main.py),
  - by `python -m app.update` from Windows Task Scheduler / cron,
  - or manually.

collect_all_data() downloads everything and returns the all_data dict;
save_data()/load_data() persist it as a pickle under DATA_DIR.
"""

from datetime import date, timedelta
from io import StringIO
import pickle
import sys
import time

import pandas as pd
import requests
import yfinance as yf
# NOTE: pandas_datareader is deliberately NOT imported here. It is only
# needed for the un-keyed FRED fallback, and fred.py imports it lazily
# inside _via_datareader(). This module used to import it at top level
# without ever using it, which made an optional dependency load-bearing
# for starting the server at all -- that is how a distutils failure
# inside pandas_datareader took down the whole app on Python 3.12.

from . import fred, settings

macro_yrs_ultralong = 30
date_fmt = "%Y-%m-%d"

PICKLE_PATH = settings.DATA_DIR / "MarketBigPictureWatch.pkl"

cities_of_interest = [
    "National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego",
    "Portland", "Seattle", "Phoenix", "Dallas",
]

futures_underlying = [
    "USDIndex", "EURIndex", "JPYIndex", "5YrYield", "10YrYield", "Gold",
    "Silver", "Copper", "CrudeOil", "BrentCrudeOil", "Gasoline", "NaturalGas",
    "Wheat", "Corn", "LiveCattle", "Cotton", "Sugar", "Coffee", "Cocoa",
    "OrangeJuice",
]
futures_symbols = [
    "DX-Y.NYB", "6E=F", "6J=F", "^FVX", "^TNX", "GC=F", "SI=F", "HG=F",
    "CL=F", "BZ=F", "RB=F", "NG=F", "ZW=F", "ZC=F", "LE=F", "CT=F", "SB=F",
    "KC=F", "CC=F", "OJ=F",
]
futures_contracts = dict(zip(futures_underlying, futures_symbols))

CaseShillerIndexID = {
    "City20": "SPCS20RSA", "Chicago": "CHXRSA", "SanFrancisco": "SFXRSA",
    "LosAngeles": "LXXRSA", "SanDiego": "SDXRSA", "NewYork": "NYXRSA",
    "Portland": "POXRSA", "Seattle": "SEXRSA", "Atlanta": "ATXRSA",
    "Boston": "BOXRSA", "Charlotte": "CRXRSA", "Cleveland": "CEXRSA",
    "Dallas": "DAXRSA", "Denver": "DNXRSA", "Detroit": "DEXRSA",
    "LasVegas": "LVXRSA", "Miami": "MIXRSA", "Minneapolis": "MNXRSA",
    "Phoenix": "PHXRSA", "Tampa": "TPXRSA", "WashingtonDC": "WDXRSA",
    "City10": "SPCS10RSA", "National": "CSUSHPISA",
}


# A run pulls ~35 FRED series back to back. pandas_datareader retries a few
# times internally and then raises, which used to abort the entire update on a
# single slow response -- and FRED throttles bursts, so a long serial run is
# exactly the case that trips it. Retry with a widening backoff instead.
FRED_BACKOFF = (5, 20, 60)          # seconds to wait before attempts 2, 3, 4

# Series that could not be downloaded on this run. A single unavailable series
# should degrade one panel, not abort the whole update, so the helpers record
# the failure and hand back an empty frame; derived series built with
# calc_two_dataframes use an inner merge, so they come out empty too rather
# than raising. The list is surfaced in meta.json and badged in the header.
DOWNLOAD_FAILURES: list[str] = []


def _empty_series() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                         "value": pd.Series(dtype="float64")})


def get_daily_data_from_fred(series_name, date_start, date_end, name=None):
    """One FRED series as a date/value frame.

    Retry and transport now live in app/fred.py, shared with the strategy
    service. A series that cannot be fetched is recorded and returned EMPTY so
    one outage degrades a single panel instead of aborting the run.
    """
    try:
        s = fred.fetch_series(series_name, date_start, date_end, log=print)
    except Exception as exc:
        print(f"  FRED {series_name}: giving up ({exc}); continuing without it",
              flush=True)
        DOWNLOAD_FAILURES.append(f"FRED:{series_name}")
        return _empty_series()
    df = s.reset_index()
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"]).sort_values("date")
    return df


def get_daily_data_from_yahoo(symbol, date_start, date_end, name=None):
    start_str = date_start.strftime(date_fmt)
    end_str = (date_end + timedelta(days=1)).strftime(date_fmt)
    try:
        df = yf.download(symbol, start=start_str, end=end_str, progress=False)
    except Exception as exc:
        print(f"  Yahoo {symbol}: {type(exc).__name__} ({exc}); "
              f"continuing without it", flush=True)
        DOWNLOAD_FAILURES.append(f"Yahoo:{symbol}")
        return _empty_series()
    if df.empty:
        print(f"  Yahoo {symbol}: no data returned; continuing without it",
              flush=True)
        DOWNLOAD_FAILURES.append(f"Yahoo:{symbol}")
        return _empty_series()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    if "Date" in df.columns:
        df.rename(columns={"Date": "date"}, inplace=True)
    elif "Datetime" in df.columns:
        df.rename(columns={"Datetime": "date"}, inplace=True)
    df = df[["date", "Close"]]
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"]).sort_values("date")
    # Normalize dates defensively: recent yfinance versions return
    # timezone-aware and/or intraday timestamps for some symbols, which
    # breaks date handling downstream. Force tz-naive midnight datetime64.
    df["date"] = pd.to_datetime(df["date"])
    if getattr(df["date"].dt, "tz", None) is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df["date"] = df["date"].dt.normalize()
    if len(df) < 10:
        raise RuntimeError(
            f"Yahoo returned only {len(df)} rows for {symbol} - "
            "treating as a failed download")
    return df


def _covers_window(df, date_start, date_end, frac=0.5) -> bool:
    """Does this frame actually span the window that was asked for?

    `get_daily_data_from_yahoo` already rejects a frame with fewer than 10
    rows, but that is a row COUNT and the real question is coverage. Yahoo
    returned three weeks of ^FVX -- about 15 trading days -- for an eight-year
    request: past the row-count guard, so no exception was raised, so the FRED
    fallback never fired, and the 5-year-yield chart was a flat line with a
    spike at the right-hand edge.

    Compares spans rather than requiring an exact start, because a symbol can
    legitimately begin later than the request (a contract that did not exist
    yet). frac=0.5 is deliberately loose: it is meant to catch "three weeks
    instead of eight years", not to police a few missing months.
    """
    if df is None or getattr(df, "empty", True) or "date" not in getattr(df, "columns", []):
        return False
    want = (date_end - date_start).days
    if want <= 0:
        return True
    got = (df["date"].max() - df["date"].min()).days
    return got >= frac * want


def get_shiller_pe_from_multpl() -> pd.DataFrame:
    URL = "https://www.multpl.com/shiller-pe/table/by-month"
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    df["date"] = [pd.Timestamp(d) for d in df["Date"]]
    df["value"] = (
        df["Value"].astype(str).str.replace(",", "", regex=False).astype(float)
    )
    df = df.sort_values("date").reset_index(drop=True)
    return df.drop(columns=["Value", "Date"])


def calc_two_dataframes(data1, operator, data2):
    df = pd.merge(data1, data2, on="date", how="inner", suffixes=("", "_1"))
    df = df.dropna(subset=["value", "value_1"])
    if operator == "/":
        df["value"] = df["value"] / df["value_1"]
    elif operator == "*":
        df["value"] = df["value"] * df["value_1"]
    elif operator == "+":
        df["value"] = df["value"] + df["value_1"]
    elif operator == "-":
        df["value"] = df["value"] - df["value_1"]
    else:
        raise ValueError(f"Unknown dataframe operator {operator}")
    return df[["date", "value"]]


def collect_all_data(log=print) -> dict:
    """Download everything from FRED / Yahoo / Multpl.  ~2-5 minutes.

    Individual series are allowed to fail: they come back empty and are listed
    in DOWNLOAD_FAILURES, which the caller records so the UI can warn.
    """
    DOWNLOAD_FAILURES.clear()
    date_plotend = date.today()
    date_plotstart = date_plotend - timedelta(
        days=int(round(macro_yrs_ultralong * 365.25)))

    log("Downloading data from Fred, Yahoo, and Multpl...")

    SP500 = get_daily_data_from_yahoo("^GSPC", date_plotstart, date_plotend, "SP500")
    gold = get_daily_data_from_yahoo("GC=F", date_plotstart, date_plotend, "Gold")
    SP500_gold = calc_two_dataframes(SP500, "/", gold)
    ShillerPE10 = get_shiller_pe_from_multpl()
    # Market value of nonfinancial corporate equities (Fed Z.1). Drives the
    # Buffett Indicator (market cap / GDP), computed once GDP is available below.
    equity = get_daily_data_from_fred("NCBEILQ027S", date_plotstart, date_plotend)
    cpi = get_daily_data_from_fred("CPIAUCSL", date_plotstart, date_plotend)
    cpi_food = get_daily_data_from_fred("CPIUFDSL", date_plotstart, date_plotend)
    cpi_housing = get_daily_data_from_fred("CPIHOSSL", date_plotstart, date_plotend)
    cpi_medical = get_daily_data_from_fred("CPIMEDSL", date_plotstart, date_plotend)
    cpi_education = get_daily_data_from_fred("CUSR0000SAE1", date_plotstart, date_plotend)
    gdpdef = get_daily_data_from_fred("GDPDEF", date_plotstart, date_plotend)
    SP500_gdpdef = calc_two_dataframes(SP500, "/", gdpdef)
    MB = get_daily_data_from_fred("BOGMBASE", date_plotstart, date_plotend)
    M2 = get_daily_data_from_fred("M2SL", date_plotstart, date_plotend)
    SP500_M2 = calc_two_dataframes(SP500, "/", M2)
    treasury_yield1 = get_daily_data_from_fred("DGS1", date_plotstart, date_plotend)
    treasury_yield2 = get_daily_data_from_fred("DGS2", date_plotstart, date_plotend)
    treasury_yield5 = get_daily_data_from_fred("DGS5", date_plotstart, date_plotend)
    treasury_yield10 = get_daily_data_from_fred("DGS10", date_plotstart, date_plotend)
    treasury_yield20 = get_daily_data_from_fred("DGS20", date_plotstart, date_plotend)
    treasury_yield_spread = calc_two_dataframes(treasury_yield1, "/", treasury_yield20)
    GDP = get_daily_data_from_fred("GDP", date_plotstart, date_plotend)
    RealGDP = get_daily_data_from_fred("GDPC1", date_plotstart, date_plotend)
    SP500_gdp = calc_two_dataframes(SP500, "/", GDP)
    # Buffett Indicator: corporate equity market value relative to GDP.
    # NCBEILQ027S is in $millions and GDP in $billions, so the raw ratio is
    # 1000x the true fraction; x0.1 renders it as the familiar percent
    # (recent readings land around 150-200%).
    BuffettIndicator = calc_two_dataframes(equity, "/", GDP)
    BuffettIndicator["value"] = BuffettIndicator["value"] * 0.1
    GDP_deflated = calc_two_dataframes(GDP, "/", gdpdef)
    GDP_deflated["value"] = GDP_deflated["value"] * 100.0
    SP500_deflgdp = calc_two_dataframes(SP500, "/", GDP_deflated)
    MB_GDP = calc_two_dataframes(MB, "/", GDP)
    M2_GDP = calc_two_dataframes(M2, "/", GDP)
    mask_norm = (MB_GDP["date"] > pd.Timestamp("1982-01-01")) & \
                (MB_GDP["date"] < pd.Timestamp("2008-05-01"))
    MB_GDP_norm = MB_GDP.copy()
    MB_GDP_norm["value"] = MB_GDP["value"] / MB_GDP.loc[mask_norm, "value"].mean()
    treasury_yield_spread_adj = calc_two_dataframes(treasury_yield_spread, "*", MB_GDP_norm)
    tedspread = get_daily_data_from_fred("TEDRATE", date_plotstart, date_plotend)
    SOFR = get_daily_data_from_fred("SOFR", date_plotstart, date_plotend)
    t3m = get_daily_data_from_fred("DGS3MO", date_plotstart, date_plotend)
    SOFR_t3m = calc_two_dataframes(SOFR, "-", t3m)
    vix = get_daily_data_from_yahoo("^VIX", date_plotstart, date_plotend, "VIX")
    stl_fsi = get_daily_data_from_fred("STLFSI4", date_plotstart, date_plotend)
    kc_fsi = get_daily_data_from_fred("KCFSI", date_plotstart, date_plotend)
    c_fsi = get_daily_data_from_fred("CFSI", date_plotstart, date_plotend)
    anfci = get_daily_data_from_fred("ANFCI", date_plotstart, date_plotend)
    population = get_daily_data_from_fred("POP", date_plotstart, date_plotend)
    wa_population = get_daily_data_from_fred("LFWA64TTUSM647N", date_plotstart, date_plotend)
    wa_population["value"] = wa_population["value"] / 1000.0
    ratio_white = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000003", date_plotstart, date_plotend), "/", population)
    ratio_black = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000006", date_plotstart, date_plotend), "/", population)
    ratio_hispanic = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000009", date_plotstart, date_plotend), "/", population)
    ratio_asian = calc_two_dataframes(
        get_daily_data_from_fred("LNU00032183", date_plotstart, date_plotend), "/", population)
    gdp_per_capita = calc_two_dataframes(GDP, "/", population)
    gdp_per_capita["value"] = gdp_per_capita["value"] * (1e6 / 1e3)
    realgdp_per_capita = calc_two_dataframes(RealGDP, "/", population)
    realgdp_per_capita["value"] = realgdp_per_capita["value"] * (1e6 / 1e3)
    epr = get_daily_data_from_fred("EMRATIO", date_plotstart, date_plotend)
    uer = get_daily_data_from_fred("UNRATE", date_plotstart, date_plotend)
    lfpr = get_daily_data_from_fred("CIVPART", date_plotstart, date_plotend)

    caseshiller = {}
    for city in cities_of_interest:
        log(f"Downloading Case-Shiller: {city}")
        caseshiller[city] = get_daily_data_from_fred(
            CaseShillerIndexID[city], date_plotstart, date_plotend)

    # Yahoo's ^FVX / ^TNX indices track the 5- and 10-year Treasury yields,
    # which FRED also publishes as DGS5 / DGS10 (already downloaded above).
    # Yahoo downloads for these two index symbols break periodically with
    # certain yfinance versions, so fall back to the FRED series.
    fred_fallback = {
        "5YrYield": treasury_yield5,
        "10YrYield": treasury_yield10,
    }

    futures_prices = {}
    for comdty in futures_underlying:
        log(f"Downloading Futures: {comdty}")
        got = None
        try:
            got = get_daily_data_from_yahoo(
                futures_contracts[comdty], date_plotstart, date_plotend, comdty)
        except Exception as e:
            if comdty in fred_fallback:
                log(f"Warning: {comdty} from Yahoo failed ({e}); "
                    f"using FRED Treasury yield instead")
                futures_prices[comdty] = fred_fallback[comdty].copy()
            else:
                log(f"Warning: Skipping {comdty} - {e}")
                futures_prices[comdty] = pd.DataFrame(columns=["date", "value"])
            continue

        # A download that SUCCEEDS but returns a sliver is the failure mode
        # that actually bit: Yahoo served three weeks of ^FVX for an eight-year
        # request. Substitute FRED only when FRED is genuinely better, so a
        # bad FRED day cannot throw away usable Yahoo data.
        # Checked ONLY for the two series with a FRED equivalent. Those are
        # Treasury yields, so a full-window history is known to exist and a
        # short answer is unambiguously wrong. Applying the same rule to the
        # commodity and currency futures would misfire: a contract can
        # legitimately start part-way through the window, and there would be
        # nothing better to switch to anyway.
        alt = fred_fallback.get(comdty)
        if alt is not None and not _covers_window(got, date_plotstart,
                                                  date_plotend):
            span = ((got["date"].max() - got["date"].min()).days
                    if not got.empty else 0)
            if _covers_window(alt, date_plotstart, date_plotend):
                log(f"Warning: {comdty} from Yahoo covered only {span} days of "
                    f"{(date_plotend - date_plotstart).days}; using FRED instead")
                DOWNLOAD_FAILURES.append(f"Yahoo:{futures_contracts[comdty]}(short)")
                futures_prices[comdty] = alt.copy()
                continue
            # FRED is no better today -- keep what we have rather than trade a
            # short series for an empty one, but do not do it silently
            log(f"Warning: {comdty} covers only {span} days of "
                f"{(date_plotend - date_plotstart).days}, and FRED is no "
                f"better; charting the short series")
            DOWNLOAD_FAILURES.append(f"Yahoo:{futures_contracts[comdty]}(short)")
        futures_prices[comdty] = got

    all_data = {
        "SP500": SP500, "gold": gold, "SP500_gold": SP500_gold,
        "ShillerPE10": ShillerPE10, "equity": equity,
        "BuffettIndicator": BuffettIndicator, "cpi": cpi, "cpi_food": cpi_food,
        "cpi_housing": cpi_housing, "cpi_medical": cpi_medical,
        "cpi_education": cpi_education, "gdpdef": gdpdef,
        "SP500_gdpdef": SP500_gdpdef, "MB": MB, "M2": M2,
        "SP500_M2": SP500_M2, "treasury_yield1": treasury_yield1,
        "treasury_yield2": treasury_yield2, "treasury_yield5": treasury_yield5,
        "treasury_yield10": treasury_yield10, "treasury_yield20": treasury_yield20,
        "treasury_yield_spread": treasury_yield_spread,
        "treasury_yield_spread_adj": treasury_yield_spread_adj,
        "GDP": GDP, "RealGDP": RealGDP, "SP500_gdp": SP500_gdp,
        "GDP_deflated": GDP_deflated, "SP500_deflgdp": SP500_deflgdp,
        "MB_GDP": MB_GDP, "M2_GDP": M2_GDP, "tedspread": tedspread,
        "t3m": t3m,
        "SOFR_t3m": SOFR_t3m, "vix": vix, "stl_fsi": stl_fsi,
        "kc_fsi": kc_fsi, "c_fsi": c_fsi, "anfci": anfci,
        "population": population, "wa_population": wa_population,
        "ratio_white": ratio_white, "ratio_black": ratio_black,
        "ratio_hispanic": ratio_hispanic, "ratio_asian": ratio_asian,
        "gdp_per_capita": gdp_per_capita,
        "realgdp_per_capita": realgdp_per_capita,
        "epr": epr, "uer": uer, "lfpr": lfpr,
        "caseshiller": caseshiller, "futures_prices": futures_prices,
        "futures_underlying": futures_underlying,
    }

    for key, val in all_data.items():
        if isinstance(val, pd.DataFrame) and "date" in val.columns:
            all_data[key]["date"] = pd.to_datetime(all_data[key]["date"])
        elif isinstance(val, dict):
            for k2, df2 in val.items():
                if isinstance(df2, pd.DataFrame) and "date" in df2.columns:
                    all_data[key][k2]["date"] = pd.to_datetime(df2["date"])

    if DOWNLOAD_FAILURES:
        log(f"WARNING: {len(DOWNLOAD_FAILURES)} series unavailable: "
            + ", ".join(DOWNLOAD_FAILURES))
    all_data["_failures"] = list(DOWNLOAD_FAILURES)
    return all_data


class DataCacheError(RuntimeError):
    """The cached pickle exists but cannot be read in this environment."""


META_SIDECAR = PICKLE_PATH.with_suffix(".meta.json")


def save_data(all_data: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PICKLE_PATH, "wb") as f:
        pickle.dump(all_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    # Record who wrote it. A pickle of pandas objects is only readable by a
    # compatible pandas, and without this the failure message cannot say which
    # two versions disagreed.
    import json as _json
    import numpy as _np
    import pandas as _pd
    META_SIDECAR.write_text(_json.dumps({
        "pandas": _pd.__version__,
        "numpy": _np.__version__,
        "python": sys.version.split()[0],
    }, indent=2), encoding="utf-8")


def _writer_versions() -> str:
    import json as _json
    try:
        m = _json.loads(META_SIDECAR.read_text(encoding="utf-8"))
        return f"pandas {m.get('pandas', '?')} / numpy {m.get('numpy', '?')}"
    except Exception:
        return "an unknown version"


def load_data() -> dict:
    """Read the cached download.

    Pickled pandas objects are not portable across pandas versions: pandas 3
    stores date columns at second/microsecond resolution, and pandas 2 cannot
    restore a resolution it never produces, which surfaces as an opaque
    NotImplementedError deep inside the unpickler. Translate that into
    something actionable instead.
    """
    import numpy as _np
    import pandas as _pd
    try:
        with open(PICKLE_PATH, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        raise DataCacheError(
            f"The cached market data at {PICKLE_PATH} cannot be read here.\n"
            f"  written by : {_writer_versions()}\n"
            f"  reading with: pandas {_pd.__version__} / numpy {_np.__version__}\n"
            f"  underlying  : {type(exc).__name__}: {exc}\n"
            f"A pickle of pandas objects is only readable by a compatible "
            f"pandas, so this usually means the cache was written from a "
            f"different environment (a .venv vs conda base, say). Re-running "
            f"the full update rewrites it."
        ) from exc
