# big_picture.py

import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import quandl
import yfinance as yf
from pandas_datareader import data as pdr
import requests
from io import StringIO
import pickle

# --------------------------------------------------
# Configuration
# --------------------------------------------------

print("Loading packages...")
plt.switch_backend("Agg")  # remove this line if you want interactive windows
print("Done.\n")

# macro_yrs_ultralong = 20
macro_yrs_ultralong = 30
future_yrs_long = 8
future_yrs_short = 1
date_plotend = date.today()

legend_fontsize = 10
dpi = 109
figsize = (1920 / dpi, 1080 / dpi)
date_fmt = "%Y-%m-%d"
isverbose = True
nrows_verbose = 5

# directory for pictures
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIC_DIR = os.path.join(BASE_DIR, "pictures")
os.makedirs(PIC_DIR, exist_ok=True)


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def _print_head(df, name):
    if isverbose:
        print(f"{name} head:")
        print(df.head(nrows_verbose))
        print("...\n")


def get_daily_data_from_fred(series_name, date_start, date_end, name=None):
    """
    Fetch daily/periodic data from FRED via pandas_datareader and return a
    DataFrame with columns: date, value
    """
    if name is None:
        name = series_name
    df = pdr.DataReader(series_name, "fred", date_start, date_end)
    df = df.reset_index()
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"])
    df = df.sort_values("date")
    _print_head(df, f"FRED {name}")
    return df


def get_daily_data_from_yahoo(symbol, date_start, date_end, name=None):
    """
    Fetch daily close prices from Yahoo via yfinance and return DataFrame with
    columns: date, value
    """
    if name is None:
        name = symbol

    # yfinance uses datetime; include a little padding
    start_str = date_start.strftime(date_fmt)
    end_str = (date_end + timedelta(days=1)).strftime(date_fmt)

    df = yf.download(symbol, start=start_str, end=end_str, progress=False)
    if df.empty:
        raise RuntimeError(f"Yahoo returned no data for {symbol}")

    df = df.reset_index()
    # yfinance returns 'Date' or 'Datetime' as column 0
    if "Date" in df.columns:
        df.rename(columns={"Date": "date"}, inplace=True)
    elif "Datetime" in df.columns:
        df.rename(columns={"Datetime": "date"}, inplace=True)
    df = df[["date", "Close"]]
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"])
    df = df.sort_values("date")
    _print_head(df, f"Yahoo {name}")
    return df


def get_shiller_pe_from_multpl() -> pd.DataFrame:
    URL = "https://www.multpl.com/shiller-pe/table/by-month"
    
    # Download page
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()

    # Parse all tables on the page
    tables = pd.read_html(StringIO(resp.text))

    # Multpl’s Shiller PE by-month table is the first table on this page
    df = tables[0]

    # Typical columns: ['Date', 'Value']
    # Clean up types
    df["date"] = [pd.Timestamp(d) for d in df["Date"]]
    df["value"] = (
        df["Value"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )

    # Sort ascending by date
    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop(columns=["Value", "Date"])
    _print_head(df, "Multpl Shiller PE 10")

    return df

def calc_two_dataframes(data1, operator, data2):
    """
    Align on 'date' and apply elementwise operator on the 'value' columns.
    Returns DataFrame with columns: date, value
    """
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

    df = df[["date", "value"]]
    return df


# --------------------------------------------------
# Date ranges
# --------------------------------------------------

date_plotstart = date_plotend - timedelta(days=int(round(macro_yrs_ultralong * 365.25)))
date_future_plotstart_long = date_plotend - timedelta(days=int(round(future_yrs_long * 365.25)))
date_future_plotstart_short = date_plotend - timedelta(days=int(round(future_yrs_short * 365.25)))

# Convert global limits to pandas Timestamps for Matplotlib
xlim_start = pd.Timestamp(date_plotstart)
xlim_end = pd.Timestamp(date_plotend)

cities_of_interest = [
    "National",
    "Chicago",
    "SanFrancisco",
    "LosAngeles",
    "SanDiego",
    "Portland",
    "Seattle",
    "Phoenix",
    "Dallas",
]

colors = [
    "black",
    "green",
    "blue",
    "cyan",
    "magenta",
    "red",
    "yellow",
    "darkblue",
    "pink",
    "purple",
    "orange",
    "brown",
]

# --------------------------------------------------
# Download section
# --------------------------------------------------

isdownloaded = False
pickle_fn = "MarketBigPictureWatch.pkl"

if os.path.isfile(pickle_fn) and date.today() == date.fromtimestamp(os.path.getmtime(pickle_fn)):
    print("Fresh pickle found, loading data from it...")
    with open(pickle_fn, "rb") as f:
        all_data = pickle.load(f)
        
    isdownloaded = True

if not isdownloaded:
    print("Downloading data from Fred, Yahoo, and Multpl...\n")

    # S&P 500 index
    print("************** S&P500 (Yahoo) **************")
    SP500 = get_daily_data_from_yahoo("^GSPC", date_plotstart, date_plotend, "SP500")

    # Gold price
    print("************** Gold (Yahoo) **************")
    gold = get_daily_data_from_yahoo("GC=F", date_plotstart, date_plotend, "Gold")

    # S&P500 / Gold
    SP500_gold = calc_two_dataframes(SP500, "/", gold)
    
        # Shiller P/E 10 ratio
    print("\n************** Shiller P/E 10 (Multpl) **************")
    ShillerPE10 = get_shiller_pe_from_multpl()

    # Tobin's Q ratio components
    print("\n************** Nonfinancial Corporate Business; Corporate Equities; Liability, Level (Fred) **************")
    equity = get_daily_data_from_fred("NCBEILQ027S", date_plotstart, date_plotend, "Equity")

    print("\n************** Nonfinancial Corporate Business; Net Worth, Level (Fred) **************")
    networth = get_daily_data_from_fred("TNWMVBSNNCB", date_plotstart, date_plotend, "NetWorth")
    
    TobinQ = calc_two_dataframes(equity, "/", networth)

    # Inflation - CPI and components
    print("\n************** CPI (Fred) **************")
    cpi = get_daily_data_from_fred("CPIAUCSL", date_plotstart, date_plotend, "CPI")

    print("\n************** CPI: Food (Fred) **************")
    cpi_food = get_daily_data_from_fred("CPIUFDSL", date_plotstart, date_plotend, "CPI Food")

    print("\n************** CPI: Housing (Fred) **************")
    cpi_housing = get_daily_data_from_fred("CPIHOSSL", date_plotstart, date_plotend, "CPI Housing")

    print("\n************** CPI: Medical (Fred) **************")
    cpi_medical = get_daily_data_from_fred("CPIMEDSL", date_plotstart, date_plotend, "CPI Medical")

    print("\n************** CPI: Education (Fred) **************")
    cpi_education = get_daily_data_from_fred("CUSR0000SAE1", date_plotstart, date_plotend, "CPI Education")
    print("\n************** GDP Deflator (Fred) **************")
    gdpdef = get_daily_data_from_fred("GDPDEF", date_plotstart, date_plotend, "GDP Deflator")

    SP500_gdpdef = calc_two_dataframes(SP500, "/", gdpdef)

    # Money supply
    print("\n************** Monetary Base (Fred) **************")
    MB = get_daily_data_from_fred("BOGMBASE", date_plotstart, date_plotend, "Monetary Base") # in millions 

    print("\n************** M2 (Fred) **************")
    M2 = get_daily_data_from_fred("M2SL", date_plotstart, date_plotend, "M2") # in billions

    SP500_M2 = calc_two_dataframes(SP500, "/", M2)

    print("\n************** US Treasury Zero-Coupon Yield Curve (FRED) **************")
    treasury_yield1 = get_daily_data_from_fred("DGS1", date_plotstart, date_plotend, "Treasury 1 yr")
    treasury_yield2 = get_daily_data_from_fred("DGS2", date_plotstart, date_plotend, "Treasury 2 yr")
    treasury_yield5 = get_daily_data_from_fred("DGS5", date_plotstart, date_plotend, "Treasury 5 yr")
    treasury_yield10 = get_daily_data_from_fred("DGS10", date_plotstart, date_plotend, "Treasury 10 yr")
    treasury_yield20 = get_daily_data_from_fred("DGS20", date_plotstart, date_plotend, "Treasury 20 yr")
  
    # short term interest rate (1 Yr) / long term interest rate (20 Yr)
    treasury_yield_spread = calc_two_dataframes(treasury_yield1, "/", treasury_yield20)

    # GDP
    print("\n************** GDP (Fred) **************")
    GDP = get_daily_data_from_fred("GDP", date_plotstart, date_plotend, "GDP") # Billions of dollars

    print("\n************** Real GDP (Fred) **************")
    RealGDP = get_daily_data_from_fred("GDPC1", date_plotstart, date_plotend, "Real GDP") # Billions of Chained 2012 Dollars

    SP500_gdp = calc_two_dataframes(SP500, "/", GDP)

    GDP_deflated = calc_two_dataframes(GDP, "/", gdpdef)
    GDP_deflated["value"] = GDP_deflated["value"] * 100.0

    SP500_deflgdp = calc_two_dataframes(SP500, "/", GDP_deflated)

    # Excess Monetary Base Explansion: MB / GDP
    MB_GDP = calc_two_dataframes(MB, "/", GDP)
    M2_GDP = calc_two_dataframes(M2, "/", GDP)

    # Normalized to pre-2008 era (1982 to May 2008) which was pretty flat
    mask_norm = (MB_GDP["date"] > pd.Timestamp("1982-01-01")) & (
        MB_GDP["date"] < pd.Timestamp("2008-05-01")
    )
    MB_GDP_norm = MB_GDP.copy()
    MB_GDP_norm["value"] = MB_GDP["value"] / MB_GDP.loc[mask_norm, "value"].mean()

    # Adjust treasury yield spread using excess monetary base expansion
    treasury_yield_spread_adj = calc_two_dataframes(
        treasury_yield_spread, "*", MB_GDP_norm
    )

    # TED spread is discontinued as LIBOR is gone in 2021
    # use SOFR-T-bill spread instead
    # Keep TED spread for historical reference
    print("\n************** TED Spread (Fred) **************")
    tedspread = get_daily_data_from_fred("TEDRATE", date_plotstart, date_plotend, "TED Spread")
    print("\n************** SOFR (Fred) **************")
    SOFR = get_daily_data_from_fred("SOFR", date_plotstart, date_plotend, "SOFR")
    print("\n************** 3-month T-bill (Fred) **************")
    t3m = get_daily_data_from_fred("DGS3MO", date_plotstart, date_plotend, "3-month T-bill")

    SOFR_t3m = calc_two_dataframes(SOFR, "-", t3m)

    # VIX
    print("\n************** VIX (Yahoo) **************")
    vix = get_daily_data_from_yahoo("^VIX", date_plotstart, date_plotend, "VIX")

    # Financial stress indices
    print("\n************** St. Louis Fed Financial Stress Index **************")
    stl_fsi = get_daily_data_from_fred("STLFSI4", date_plotstart, date_plotend, "STLFSI4")

    print("\n************** Kansas City Financial Stress Index **************")
    kc_fsi = get_daily_data_from_fred("KCFSI", date_plotstart, date_plotend, "KCFSI")

    print("\n************** Cleveland Financial Stress Index **************")
    c_fsi = get_daily_data_from_fred("CFSI", date_plotstart, date_plotend, "CFSI") # discontinued

    print("\n************** Chicago Fed Adjusted National Financial Conditions Index **************")
    anfci = get_daily_data_from_fred("ANFCI", date_plotstart, date_plotend, "ANFCI")

    # Population
    print("\n************** US Population (Fred) **************")
    population = get_daily_data_from_fred("POP", date_plotstart, date_plotend, "Population")

    print("\n************** Working age population (age 15-64) (Fred) **************")
    wa_population = get_daily_data_from_fred(
        "LFWA64TTUSM647N", date_plotstart, date_plotend, "WorkingAgePop"
    )
    wa_population["value"] = wa_population["value"] / 1000.0

    print("\n************** White population (Fred) **************")
    ratio_white = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000003", date_plotstart, date_plotend, "White"),
        "/",
        population,
    )

    print("\n************** Black population (Fred) **************")
    ratio_black = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000006", date_plotstart, date_plotend, "Black"),
        "/",
        population,
    )

    print("\n************** Hispanic population (Fred) **************")
    ratio_hispanic = calc_two_dataframes(
        get_daily_data_from_fred("LNU00000009", date_plotstart, date_plotend, "Hispanic"),
        "/",
        population,
    )

    print("\n************** Asian population (Fred) **************")
    ratio_asian = calc_two_dataframes(
        get_daily_data_from_fred("LNU00032183", date_plotstart, date_plotend, "Asian"),
        "/",
        population,
    )

    gdp_per_capita = calc_two_dataframes(GDP, "/", population)
    gdp_per_capita["value"] = gdp_per_capita["value"] * (1e6 / 1e3)

    realgdp_per_capita = calc_two_dataframes(RealGDP, "/", population)
    realgdp_per_capita["value"] = realgdp_per_capita["value"] * (1e6 / 1e3)

    # Labor market
    print("\n************** Civilian Employment-Population ratio (Fred) **************")
    epr = get_daily_data_from_fred("EMRATIO", date_plotstart, date_plotend, "EMRATIO")

    print("\n************** Civilian Unemployment Rate (Fred) **************")
    uer = get_daily_data_from_fred("UNRATE", date_plotstart, date_plotend, "UNRATE")

    print("\n************** Civilian Labor Force Participation Rate (Fred) **************")
    lfpr = get_daily_data_from_fred("CIVPART", date_plotstart, date_plotend, "CIVPART")

    # Case-Shiller
    CaseShillerIndexID = {
        "City20": "SPCS20RSA",
        "Chicago": "CHXRSA",
        "SanFrancisco": "SFXRSA",
        "LosAngeles": "LXXRSA",
        "SanDiego": "SDXRSA",
        "NewYork": "NYXRSA",
        "Portland": "POXRSA",
        "Seattle": "SEXRSA",
        "Atlanta": "ATXRSA",
        "Boston": "BOXRSA",
        "Charlotte": "CRXRSA",
        "Cleveland": "CEXRSA",
        "Dallas": "DAXRSA",
        "Denver": "DNXRSA",
        "Detroit": "DEXRSA",
        "LasVegas": "LVXRSA",
        "Miami": "MIXRSA",
        "Minneapolis": "MNXRSA",
        "Phoenix": "PHXRSA",
        "Tampa": "TPXRSA",
        "WashingtonDC": "WDXRSA",
        "City10": "SPCS10RSA",
        "National": "CSUSHPISA",
    }
    caseshiller = {}
    for city in cities_of_interest:
        print(f"\n************** Case Shiller Index: {city} (Fred) **************")
        caseshiller[city] = get_daily_data_from_fred(
            CaseShillerIndexID[city], date_plotstart, date_plotend, f"CaseShiller {city}"
        )

    # Futures (Yahoo)
    futures_underlying = [
        "USDIndex",
        "EURIndex",
        "JPYIndex",
        "5YrYield",
        "10YrYield",
        "Gold",
        "Silver",
        "Copper",
        "CrudeOil",
        "BrentCrudeOil",
        "Gasoline",
        "NaturalGas",
        "Wheat",
        "Corn",
        "LiveCattle",
        "Cotton",
        "Sugar",
        "Coffee",
        "Cocoa",
        "OrangeJuice",
    ]

    futures_symbols = [
        "DX=F",
        "6E=F",
        "6J=F",
        "^FVX",
        "^TNX",
        "GC=F",
        "SI=F",
        "HG=F",
        "CL=F",
        "BZ=F",
        "RB=F",
        "NG=F",
        "ZW=F",
        "ZC=F",
        "LE=F",
        "CT=F",
        "SB=F",
        "KC=F",
        "CC=F",
        "OJ=F",
    ]

    futures_contracts = dict(zip(futures_underlying, futures_symbols))
    futures_prices = {}
    for comdty in futures_underlying:
        print(f"\n************** Futures: {comdty} (Yahoo) **************")
        futures_prices[comdty] = get_daily_data_from_yahoo(
            futures_contracts[comdty], date_plotstart, date_plotend, comdty
        )

    print("\nAll downloads finished! Saving to pickle...")
    
    all_data = {
        "SP500": SP500,
        "gold": gold,
        "SP500_gold": SP500_gold,
        "ShillerPE10": ShillerPE10,
        "equity": equity,
        "networth": networth,
        "TobinQ": TobinQ,
        "cpi": cpi,
        "cpi_food": cpi_food,
        "cpi_housing": cpi_housing,
        "cpi_medical": cpi_medical,
        "cpi_education": cpi_education,
        "gdpdef": gdpdef,
        "SP500_gdpdef": SP500_gdpdef,
        "MB": MB,
        "M2": M2,
        "SP500_M2": SP500_M2,
        "treasury_yield1": treasury_yield1,
        "treasury_yield2": treasury_yield2,
        "treasury_yield5": treasury_yield5,
        "treasury_yield10": treasury_yield10,
        "treasury_yield20": treasury_yield20,
        "treasury_yield_spread": treasury_yield_spread,
        "treasury_yield_spread_adj": treasury_yield_spread_adj,
        "GDP": GDP,
        "RealGDP": RealGDP,
        "SP500_gdp": SP500_gdp,
        "GDP_deflated": GDP_deflated,
        "SP500_deflgdp": SP500_deflgdp,
        "MB_GDP": MB_GDP,
        "M2_GDP": M2_GDP,
        "tedspread": tedspread,
        "SOFR_t3m": SOFR_t3m,
        "vix": vix,
        "stl_fsi": stl_fsi,
        "kc_fsi": kc_fsi,
        "c_fsi": c_fsi,
        "anfci": anfci,
        "population": population,
        "wa_population": wa_population,
        "ratio_white": ratio_white,
        "ratio_black": ratio_black,
        "ratio_hispanic": ratio_hispanic,
        "ratio_asian": ratio_asian,
        "gdp_per_capita": gdp_per_capita,
        "realgdp_per_capita": realgdp_per_capita,
        "epr": epr,
        "uer": uer,
        "lfpr": lfpr,
        "caseshiller": caseshiller,       # dict of DataFrames
        "futures_prices": futures_prices,  # dict of DataFrames
        "futures_underlying": futures_underlying,
    }
    
    # normalize all DataFrame dates to datetime64[ns]
    for key, val in all_data.items():
        if isinstance(val, pd.DataFrame) and "date" in val.columns:
            all_data[key]["date"] = pd.to_datetime(all_data[key]["date"])
        elif isinstance(val, dict):
            # e.g. caseshiller, futures_prices
            for k2, df2 in val.items():
                if isinstance(df2, pd.DataFrame) and "date" in df2.columns:
                    all_data[key][k2]["date"] = pd.to_datetime(df2["date"])   
                    
    with open(pickle_fn, "wb") as f:
        pickle.dump(all_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        
    isdownloaded = True


# --------------------------------------------------
# Plotting using all_data
# --------------------------------------------------

if isdownloaded:
    print("\nPlotting...")
    nfig = 0
    todaystr = date.today().strftime(date_fmt)

    # ===========================
    # First figure block
    # ===========================
    fig = plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    nrows, ncols = 3, 2
    nplot = 0

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(all_data["SP500"]["date"], all_data["SP500"]["value"], "b-", label="S&P500")
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(all_data["gold"]["date"], all_data["gold"]["value"], "r-", label="Gold")
    ax2.set_ylabel("USD/OZ")
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="lower right")
    ax.grid(True, linestyle=":")
    plt.title(f"Stock and Gold as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(all_data["SP500_gold"]["date"], all_data["SP500_gold"]["value"], "b-")
    ax.set_xlim([xlim_start, xlim_end])
    ax.grid(True, linestyle=":")
    plt.title(f"S&P500 / Gold as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    baseline_yearsago = 10
    baseline_year = date.today().year - baseline_yearsago
    baseline_date_py = date(baseline_year, date.today().month, date.today().day)
    baseline_date = pd.Timestamp(baseline_date_py)  # <-- convert to Timestamp to avoid comparison error to datetime64[ns]

    baseline_cpi = all_data["cpi"].loc[
        all_data["cpi"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["cpi"]["date"],
        all_data["cpi"]["value"] / baseline_cpi * 100.0,
        ":",
        color="blue",
        linewidth=4,
        label="CPI",
    )

    baseline_cpi_food = all_data["cpi_food"].loc[
        all_data["cpi_food"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["cpi_food"]["date"],
        all_data["cpi_food"]["value"] / baseline_cpi_food * 100.0,
        "-",
        color="green",
        label="CPI:Food",
    )

    baseline_cpi_housing = all_data["cpi_housing"].loc[
        all_data["cpi_housing"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["cpi_housing"]["date"],
        all_data["cpi_housing"]["value"] / baseline_cpi_housing * 100.0,
        "-",
        color="aqua",
        label="CPI:Housing",
    )

    baseline_cpi_medical = all_data["cpi_medical"].loc[
        all_data["cpi_medical"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["cpi_medical"]["date"],
        all_data["cpi_medical"]["value"] / baseline_cpi_medical * 100.0,
        "-",
        color="magenta",
        label="CPI:Medical",
    )

    baseline_cpi_education = all_data["cpi_education"].loc[
        all_data["cpi_education"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["cpi_education"]["date"],
        all_data["cpi_education"]["value"] / baseline_cpi_education * 100.0,
        "-",
        color="gold",
        label="CPI:Education",
    )

    baseline_gdpdef = all_data["gdpdef"].loc[
        all_data["gdpdef"]["date"] >= baseline_date, "value"
    ].iloc[0]
    ax.plot(
        all_data["gdpdef"]["date"],
        all_data["gdpdef"]["value"] / baseline_gdpdef * 100.0,
        ":",
        color="red",
        linewidth=4,
        label="GDP Deflator",
    )

    ax.set_xlim([xlim_start, xlim_end])
    ax.set_ylabel("Index")
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax.grid(True, linestyle=":")
    plt.title(
        f"Inflation Index ({baseline_yearsago} years ago = 100) as of {todaystr}"
    )

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["SP500_gdp"]["date"],
        all_data["SP500_gdp"]["value"],
        "b-",
        label="S&P500 / GDP",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["SP500_M2"]["date"],
        all_data["SP500_M2"]["value"],
        "r-",
        label="S&P500 / M2",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper right")
    ax.grid(True, linestyle=":")
    plt.title(f"S&P500 vs. GDP and M2 as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(all_data["MB"]["date"], all_data["MB"]["value"], "b-", label="MB")
    ax.plot(all_data["M2"]["date"], all_data["M2"]["value"], "r-", label="M2")
    ax.plot(all_data["GDP"]["date"], all_data["GDP"]["value"], "-", label="GDP")
    ax.plot(
        all_data["RealGDP"]["date"],
        all_data["RealGDP"]["value"],
        "-",
        color="darkgreen",
        label="Real GDP (2009 USD)",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.set_ylabel("USD Bln")
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["MB_GDP"]["date"],
        all_data["MB_GDP"]["value"],
        "m--",
        label="MB/GDP",
    )
    ax2.plot(
        all_data["M2_GDP"]["date"],
        all_data["M2_GDP"]["value"],
        "c--",
        label="M2/GDP",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper center")
    ax.grid(True, linestyle=":")
    plt.title(f"Money Supply and GDP as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["ShillerPE10"]["date"],
        all_data["ShillerPE10"]["value"],
        "b-",
        label="Shiller P/E 10",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["TobinQ"]["date"],
        all_data["TobinQ"]["value"],
        "r-",
        label="Tobin's Q",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper right")
    ax.grid(True, linestyle=":")
    plt.title(f"Stock Market Valuation - Ratios as of {todaystr}")

    plt.tight_layout()
    nfig += 1
    plt.savefig(os.path.join(PIC_DIR, f"BigPicture{nfig}.png"))

    # ===========================
    # Second figure block
    # ===========================
    plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    nrows, ncols = 3, 2
    nplot = 0

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["treasury_yield20"]["date"],
        all_data["treasury_yield20"]["value"],
        "-",
        color="blue",
        linewidth=0.5,
        label="20 Yr",
    )
    ax.plot(
        all_data["treasury_yield10"]["date"],
        all_data["treasury_yield10"]["value"],
        "-",
        color="green",
        linewidth=0.5,
        label="10 Yr",
    )
    ax.plot(
        all_data["treasury_yield5"]["date"],
        all_data["treasury_yield5"]["value"],
        "-",
        color="yellow",
        linewidth=0.5,
        label="5 Yr",
    )
    ax.plot(
        all_data["treasury_yield2"]["date"],
        all_data["treasury_yield2"]["value"],
        "-",
        color="orange",
        linewidth=0.5,
        label="2 Yr",
    )
    ax.plot(
        all_data["treasury_yield1"]["date"],
        all_data["treasury_yield1"]["value"],
        "-",
        color="red",
        linewidth=0.5,
        label="1 Yr",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.set_ylabel("%")
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax.grid(True, linestyle=":")
    plt.title(f"Treasury Zero-Coupon Yield as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["SP500"]["date"],
        all_data["SP500"]["value"],
        "-",
        color="blue",
        label="S&P500",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["treasury_yield_spread"]["date"],
        all_data["treasury_yield_spread"]["value"],
        "-",
        color="magenta",
        linewidth=1,
        label="1Yr/15Yr",
    )
    ax2.plot(
        all_data["treasury_yield_spread_adj"]["date"],
        all_data["treasury_yield_spread_adj"]["value"],
        "-",
        color="cyan",
        linewidth=1,
        label="1Yr/15Yr_MBAdj",
    )
    # horizontal line at 1
    first_date = all_data["treasury_yield_spread"]["date"].iloc[0]
    last_date = all_data["treasury_yield_spread"]["date"].iloc[-1]
    ax2.plot([first_date, last_date], [1, 1], "-", color="red")
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper center")
    ax.grid(True, linestyle=":")
    plt.title(f"Stock Market and Interest Rate Structure as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["vix"]["date"],
        all_data["vix"]["value"],
        "-",
        color="blue",
        label="VIX",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["tedspread"]["date"],
        all_data["tedspread"]["value"],
        "-",
        color="magenta",
        linewidth=1,
        label="TED Spread (discontinued)",
    )
    ax2.plot(
        all_data["SOFR_t3m"]["date"],
        all_data["SOFR_t3m"]["value"],
        "-",
        color="purple",
        linewidth=1,
        label="SOFR-T-bill Spread",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.set_ylabel("%")
    ax2.legend(prop={"size": legend_fontsize}, loc="upper right")
    ax.grid(True, linestyle=":")
    plt.title(f"Financial Stress Indicators (1) as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["SP500"]["date"],
        all_data["SP500"]["value"],
        "-",
        color="blue",
        label="S&P500",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["stl_fsi"]["date"],
        all_data["stl_fsi"]["value"],
        "-",
        color="red",
        linewidth=1,
        label="St. Louis Fed FSI",
    )
    ax2.plot(
        all_data["kc_fsi"]["date"],
        all_data["kc_fsi"]["value"],
        "-",
        color="green",
        linewidth=1,
        label="Kansas City FSI",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper center")
    ax.grid(True, linestyle=":")
    plt.title(f"Financial Stress Indicators (2) as of {todaystr}")

    ## this correlation plot has no meaning now -it seems SOFR-T-bill spread is leading VIX, not
    ## correlating
    # nplot += 1
    # ax = plt.subplot(nrows, ncols, nplot)
    # SOFR_t3m_vix = pd.merge(
    #     all_data["SOFR_t3m"],
    #     all_data["vix"],
    #     on="date",
    #     how="inner",
    #     suffixes=("", "_1"),
    # )
    # ax.plot(SOFR_t3m_vix["value_1"], SOFR_t3m_vix["value"], "b.")
    # ax.set_xlabel("VIX")
    # ax.set_ylabel("SOFR-T-bill Spread")
    # corr = SOFR_t3m_vix["value_1"].corr(SOFR_t3m_vix["value"])
    # ax.grid(True, linestyle=":")
    # plt.title(f"VIX ~ SOFR-T-bill Spread, corr = {round(corr * 100, 2)}%")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["SP500"]["date"],
        all_data["SP500"]["value"],
        "-",
        color="blue",
        label="S&P500",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["c_fsi"]["date"],
        all_data["c_fsi"]["value"],
        "-",
        color="red",
        linewidth=1,
        label="Cleveland FSI (discontinued)",
    )
    ax2.plot(
        all_data["anfci"]["date"],
        all_data["anfci"]["value"],
        "-",
        color="green",
        linewidth=1,
        label="Chicago Fed Adjusted National FCI",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="upper center")
    ax.grid(True, linestyle=":")
    plt.title(f"Financial Stress Indicators (3) as of {todaystr}")

    plt.tight_layout()
    nfig += 1
    plt.savefig(os.path.join(PIC_DIR, f"BigPicture{nfig}.png"))

    # ===========================
    # Third figure block
    # ===========================
    plt.figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows, ncols = 2, 2
    nplot = 0

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["population"]["date"],
        all_data["population"]["value"] / 1e6,
        "--",
        color="blue",
        linewidth=1,
        label="Population",
    )
    ax.plot(
        all_data["wa_population"]["date"],
        all_data["wa_population"]["value"] / 1e6,
        "--",
        color="magenta",
        linewidth=1,
        label="Working Age (15-64) Population",
    )
    ax.set_ylabel("Bln Persons")
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["gdp_per_capita"]["date"],
        all_data["gdp_per_capita"]["value"],
        "-",
        color="red",
        linewidth=1,
        label="GDP Per Capita",
    )
    ax2.plot(
        all_data["realgdp_per_capita"]["date"],
        all_data["realgdp_per_capita"]["value"],
        "-",
        color="green",
        linewidth=1,
        label="Real GDP Per Capita (2009 USD)",
    )
    ax2.set_ylabel("K USD")
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.legend(prop={"size": legend_fontsize}, loc="lower right")
    ax.grid(True, linestyle=":")
    plt.title(f"Population as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    ax.plot(
        all_data["epr"]["date"],
        all_data["epr"]["value"],
        "-",
        color="green",
        linewidth=1,
        label="Employment-Population Ratio",
    )
    ax.plot(
        all_data["lfpr"]["date"],
        all_data["lfpr"]["value"],
        "-",
        color="blue",
        linewidth=1,
        label="Labor Force Participation Rate",
    )
    ax.set_xlim([xlim_start, xlim_end])
    ax.set_ylabel("%")
    ax.legend(prop={"size": legend_fontsize}, loc="lower left")
    ax2 = ax.twinx()
    ax2.plot(
        all_data["uer"]["date"],
        all_data["uer"]["value"],
        "-",
        color="red",
        linewidth=1,
        label="Unemployment Rate",
    )
    ax2.set_xlim([xlim_start, xlim_end])
    ax2.set_ylabel("%")
    ax2.legend(prop={"size": legend_fontsize}, loc="upper center")
    ax.grid(True, linestyle=":")
    plt.title(f"Labor Market Condition as of {todaystr}")

    nplot += 1
    ax = plt.subplot(nrows, ncols, nplot)
    for n, city in enumerate(cities_of_interest):
        city_df = all_data["caseshiller"][city]
        ax.plot(
            city_df["date"],
            city_df["value"],
            "-",
            color=colors[n],
            linewidth=3 if city in ["National", "Chicago", "SanFrancisco"] else 1,
            label=city,
        )
    ax.set_xlim([xlim_start, xlim_end])
    ax.legend(prop={"size": legend_fontsize}, loc="upper left")
    ax.grid(True, linestyle=":")
    plt.title(f"S&P/Case-Shiller Home Price Indices as of {todaystr}")

    plt.tight_layout()
    nfig += 1
    plt.savefig(os.path.join(PIC_DIR, f"BigPicture{nfig}.png"))

    # ===========================
    # Fourth figure block: Futures long term
    # ===========================
    plt.figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows, ncols = 4, 5
    nplot = 0

    future_long_start = pd.Timestamp(date_future_plotstart_long)
    for comdty in all_data["futures_underlying"]:
        nplot += 1
        ax = plt.subplot(nrows, ncols, nplot)
        df_fut = all_data["futures_prices"][comdty]
        ax.plot(
            df_fut["date"],
            df_fut["value"],
            "-",
            color="blue",
            linewidth=1,
            label=comdty,
        )
        ax.set_xlim([future_long_start, xlim_end])
        ax.legend()
        plt.grid(True, linestyle=":")
        plt.tick_params(axis="both", which="major", labelsize=6)
        plt.tick_params(axis="both", which="minor", labelsize=6)
    plt.suptitle(f"Futures - Long Term ({future_yrs_long}-year) as of {todaystr}")
    nfig += 1
    plt.savefig(os.path.join(PIC_DIR, f"BigPicture{nfig}.png"))
        

    # ===========================
    # Fourth figure block: Futures short term
    # ===========================
    plt.figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows, ncols = 4, 5
    nplot = 0

    future_short_start = pd.Timestamp(date_future_plotstart_short)
    for comdty in all_data["futures_underlying"]:
        nplot += 1
        ax = plt.subplot(nrows, ncols, nplot)
        df_fut = all_data["futures_prices"][comdty]
        df_fut = df_fut[df_fut["date"] >= future_short_start]
        df_fut = df_fut[df_fut["date"] <= xlim_end]
        ax.plot(
            df_fut["date"],
            df_fut["value"],
            "-",
            color="blue",
            linewidth=1,
            label=comdty,
        )
        # ax.set_xlim([future_short_start, xlim_end])
        ax.legend()
        plt.grid(True, linestyle=":")
        plt.tick_params(axis="both", which="major", labelsize=5)
        plt.tick_params(axis="both", which="minor", labelsize=5)  
    plt.suptitle(f"Futures - Short Term ({future_yrs_short}-year) as of {todaystr}")
    nfig += 1
    plt.savefig(os.path.join(PIC_DIR, f"BigPicture{nfig}.png"))

    print(f"All done! Browse the folder '{PIC_DIR}' for the plots.")
    
