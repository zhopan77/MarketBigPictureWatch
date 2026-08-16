"""
Translate a built figure's visible text.

Post-processing the finished figure rather than threading a language through
every builder: the builders stay single-language and readable, and adding a
locale means adding a dictionary rather than editing plotting code.

Anything absent from the table passes through unchanged, which is what keeps
tickers (CL, ES, 6E), index names (M2, VIX) and ratio labels correct without
having to enumerate them.
"""

from __future__ import annotations

import copy
import re

# "Population as of 2026-07-28" -> stem + date, so the 14 subplot titles do
# not each need a dated variant in the table.
_AS_OF = re.compile(r"^(?P<stem>.+?)\s+as of\s+(?P<date>\d{4}-\d{2}-\d{2})$")
# "CL<br>(no data)" -- the placeholder drawn on a futures panel whose download
# failed. Translating the pieces keeps a failed contract legible.
_NO_DATA = re.compile(r"^(?P<stem>.+?)<br>\(no data\)$")

ZH = {
    # ---- subplot / figure titles ----
    "Stock and Gold": "股票与黄金",
    "S&P500 / Gold": "标普500 / 黄金",
    "Inflation Index (10 years ago = 100)": "通胀指数（10年前 = 100）",
    "S&P500 vs. GDP and M2": "标普500 对比 GDP 与 M2",
    "Money Supply and GDP": "货币供应与 GDP",
    "Stock Market Valuation - Ratios": "股市估值 — 各项比率",
    "Treasury Zero-Coupon Yield": "国债零息收益率",
    "Stock Market and Interest Rate Structure": "股市与利率结构",
    "Financial Stress Indicators (1)": "金融压力指标（一）",
    "Financial Stress Indicators (2)": "金融压力指标（二）",
    "Financial Stress Indicators (3)": "金融压力指标（三）",
    "Population": "人口",
    "Labor Market Condition": "就业市场状况",
    "S&P/Case-Shiller Home Price Indices": "标普/凯斯-席勒房价指数",
    "Futures - Long Term (8-year)": "期货 — 长期（8年）",
    "Futures - Short Term (1-year)": "期货 — 短期（1年）",

    # ---- axis titles ----
    "Index": "指数",
    "USD/OZ": "美元/盎司",
    "USD Bln": "十亿美元",
    "Bln Persons": "十亿人",
    "K USD": "千美元",

    # ---- legend entries ----
    "S&P500": "标普500",
    "Gold": "黄金",
    "S&P500 / GDP": "标普500 / GDP",
    "S&P500 / M2": "标普500 / M2",
    "GDP Deflator": "GDP 平减指数",
    "CPI:Food": "CPI：食品",
    "CPI:Housing": "CPI：住房",
    "CPI:Medical": "CPI：医疗",
    "CPI:Education": "CPI：教育",
    "Real GDP (2009 USD)": "实际 GDP（2009年美元）",
    "Real GDP Per Capita (2009 USD)": "人均实际 GDP（2009年美元）",
    "GDP Per Capita": "人均 GDP",
    "Shiller P/E 10": "席勒市盈率（10年）",
    "Buffett Indicator": "巴菲特指标",
    "1 Yr": "1年", "2 Yr": "2年", "5 Yr": "5年",
    "10 Yr": "10年", "20 Yr": "20年",
    "1Yr/15Yr": "1年/15年",
    "1Yr/15Yr_MBAdj": "1年/15年（基础货币调整）",
    "TED Spread (discontinued)": "TED 利差（已停止发布）",
    "SOFR-T-bill Spread": "SOFR — 国库券利差",
    "St. Louis Fed FSI": "圣路易斯联储金融压力指数",
    "Kansas City FSI": "堪萨斯城联储金融压力指数",
    "Cleveland FSI (discontinued)": "克利夫兰联储金融压力指数（已停止发布）",
    "Chicago Fed Adjusted National FCI": "芝加哥联储调整后全国金融状况指数",
    "Population ": "人口 ",
    "Working Age (15-64) Population": "劳动年龄（15-64岁）人口",
    "Employment-Population Ratio": "就业人口比",
    "Labor Force Participation Rate": "劳动参与率",
    "Unemployment Rate": "失业率",

    # ---- Case-Shiller cities ----
    "National": "全国",
    "Chicago": "芝加哥",
    "SanFrancisco": "旧金山",
    "LosAngeles": "洛杉矶",
    "SanDiego": "圣地亚哥",
    "Portland": "波特兰",
    "Seattle": "西雅图",
    "Phoenix": "凤凰城",
    "Dallas": "达拉斯",

    # ---- futures panels ----
    # These are the descriptive names in data_pipeline.futures_underlying, NOT
    # the Yahoo symbols. The legend is the only label on each of the twenty
    # small panels, so leaving them English leaves the tab unreadable.
    "USDIndex": "美元指数",
    "EURIndex": "欧元指数",
    "JPYIndex": "日元指数",
    "5YrYield": "5年期国债收益率",
    "10YrYield": "10年期国债收益率",
    "Silver": "白银",
    "Copper": "铜",
    "CrudeOil": "WTI原油",
    "BrentCrudeOil": "布伦特原油",
    "Gasoline": "汽油",
    "NaturalGas": "天然气",
    "Wheat": "小麦",
    "Corn": "玉米",
    "LiveCattle": "活牛",
    "Cotton": "棉花",
    "Sugar": "白糖",
    "Coffee": "咖啡",
    "Cocoa": "可可",
    "OrangeJuice": "橙汁",

    # ---- connective ----
    "as of": "截至",
    "no data": "无数据",
}

# Deliberate pass-throughs: universally used as-is in Chinese finance writing,
# so they are not gaps in the table.
KEEP = {"%", "CPI", "GDP", "M2", "MB", "M2/GDP", "MB/GDP", "VIX"}

TABLES = {"zh": ZH}

# Plotly renders date ticks itself, so they cannot be fixed with a dictionary.
# tickformatstops swaps the pattern by zoom level, which matters because an
# 8-year chart wants "2026年" where a one-year chart wants "2026年7月". The
# "-" pad modifier drops the leading zero, giving 7月 rather than 07月.
_DAY_MS = 86400000
DATE_TICKS = {
    "zh": [
        {"dtickrange": [None, _DAY_MS], "value": "%Y年%-m月%-d日 %H:%M"},
        {"dtickrange": [_DAY_MS, _DAY_MS * 28], "value": "%Y年%-m月%-d日"},
        {"dtickrange": [_DAY_MS * 28, _DAY_MS * 300], "value": "%Y年%-m月"},
        {"dtickrange": [_DAY_MS * 300, None], "value": "%Y年"},
    ],
}


def _tr(text, table) -> str:
    if not isinstance(text, str) or not text.strip():
        return text
    if text in table:
        return table[text]
    m = _AS_OF.match(text)
    if m:
        stem = m.group("stem")
        return f"{table.get(stem, stem)} {table['as of']} {m.group('date')}"
    m = _NO_DATA.match(text)
    if m:
        stem = m.group("stem")
        return f"{table.get(stem, stem)}<br>（{table['no data']}）"
    return text


def translate_figure(fig, lang: str):
    """Return a copy of `fig` with its visible text in `lang`.

    Touches subplot-title annotations, the figure title, legend entries and
    axis titles. Everything else, including the data, is untouched.
    """
    table = TABLES.get(lang)
    if table is None:
        return fig

    f = copy.deepcopy(fig)

    for ann in (f.layout.annotations or []):
        if getattr(ann, "text", None):
            ann.text = _tr(ann.text, table)

    if f.layout.title and f.layout.title.text:
        f.layout.title.text = _tr(f.layout.title.text, table)

    for tr in f.data:
        if getattr(tr, "name", None):
            tr.name = _tr(tr.name, table)

    stops = DATE_TICKS.get(lang)
    for key in f.layout:
        if key.startswith(("xaxis", "yaxis")):
            axis = f.layout[key]
            title = getattr(axis, "title", None)
            if title is not None and getattr(title, "text", None):
                title.text = _tr(title.text, table)
            # Date ticks live on the x axes; applying the stops there localises
            # every tick label at whatever zoom the reader ends up at.
            if stops and key.startswith("xaxis"):
                axis.tickformatstops = stops
    return f


def untranslated(fig, lang: str) -> list:
    """Strings a locale has no entry for. Used by the build to report gaps
    rather than letting English quietly survive in a translated chart."""
    table = TABLES.get(lang)
    if table is None:
        return []
    missing = []
    def check(text):
        if not isinstance(text, str) or not text.strip():
            return
        if text in table:
            return
        m = _AS_OF.match(text) or _NO_DATA.match(text)
        stem = m.group("stem") if m else text
        if stem not in table and stem not in KEEP:
            missing.append(stem)
    for ann in (fig.layout.annotations or []):
        check(getattr(ann, "text", None))
    if fig.layout.title and fig.layout.title.text:
        check(fig.layout.title.text)
    for tr in fig.data:
        check(getattr(tr, "name", None))
    for key in fig.layout:
        if key.startswith(("xaxis", "yaxis")):
            t = getattr(getattr(fig.layout[key], "title", None), "text", None)
            check(t)
    return sorted(set(missing))
