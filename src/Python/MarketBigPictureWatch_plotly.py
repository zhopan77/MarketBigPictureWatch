# MarketBigPictureWatch_plotly.py
#
# Plotly version of MarketBigPictureWatch.py that reproduces the matplotlib
# figures (BigPicture1..5.png) as closely as possible:
#   - same subplot layouts, plot order, and titles ("... as of YYYY-MM-DD")
#   - per-subplot legends placed like matplotlib's loc= (requires plotly >= 5.15)
#   - same colors, line widths, and dash styles
#   - fixed 30-year x range, dotted grid on the primary axis only
#   - inflation panel normalized per-series to its own 10-years-ago value
#
# Output: interactive HTML files BigPicture1.html .. BigPicture5.html in ./pictures

import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from pandas_datareader import data as pdr
import requests
from io import StringIO
import pickle

# --------------------------------------------------
# Configuration
# --------------------------------------------------

print("Loading packages...")
print("Done.\n")

macro_yrs_ultralong = 30
future_yrs_long = 8
future_yrs_short = 1
date_plotend = date.today()

legend_fontsize = 10
fig_width = 1920
fig_height = 1080
date_fmt = "%Y-%m-%d"

# directory for pictures
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIC_DIR = os.path.join(BASE_DIR, "pictures")
os.makedirs(PIC_DIR, exist_ok=True)

GRID = dict(showgrid=True, griddash="dot", gridcolor="rgba(150,150,150,0.55)")
NOGRID = dict(showgrid=False)

# matplotlib named colors that plotly/CSS also understands are used directly
# (blue, red, green, magenta, cyan, aqua, gold, orange, yellow, purple,
#  darkgreen, darkblue, pink, black, brown).  matplotlib's default first cycle
# color 'C0' (used for the GDP line) is:
MPL_C0 = "#1f77b4"


# --------------------------------------------------
# Helper functions (data download - unchanged logic)
# --------------------------------------------------

def get_daily_data_from_fred(series_name, date_start, date_end, name=None):
    if name is None:
        name = series_name
    df = pdr.DataReader(series_name, "fred", date_start, date_end)
    df = df.reset_index()
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"])
    df = df.sort_values("date")
    return df


def get_daily_data_from_yahoo(symbol, date_start, date_end, name=None):
    if name is None:
        name = symbol

    start_str = date_start.strftime(date_fmt)
    end_str = (date_end + timedelta(days=1)).strftime(date_fmt)

    df = yf.download(symbol, start=start_str, end=end_str, progress=False)

    if df.empty:
        raise RuntimeError(f"Yahoo returned no data for {symbol}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    if "Date" in df.columns:
        df.rename(columns={"Date": "date"}, inplace=True)
    elif "Datetime" in df.columns:
        df.rename(columns={"Datetime": "date"}, inplace=True)

    df = df[["date", "Close"]]
    df.columns = ["date", "value"]
    df = df.dropna(subset=["value"])
    df = df.sort_values("date")
    return df


def get_shiller_pe_from_multpl() -> pd.DataFrame:
    URL = "https://www.multpl.com/shiller-pe/table/by-month"
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    df["date"] = [pd.Timestamp(d) for d in df["Date"]]
    df["value"] = (
        df["Value"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .astype(float)
    )
    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop(columns=["Value", "Date"])
    return df


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

    df = df[["date", "value"]]
    return df


# --------------------------------------------------
# Plotting helpers
# --------------------------------------------------

def line(df, name, color=None, width=1.5, dash=None, legend=None,
         showlegend=True):
    """Build a go.Scatter line trace from a (date, value) DataFrame."""
    return go.Scatter(
        x=df["date"], y=df["value"], name=name, mode="lines",
        showlegend=showlegend, legend=legend,
        line=dict(color=color, width=width, dash=dash),
    )


class LegendManager:
    """
    Creates one plotly legend per matplotlib legend, positioned inside the
    subplot area like matplotlib's loc= (upper left, lower right, ...).
    Requires plotly >= 5.15 (multiple-legend support).
    """

    # (x fraction inside subplot, y fraction, xanchor, yanchor)
    LOCS = {
        "upper left":   (0.01, 0.99, "left",   "top"),
        "upper center": (0.50, 0.99, "center", "top"),
        "upper right":  (0.99, 0.99, "right",  "top"),
        "lower left":   (0.01, 0.01, "left",   "bottom"),
        "lower center": (0.50, 0.01, "center", "bottom"),
        "lower right":  (0.99, 0.01, "right",  "bottom"),
    }

    def __init__(self, fig):
        self.fig = fig
        self.count = 0

    def new(self, row, col, loc="upper left"):
        self.count += 1
        name = "legend" if self.count == 1 else f"legend{self.count}"

        sp = self.fig.get_subplot(row, col)
        xd = sp.xaxis.domain
        yd = sp.yaxis.domain
        fx, fy, xanchor, yanchor = self.LOCS[loc]
        x = xd[0] + fx * (xd[1] - xd[0])
        y = yd[0] + fy * (yd[1] - yd[0])

        self.fig.update_layout({name: dict(
            x=x, y=y, xanchor=xanchor, yanchor=yanchor,
            font=dict(size=legend_fontsize),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(150,150,150,0.9)", borderwidth=1,
        )})
        return name


def style_figure(fig, xlim=None):
    """White background, dotted grid on primary axes only, fixed x range."""
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="white", paper_bgcolor="white",
        width=fig_width, height=fig_height,
        margin=dict(l=60, r=60, t=60, b=40),
        font=dict(size=12),
    )
    fig.update_xaxes(**GRID, ticks="outside",
                     linecolor="black", mirror=True, zeroline=False)
    fig.update_yaxes(**GRID, ticks="outside",
                     linecolor="black", mirror=True, zeroline=False,
                     secondary_y=False)
    # matplotlib only draws the grid of the primary axis
    fig.update_yaxes(**NOGRID, secondary_y=True)
    if xlim is not None:
        fig.update_xaxes(range=list(xlim))


# --------------------------------------------------
# Date ranges
# --------------------------------------------------

date_plotstart = date_plotend - timedelta(days=int(round(macro_yrs_ultralong * 365.25)))
date_future_plotstart_long = date_plotend - timedelta(days=int(round(future_yrs_long * 365.25)))
date_future_plotstart_short = date_plotend - timedelta(days=int(round(future_yrs_short * 365.25)))

xlim_start = pd.Timestamp(date_plotstart)
xlim_end = pd.Timestamp(date_plotend)

cities_of_interest = [
    "National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego",
    "Portland", "Seattle", "Phoenix", "Dallas",
]

colors = [
    "black", "green", "blue", "cyan", "magenta", "red",
    "yellow", "darkblue", "pink", "purple", "orange", "brown",
]

# --------------------------------------------------
# Download section (unchanged from the matplotlib script)
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

    SP500 = get_daily_data_from_yahoo("^GSPC", date_plotstart, date_plotend, "SP500")
    gold = get_daily_data_from_yahoo("GC=F", date_plotstart, date_plotend, "Gold")
    SP500_gold = calc_two_dataframes(SP500, "/", gold)
    ShillerPE10 = get_shiller_pe_from_multpl()
    equity = get_daily_data_from_fred("NCBEILQ027S", date_plotstart, date_plotend, "Equity")
    networth = get_daily_data_from_fred("TNWMVBSNNCB", date_plotstart, date_plotend, "NetWorth")
    TobinQ = calc_two_dataframes(equity, "/", networth)
    cpi = get_daily_data_from_fred("CPIAUCSL", date_plotstart, date_plotend, "CPI")
    cpi_food = get_daily_data_from_fred("CPIUFDSL", date_plotstart, date_plotend, "CPI Food")
    cpi_housing = get_daily_data_from_fred("CPIHOSSL", date_plotstart, date_plotend, "CPI Housing")
    cpi_medical = get_daily_data_from_fred("CPIMEDSL", date_plotstart, date_plotend, "CPI Medical")
    cpi_education = get_daily_data_from_fred("CUSR0000SAE1", date_plotstart, date_plotend, "CPI Education")
    gdpdef = get_daily_data_from_fred("GDPDEF", date_plotstart, date_plotend, "GDP Deflator")
    SP500_gdpdef = calc_two_dataframes(SP500, "/", gdpdef)
    MB = get_daily_data_from_fred("BOGMBASE", date_plotstart, date_plotend, "Monetary Base")
    M2 = get_daily_data_from_fred("M2SL", date_plotstart, date_plotend, "M2")
    SP500_M2 = calc_two_dataframes(SP500, "/", M2)
    treasury_yield1 = get_daily_data_from_fred("DGS1", date_plotstart, date_plotend, "Treasury 1 yr")
    treasury_yield2 = get_daily_data_from_fred("DGS2", date_plotstart, date_plotend, "Treasury 2 yr")
    treasury_yield5 = get_daily_data_from_fred("DGS5", date_plotstart, date_plotend, "Treasury 5 yr")
    treasury_yield10 = get_daily_data_from_fred("DGS10", date_plotstart, date_plotend, "Treasury 10 yr")
    treasury_yield20 = get_daily_data_from_fred("DGS20", date_plotstart, date_plotend, "Treasury 20 yr")
    treasury_yield_spread = calc_two_dataframes(treasury_yield1, "/", treasury_yield20)
    GDP = get_daily_data_from_fred("GDP", date_plotstart, date_plotend, "GDP")
    RealGDP = get_daily_data_from_fred("GDPC1", date_plotstart, date_plotend, "Real GDP")
    SP500_gdp = calc_two_dataframes(SP500, "/", GDP)
    GDP_deflated = calc_two_dataframes(GDP, "/", gdpdef)
    GDP_deflated["value"] = GDP_deflated["value"] * 100.0
    SP500_deflgdp = calc_two_dataframes(SP500, "/", GDP_deflated)
    MB_GDP = calc_two_dataframes(MB, "/", GDP)
    M2_GDP = calc_two_dataframes(M2, "/", GDP)
    mask_norm = (MB_GDP["date"] > pd.Timestamp("1982-01-01")) & (MB_GDP["date"] < pd.Timestamp("2008-05-01"))
    MB_GDP_norm = MB_GDP.copy()
    MB_GDP_norm["value"] = MB_GDP["value"] / MB_GDP.loc[mask_norm, "value"].mean()
    treasury_yield_spread_adj = calc_two_dataframes(treasury_yield_spread, "*", MB_GDP_norm)
    tedspread = get_daily_data_from_fred("TEDRATE", date_plotstart, date_plotend, "TED Spread")
    SOFR = get_daily_data_from_fred("SOFR", date_plotstart, date_plotend, "SOFR")
    t3m = get_daily_data_from_fred("DGS3MO", date_plotstart, date_plotend, "3-month T-bill")
    SOFR_t3m = calc_two_dataframes(SOFR, "-", t3m)
    vix = get_daily_data_from_yahoo("^VIX", date_plotstart, date_plotend, "VIX")
    stl_fsi = get_daily_data_from_fred("STLFSI4", date_plotstart, date_plotend, "STLFSI4")
    kc_fsi = get_daily_data_from_fred("KCFSI", date_plotstart, date_plotend, "KCFSI")
    c_fsi = get_daily_data_from_fred("CFSI", date_plotstart, date_plotend, "CFSI")
    anfci = get_daily_data_from_fred("ANFCI", date_plotstart, date_plotend, "ANFCI")
    population = get_daily_data_from_fred("POP", date_plotstart, date_plotend, "Population")
    wa_population = get_daily_data_from_fred("LFWA64TTUSM647N", date_plotstart, date_plotend, "WorkingAgePop")
    wa_population["value"] = wa_population["value"] / 1000.0
    ratio_white = calc_two_dataframes(get_daily_data_from_fred("LNU00000003", date_plotstart, date_plotend, "White"), "/", population)
    ratio_black = calc_two_dataframes(get_daily_data_from_fred("LNU00000006", date_plotstart, date_plotend, "Black"), "/", population)
    ratio_hispanic = calc_two_dataframes(get_daily_data_from_fred("LNU00000009", date_plotstart, date_plotend, "Hispanic"), "/", population)
    ratio_asian = calc_two_dataframes(get_daily_data_from_fred("LNU00032183", date_plotstart, date_plotend, "Asian"), "/", population)
    gdp_per_capita = calc_two_dataframes(GDP, "/", population)
    gdp_per_capita["value"] = gdp_per_capita["value"] * (1e6 / 1e3)
    realgdp_per_capita = calc_two_dataframes(RealGDP, "/", population)
    realgdp_per_capita["value"] = realgdp_per_capita["value"] * (1e6 / 1e3)
    epr = get_daily_data_from_fred("EMRATIO", date_plotstart, date_plotend, "EMRATIO")
    uer = get_daily_data_from_fred("UNRATE", date_plotstart, date_plotend, "UNRATE")
    lfpr = get_daily_data_from_fred("CIVPART", date_plotstart, date_plotend, "CIVPART")

    CaseShillerIndexID = {
        "City20": "SPCS20RSA", "Chicago": "CHXRSA", "SanFrancisco": "SFXRSA", "LosAngeles": "LXXRSA",
        "SanDiego": "SDXRSA", "NewYork": "NYXRSA", "Portland": "POXRSA", "Seattle": "SEXRSA",
        "Atlanta": "ATXRSA", "Boston": "BOXRSA", "Charlotte": "CRXRSA", "Cleveland": "CEXRSA",
        "Dallas": "DAXRSA", "Denver": "DNXRSA", "Detroit": "DEXRSA", "LasVegas": "LVXRSA",
        "Miami": "MIXRSA", "Minneapolis": "MNXRSA", "Phoenix": "PHXRSA", "Tampa": "TPXRSA",
        "WashingtonDC": "WDXRSA", "City10": "SPCS10RSA", "National": "CSUSHPISA",
    }
    caseshiller = {}
    for city in cities_of_interest:
        print(f"Downloading Case-Shiller: {city}")
        caseshiller[city] = get_daily_data_from_fred(CaseShillerIndexID[city], date_plotstart, date_plotend, f"CaseShiller {city}")

    futures_underlying = ["USDIndex", "EURIndex", "JPYIndex", "5YrYield", "10YrYield", "Gold", "Silver", "Copper", "CrudeOil",
                          "BrentCrudeOil", "Gasoline", "NaturalGas", "Wheat", "Corn", "LiveCattle", "Cotton", "Sugar",
                          "Coffee", "Cocoa", "OrangeJuice"]
    futures_symbols = ["DX-Y.NYB", "6E=F", "6J=F", "^FVX", "^TNX", "GC=F", "SI=F", "HG=F", "CL=F", "BZ=F",
                       "RB=F", "NG=F", "ZW=F", "ZC=F", "LE=F", "CT=F", "SB=F", "KC=F", "CC=F", "OJ=F"]
    futures_contracts = dict(zip(futures_underlying, futures_symbols))

    futures_prices = {}
    for comdty in futures_underlying:
        print(f"Downloading Futures: {comdty}")
        try:
            futures_prices[comdty] = get_daily_data_from_yahoo(futures_contracts[comdty], date_plotstart, date_plotend, comdty)
        except RuntimeError as e:
            print(f"Warning: Skipping {comdty} - {e}")
            futures_prices[comdty] = pd.DataFrame(columns=["date", "value"])

    all_data = {
        "SP500": SP500, "gold": gold, "SP500_gold": SP500_gold, "ShillerPE10": ShillerPE10,
        "equity": equity, "networth": networth, "TobinQ": TobinQ, "cpi": cpi, "cpi_food": cpi_food,
        "cpi_housing": cpi_housing, "cpi_medical": cpi_medical, "cpi_education": cpi_education,
        "gdpdef": gdpdef, "SP500_gdpdef": SP500_gdpdef, "MB": MB, "M2": M2, "SP500_M2": SP500_M2,
        "treasury_yield1": treasury_yield1, "treasury_yield2": treasury_yield2, "treasury_yield5": treasury_yield5,
        "treasury_yield10": treasury_yield10, "treasury_yield20": treasury_yield20, "treasury_yield_spread": treasury_yield_spread,
        "treasury_yield_spread_adj": treasury_yield_spread_adj, "GDP": GDP, "RealGDP": RealGDP, "SP500_gdp": SP500_gdp,
        "GDP_deflated": GDP_deflated, "SP500_deflgdp": SP500_deflgdp, "MB_GDP": MB_GDP, "M2_GDP": M2_GDP,
        "tedspread": tedspread, "SOFR_t3m": SOFR_t3m, "vix": vix, "stl_fsi": stl_fsi, "kc_fsi": kc_fsi,
        "c_fsi": c_fsi, "anfci": anfci, "population": population, "wa_population": wa_population,
        "ratio_white": ratio_white, "ratio_black": ratio_black, "ratio_hispanic": ratio_hispanic,
        "ratio_asian": ratio_asian, "gdp_per_capita": gdp_per_capita, "realgdp_per_capita": realgdp_per_capita,
        "epr": epr, "uer": uer, "lfpr": lfpr, "caseshiller": caseshiller, "futures_prices": futures_prices,
        "futures_underlying": futures_underlying,
    }

    for key, val in all_data.items():
        if isinstance(val, pd.DataFrame) and "date" in val.columns:
            all_data[key]["date"] = pd.to_datetime(all_data[key]["date"])
        elif isinstance(val, dict):
            for k2, df2 in val.items():
                if isinstance(df2, pd.DataFrame) and "date" in df2.columns:
                    all_data[key][k2]["date"] = pd.to_datetime(df2["date"])

    with open(pickle_fn, "wb") as f:
        pickle.dump(all_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    isdownloaded = True


# --------------------------------------------------
# Plotting using Plotly
# --------------------------------------------------

if isdownloaded:
    print("\nGenerating Interactive Plots...")
    nfig = 0
    todaystr = date.today().strftime(date_fmt)

    # ==================================================
    # Figure 1  (3 x 2) - matches BigPicture1.png
    # ==================================================
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            f"Stock and Gold as of {todaystr}",
            f"S&P500 / Gold as of {todaystr}",
            f"Inflation Index (10 years ago = 100) as of {todaystr}",
            f"S&P500 vs. GDP and M2 as of {todaystr}",
            f"Money Supply and GDP as of {todaystr}",
            f"Stock Market Valuation - Ratios as of {todaystr}",
        ),
        specs=[[{"secondary_y": True},  {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": True}],
               [{"secondary_y": True},  {"secondary_y": True}]],
        vertical_spacing=0.09, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    # --- (1,1) Stock and Gold ---
    fig.add_trace(line(all_data["SP500"], "S&P500", "blue",
                       legend=lm.new(1, 1, "upper left")), row=1, col=1)
    fig.add_trace(line(all_data["gold"], "Gold", "red",
                       legend=lm.new(1, 1, "lower right")),
                  row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="USD/OZ", row=1, col=1, secondary_y=True)

    # --- (1,2) S&P500 / Gold  (no legend, like matplotlib) ---
    fig.add_trace(line(all_data["SP500_gold"], "S&P500 / Gold", "blue",
                       showlegend=False), row=1, col=2)

    # --- (2,1) Inflation Index: each series normalized to ITS OWN value
    #     10 years ago (exactly like the matplotlib script) ---
    baseline_yearsago = 10
    baseline_date = pd.Timestamp(date(date.today().year - baseline_yearsago,
                                      date.today().month, date.today().day))
    leg_infl = lm.new(2, 1, "upper left")

    infl_series = [
        ("cpi",           "CPI",           "blue",    "dot", 4),
        ("cpi_food",      "CPI:Food",      "green",   None,  1.5),
        ("cpi_housing",   "CPI:Housing",   "aqua",    None,  1.5),
        ("cpi_medical",   "CPI:Medical",   "magenta", None,  1.5),
        ("cpi_education", "CPI:Education", "gold",    None,  1.5),
        ("gdpdef",        "GDP Deflator",  "red",     "dot", 4),
    ]
    for key, name, color, dash, width in infl_series:
        df_s = all_data[key]
        baseline = df_s.loc[df_s["date"] >= baseline_date, "value"].iloc[0]
        df_norm = df_s.copy()
        df_norm["value"] = df_norm["value"] / baseline * 100.0
        fig.add_trace(line(df_norm, name, color, width=width, dash=dash,
                           legend=leg_infl), row=2, col=1)
    fig.update_yaxes(title_text="Index", row=2, col=1)

    # --- (2,2) S&P500 vs GDP and M2 ---
    fig.add_trace(line(all_data["SP500_gdp"], "S&P500 / GDP", "blue",
                       legend=lm.new(2, 2, "upper left")), row=2, col=2)
    fig.add_trace(line(all_data["SP500_M2"], "S&P500 / M2", "red",
                       legend=lm.new(2, 2, "upper right")),
                  row=2, col=2, secondary_y=True)

    # --- (3,1) Money supply and GDP ---
    leg_ms = lm.new(3, 1, "upper left")
    fig.add_trace(line(all_data["MB"], "MB", "blue", legend=leg_ms), row=3, col=1)
    fig.add_trace(line(all_data["M2"], "M2", "red", legend=leg_ms), row=3, col=1)
    fig.add_trace(line(all_data["GDP"], "GDP", MPL_C0, legend=leg_ms), row=3, col=1)
    fig.add_trace(line(all_data["RealGDP"], "Real GDP (2009 USD)", "darkgreen",
                       legend=leg_ms), row=3, col=1)
    leg_ms2 = lm.new(3, 1, "upper center")
    # matplotlib's letter codes "m"/"c" are the muted colors, not pure magenta/cyan
    fig.add_trace(line(all_data["MB_GDP"], "MB/GDP", "#bf00bf", dash="dash",
                       legend=leg_ms2), row=3, col=1, secondary_y=True)
    fig.add_trace(line(all_data["M2_GDP"], "M2/GDP", "#00bfbf", dash="dash",
                       legend=leg_ms2), row=3, col=1, secondary_y=True)
    fig.update_yaxes(title_text="USD Bln", row=3, col=1, secondary_y=False)

    # --- (3,2) Valuation ratios ---
    fig.add_trace(line(all_data["ShillerPE10"], "Shiller P/E 10", "blue",
                       legend=lm.new(3, 2, "upper left")), row=3, col=2)
    fig.add_trace(line(all_data["TobinQ"], "Tobin's Q", "red",
                       legend=lm.new(3, 2, "upper right")),
                  row=3, col=2, secondary_y=True)

    style_figure(fig, xlim=(xlim_start, xlim_end))
    nfig += 1
    fig.write_html(os.path.join(PIC_DIR, f"BigPicture{nfig}.html"))

    # ==================================================
    # Figure 2  (3 x 2, 5 plots) - matches BigPicture2.png
    # ==================================================
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            f"Treasury Zero-Coupon Yield as of {todaystr}",
            f"Stock Market and Interest Rate Structure as of {todaystr}",
            f"Financial Stress Indicators (1) as of {todaystr}",
            f"Financial Stress Indicators (2) as of {todaystr}",
            f"Financial Stress Indicators (3) as of {todaystr}",
            "",
        ),
        specs=[[{"secondary_y": False}, {"secondary_y": True}],
               [{"secondary_y": True},  {"secondary_y": True}],
               [{"secondary_y": True},  None]],
        vertical_spacing=0.09, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    # --- (1,1) Treasury yields ---
    leg_ty = lm.new(1, 1, "upper left")
    for key, name, color in [
        ("treasury_yield20", "20 Yr", "blue"),
        ("treasury_yield10", "10 Yr", "green"),
        ("treasury_yield5",  "5 Yr",  "yellow"),
        ("treasury_yield2",  "2 Yr",  "orange"),
        ("treasury_yield1",  "1 Yr",  "red"),
    ]:
        fig.add_trace(line(all_data[key], name, color, width=0.5,
                           legend=leg_ty), row=1, col=1)
    fig.update_yaxes(title_text="%", row=1, col=1)

    # --- (1,2) Stock market and interest rate structure ---
    fig.add_trace(line(all_data["SP500"], "S&P500", "blue",
                       legend=lm.new(1, 2, "upper left")), row=1, col=2)
    leg_sp = lm.new(1, 2, "upper center")
    fig.add_trace(line(all_data["treasury_yield_spread"], "1Yr/15Yr",
                       "magenta", width=1, legend=leg_sp),
                  row=1, col=2, secondary_y=True)
    fig.add_trace(line(all_data["treasury_yield_spread_adj"], "1Yr/15Yr_MBAdj",
                       "cyan", width=1, legend=leg_sp),
                  row=1, col=2, secondary_y=True)
    # horizontal red line at 1 (no legend entry, like matplotlib)
    first_date = all_data["treasury_yield_spread"]["date"].iloc[0]
    last_date = all_data["treasury_yield_spread"]["date"].iloc[-1]
    fig.add_trace(go.Scatter(x=[first_date, last_date], y=[1, 1], mode="lines",
                             line=dict(color="red", width=1.5),
                             showlegend=False, hoverinfo="skip"),
                  row=1, col=2, secondary_y=True)

    # --- (2,1) Financial stress (1): VIX + TED + SOFR-T-bill ---
    fig.add_trace(line(all_data["vix"], "VIX", "blue",
                       legend=lm.new(2, 1, "upper left")), row=2, col=1)
    leg_fs1 = lm.new(2, 1, "upper right")
    fig.add_trace(line(all_data["tedspread"], "TED Spread (discontinued)",
                       "magenta", width=1, legend=leg_fs1),
                  row=2, col=1, secondary_y=True)
    fig.add_trace(line(all_data["SOFR_t3m"], "SOFR-T-bill Spread",
                       "purple", width=1, legend=leg_fs1),
                  row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="%", row=2, col=1, secondary_y=True)

    # --- (2,2) Financial stress (2): S&P500 + STL FSI + KC FSI ---
    fig.add_trace(line(all_data["SP500"], "S&P500", "blue",
                       legend=lm.new(2, 2, "upper left")), row=2, col=2)
    leg_fs2 = lm.new(2, 2, "upper center")
    fig.add_trace(line(all_data["stl_fsi"], "St. Louis Fed FSI", "red",
                       width=1, legend=leg_fs2), row=2, col=2, secondary_y=True)
    fig.add_trace(line(all_data["kc_fsi"], "Kansas City FSI", "green",
                       width=1, legend=leg_fs2), row=2, col=2, secondary_y=True)

    # --- (3,1) Financial stress (3): S&P500 + Cleveland FSI + ANFCI ---
    fig.add_trace(line(all_data["SP500"], "S&P500", "blue",
                       legend=lm.new(3, 1, "upper left")), row=3, col=1)
    leg_fs3 = lm.new(3, 1, "upper center")
    fig.add_trace(line(all_data["c_fsi"], "Cleveland FSI (discontinued)", "red",
                       width=1, legend=leg_fs3), row=3, col=1, secondary_y=True)
    fig.add_trace(line(all_data["anfci"], "Chicago Fed Adjusted National FCI",
                       "green", width=1, legend=leg_fs3),
                  row=3, col=1, secondary_y=True)

    style_figure(fig, xlim=(xlim_start, xlim_end))
    nfig += 1
    fig.write_html(os.path.join(PIC_DIR, f"BigPicture{nfig}.html"))

    # ==================================================
    # Figure 3  (2 x 2, 3 plots) - matches BigPicture3.png
    # ==================================================
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            f"Population as of {todaystr}",
            f"Labor Market Condition as of {todaystr}",
            f"S&P/Case-Shiller Home Price Indices as of {todaystr}",
            "",
        ),
        specs=[[{"secondary_y": True}, {"secondary_y": True}],
               [{"secondary_y": False}, None]],
        vertical_spacing=0.12, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    # --- (1,1) Population + GDP per capita ---
    leg_pop = lm.new(1, 1, "upper left")
    fig.add_trace(line(all_data["population"].assign(value=all_data["population"]["value"] / 1e6),
                       "Population", "blue", width=1, dash="dash",
                       legend=leg_pop), row=1, col=1)
    fig.add_trace(line(all_data["wa_population"].assign(value=all_data["wa_population"]["value"] / 1e6),
                       "Working Age (15-64) Population", "magenta", width=1,
                       dash="dash", legend=leg_pop), row=1, col=1)
    leg_gpc = lm.new(1, 1, "lower right")
    fig.add_trace(line(all_data["gdp_per_capita"], "GDP Per Capita", "red",
                       width=1, legend=leg_gpc), row=1, col=1, secondary_y=True)
    fig.add_trace(line(all_data["realgdp_per_capita"],
                       "Real GDP Per Capita (2009 USD)", "green", width=1,
                       legend=leg_gpc), row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Bln Persons", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="K USD", row=1, col=1, secondary_y=True)

    # --- (1,2) Labor market ---
    leg_lab = lm.new(1, 2, "lower left")
    fig.add_trace(line(all_data["epr"], "Employment-Population Ratio", "green",
                       width=1, legend=leg_lab), row=1, col=2)
    fig.add_trace(line(all_data["lfpr"], "Labor Force Participation Rate",
                       "blue", width=1, legend=leg_lab), row=1, col=2)
    fig.add_trace(line(all_data["uer"], "Unemployment Rate", "red", width=1,
                       legend=lm.new(1, 2, "upper center")),
                  row=1, col=2, secondary_y=True)
    fig.update_yaxes(title_text="%", row=1, col=2, secondary_y=False)
    fig.update_yaxes(title_text="%", row=1, col=2, secondary_y=True)

    # --- (2,1) Case-Shiller home price indices ---
    leg_cs = lm.new(2, 1, "upper left")
    for n, city in enumerate(cities_of_interest):
        city_df = all_data["caseshiller"][city]
        lw = 3 if city in ["National", "Chicago", "SanFrancisco"] else 1
        fig.add_trace(line(city_df, city, colors[n], width=lw,
                           legend=leg_cs), row=2, col=1)

    style_figure(fig, xlim=(xlim_start, xlim_end))
    nfig += 1
    fig.write_html(os.path.join(PIC_DIR, f"BigPicture{nfig}.html"))

    # ==================================================
    # Figures 4 & 5  (4 x 5 futures grids) - match BigPicture4/5.png
    # ==================================================
    def plot_futures(start_date, suptitle, fixed_xlim):
        """
        Futures grid like matplotlib: no subplot titles, a small legend with
        the commodity name in each panel, dotted grid, small tick labels.
        fixed_xlim=True  -> set the x range (long-term figure)
        fixed_xlim=False -> filter the data instead (short-term figure)
        """
        fut_fig = make_subplots(rows=4, cols=5,
                                vertical_spacing=0.06, horizontal_spacing=0.04)
        fut_lm = LegendManager(fut_fig)
        start_ts = pd.Timestamp(start_date)

        for i, comdty in enumerate(all_data["futures_underlying"]):
            r = (i // 5) + 1
            c = (i % 5) + 1
            df_fut = all_data["futures_prices"][comdty]
            if not fixed_xlim and not df_fut.empty:
                df_fut = df_fut[(df_fut["date"] >= start_ts) & (df_fut["date"] <= xlim_end)]
            if not df_fut.empty:
                fut_fig.add_trace(line(df_fut, comdty, "blue", width=1,
                                       legend=fut_lm.new(r, c, "upper right")),
                                  row=r, col=c)
            if fixed_xlim:
                fut_fig.update_xaxes(range=[pd.Timestamp(start_date), xlim_end],
                                     row=r, col=c)

        fut_fig.update_layout(
            template="plotly_white",
            plot_bgcolor="white", paper_bgcolor="white",
            width=fig_width, height=fig_height,
            margin=dict(l=50, r=30, t=70, b=30),
            title=dict(text=suptitle, x=0.5, xanchor="center",
                       font=dict(size=14)),
        )
        fut_fig.update_xaxes(**GRID, tickfont=dict(size=7), ticks="outside",
                             linecolor="black", mirror=True, zeroline=False)
        fut_fig.update_yaxes(**GRID, tickfont=dict(size=7), ticks="outside",
                             linecolor="black", mirror=True, zeroline=False)
        return fut_fig

    fig = plot_futures(date_future_plotstart_long,
                       f"Futures - Long Term ({future_yrs_long}-year) as of {todaystr}",
                       fixed_xlim=True)
    nfig += 1
    fig.write_html(os.path.join(PIC_DIR, f"BigPicture{nfig}.html"))

    fig = plot_futures(date_future_plotstart_short,
                       f"Futures - Short Term ({future_yrs_short}-year) as of {todaystr}",
                       fixed_xlim=False)
    nfig += 1
    fig.write_html(os.path.join(PIC_DIR, f"BigPicture{nfig}.html"))

    print(f"\nAll done! Browse the folder '{PIC_DIR}' for the interactive HTML plots.")
