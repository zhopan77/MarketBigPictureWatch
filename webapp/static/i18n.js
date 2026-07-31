/* Translation layer.
 *
 * Two mechanisms, because the page has two kinds of text:
 *   - static markup carries data-i18n="key" and is swapped in place;
 *   - strings built in JS call t("key") at render time.
 * Changing language therefore means: set the flag, swap the markup, re-render.
 *
 * Chinese here is Simplified, in a financial register rather than a literal
 * gloss: "sleeve" becomes 增强仓 (enhancement position) rather than a
 * word-for-word translation, and the ratio names use their standard Chinese
 * finance terms (夏普比率, 索提诺比率, 最大回撤).
 *
 * NOT translated: the contents of the macro charts on tabs 01-05. Their
 * titles and axis labels are baked into the figure JSON at build time, so
 * translating them means rebuilding the figures per language.
 */

const I18N = {
  en: {
    "app.title_1": "Market Big Picture",
    "app.title_2": "and Long-term Strategies",
    "app.title_full": "Market Big Picture and Long-term Strategies",
    "app.tagline": "See the big picture. Weather the market. Build wealth steadily.",
    "app.updated": "data updated",
    "app.nodata": "no data yet",
    "app.dark": "Dark mode",
    "app.lang": "Language",

    "tab.markets": "Markets, Inflation & Money",
    "tab.rates-stress": "Rates & Financial Stress",
    "tab.economy": "Population, Labor & Housing",
    "tab.futures-long": "Futures \u2014 Long Term (8y)",
    "tab.futures-short": "Futures \u2014 Short Term (1y)",
    "tab.all-weather": "All Weather Strategy",
    "tab.all-weather-lev": "All Weather Leverage Strategy",
    "panel.base": "All Weather 9",
    "panel.leverage": "All Weather 9 Leverage",

    "fact.through": "through",
    "fact.sleeve": "sleeve",
    "fact.lastadj": "last adjustment",
    "fact.nextupdate": "next update",
    "sched.manual": "manual",
    "sleeve.on": "sleeve ON",
    "sleeve.off": "sleeve OFF",
    "sleeve.fraction": "sleeve fraction",
    "sleeve.hint_a": "share of the book tilted into",
    "sleeve.hint_b": "while the sleeve is on",

    "stats.name": "Name",
    "stats.return": "Return",
    "stats.cagr": "CAGR",
    "stats.vol": "Volatility",
    "stats.dvol": "Down Vol",
    "stats.sharpe": "Sharpe",
    "stats.sortino": "Sortino",
    "stats.ulcer": "Ulcer",
    "stats.upi": "UPI",
    "stats.maxdd": "MaxDD",

    "series.strategy": "All Weather Strategy",
    "series.strategy_lev": "All Weather Leverage Strategy",
    "series.spy": "SPY buy & hold",
    "series.qqq": "QQQ buy & hold",
    "chart.cumret": "cumulative return",
    "chart.growth": "growth of 100 (log)",
    "chart.logscale": "log scale",
    "range.begin": "begin",
    "range.end": "end",
    "range.max": "Max",

    "alloc.title": "Allocation",
    "alloc.asof": "as of",
    "alloc.invest": "invest",
    "alloc.export": "Export allocation CSV",
    "alloc.symbol": "Symbol",
    "alloc.holding": "Holding",
    "alloc.weight": "Weight",
    "alloc.amount": "Amount",
    "alloc.price": "Price",
    "alloc.shares": "Shares",

    "monthly.title": "Monthly returns",
    "monthly.caption": "strategy, % \u2014 selected period; the first month is partial unless the period starts on a month boundary",
    "monthly.year": "Year",
    "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],

    "log.title": "Adjustment log \u2014 every rebalance and sleeve flip",
    "log.entries": "entries",
    "log.to": "to",
    "log.none": "no entries",
    "log.rebal": "REBAL",
    "log.toport": "to PORT",
    "log.tosleeve": "to",

    "msg.loading": "Loading\u2026",
    "msg.unavailable": "Strategy not available.",
    "msg.build": "Build it with",
    "msg.reload": "then reload.",
    "msg.figunavailable": "Figure unavailable.",
    "msg.figbuild": "To build the figures, run",
    "msg.figreload": "and reload this page.",
    "msg.loadfail": "Could not load the figure.",
    "msg.stale_a": "This cache was built by an older version",
    "msg.stale_b": "so some of it may be incomplete. Rebuild with",
    "msg.noplotly": "Charts need plotly.js, which did not load. Everything else on this tab is unaffected.",
    "msg.figlang": "Charts for this language have not been built yet \u2014 showing English. Build them with",

    "foot.sources": "Sources: FRED \u00b7 Yahoo Finance \u00b7 multpl.com",
    "foot.disclaimer": "Not investment advice.",
  },

  zh: {
    "app.title_1": "\u5e02\u573a\u603b\u89c8",
    "app.title_2": "\u548c\u957f\u671f\u7b56\u7565",
    "app.title_full": "\u5e02\u573a\u603b\u89c8\u548c\u957f\u671f\u7b56\u7565",
    "app.tagline": "\u6d1e\u5bdf\u5927\u5c40  \u7a7f\u8d8a\u725b\u718a  \u7a33\u5065\u79ef\u7d2f\u8d22\u5bcc",
    "app.updated": "\u6570\u636e\u66f4\u65b0",
    "app.nodata": "\u6682\u65e0\u6570\u636e",
    "app.dark": "\u6df1\u8272\u6a21\u5f0f",
    "app.lang": "\u8bed\u8a00",

    "tab.markets": "\u5e02\u573a\u3001\u901a\u80c0\u4e0e\u8d27\u5e01",
    "tab.rates-stress": "\u5229\u7387\u4e0e\u91d1\u878d\u538b\u529b",
    "tab.economy": "\u4eba\u53e3\u3001\u5c31\u4e1a\u4e0e\u4f4f\u623f",
    "tab.futures-long": "\u671f\u8d27 \u2014 \u957f\u671f\uff088\u5e74\uff09",
    "tab.futures-short": "\u671f\u8d27 \u2014 \u77ed\u671f\uff081\u5e74\uff09",
    "tab.all-weather": "\u5168\u5929\u5019\u7b56\u7565",
    "tab.all-weather-lev": "\u5168\u5929\u5019\u6760\u6746\u7b56\u7565",
    "panel.base": "\u5168\u5929\u5019\u7b56\u7565",
    "panel.leverage": "\u5168\u5929\u5019\u6760\u6746\u7b56\u7565",

    "fact.through": "\u6570\u636e\u622a\u81f3",
    "fact.sleeve": "\u589e\u5f3a\u4ed3",
    "fact.lastadj": "\u6700\u8fd1\u8c03\u4ed3",
    "fact.nextupdate": "\u4e0b\u6b21\u66f4\u65b0",
    "sched.manual": "\u624b\u52a8",
    "sleeve.on": "\u589e\u5f3a\u4ed3 \u5f00\u542f",
    "sleeve.off": "\u589e\u5f3a\u4ed3 \u5173\u95ed",
    "sleeve.fraction": "\u589e\u5f3a\u4ed3\u6bd4\u4f8b",
    "sleeve.hint_a": "\u589e\u5f3a\u4ed3\u5f00\u542f\u65f6\u6295\u5165",
    "sleeve.hint_b": "\u7684\u8d44\u91d1\u6bd4\u4f8b",

    "stats.name": "\u540d\u79f0",
    "stats.return": "\u7d2f\u8ba1\u6536\u76ca",
    "stats.cagr": "\u5e74\u5316\u6536\u76ca",
    "stats.vol": "\u6ce2\u52a8\u7387",
    "stats.dvol": "\u4e0b\u884c\u6ce2\u52a8\u7387",
    "stats.sharpe": "\u590f\u666e\u6bd4\u7387",
    "stats.sortino": "\u7d22\u63d0\u8bfa\u6bd4\u7387",
    "stats.ulcer": "\u6e83\u75a1\u6307\u6570",
    "stats.upi": "\u9a6c\u4e01\u6bd4\u7387",
    "stats.maxdd": "\u6700\u5927\u56de\u64a4",

    "series.strategy": "\u5168\u5929\u5019\u7b56\u7565",
    "series.strategy_lev": "\u5168\u5929\u5019\u6760\u6746\u7b56\u7565",
    "series.spy": "SPY \u4e70\u5165\u6301\u6709",
    "series.qqq": "QQQ \u4e70\u5165\u6301\u6709",
    "chart.cumret": "\u7d2f\u8ba1\u6536\u76ca",
    "chart.growth": "\u51c0\u503c\u589e\u957f\uff08\u5bf9\u6570\uff0c\u8d77\u70b9100\uff09",
    "chart.logscale": "\u5bf9\u6570\u5750\u6807",
    "range.begin": "\u8d77\u59cb",
    "range.end": "\u7ed3\u675f",
    "range.max": "\u5168\u90e8",

    "alloc.title": "\u5f53\u524d\u914d\u7f6e",
    "alloc.asof": "\u622a\u81f3",
    "alloc.invest": "\u6295\u8d44\u91d1\u989d",
    "alloc.export": "\u5bfc\u51fa\u914d\u7f6e CSV",
    "alloc.symbol": "\u4ee3\u7801",
    "alloc.holding": "\u540d\u79f0",
    "alloc.weight": "\u6743\u91cd",
    "alloc.amount": "\u91d1\u989d",
    "alloc.price": "\u4ef7\u683c",
    "alloc.shares": "\u80a1\u6570",

    "monthly.title": "\u6708\u5ea6\u6536\u76ca",
    "monthly.caption": "\u7b56\u7565\uff0c%\uff08\u6309\u6240\u9009\u533a\u95f4\uff1b\u82e5\u533a\u95f4\u975e\u81ea\u7136\u6708\u8d77\u59cb\uff0c\u9996\u6708\u4e3a\u4e0d\u5b8c\u6574\u6708\u4efd\uff09",
    "monthly.year": "\u5168\u5e74",
    "months": ["1\u6708", "2\u6708", "3\u6708", "4\u6708", "5\u6708", "6\u6708",
               "7\u6708", "8\u6708", "9\u6708", "10\u6708", "11\u6708", "12\u6708"],

    "log.title": "\u8c03\u4ed3\u8bb0\u5f55 \u2014 \u6bcf\u6b21\u518d\u5e73\u8861\u4e0e\u589e\u5f3a\u4ed3\u5207\u6362",
    "log.entries": "\u6761\u8bb0\u5f55",
    "log.to": "\u81f3",
    "log.none": "\u6682\u65e0\u8bb0\u5f55",
    "log.rebal": "\u518d\u5e73\u8861",
    "log.toport": "\u8f6c\u56de\u7ec4\u5408",
    "log.tosleeve": "\u8f6c\u5165",

    "msg.loading": "\u52a0\u8f7d\u4e2d\u2026",
    "msg.unavailable": "\u7b56\u7565\u6570\u636e\u4e0d\u53ef\u7528\u3002",
    "msg.build": "\u8bf7\u8fd0\u884c",
    "msg.reload": "\u7136\u540e\u5237\u65b0\u9875\u9762\u3002",
    "msg.figunavailable": "\u56fe\u8868\u4e0d\u53ef\u7528\u3002",
    "msg.figbuild": "\u8bf7\u8fd0\u884c",
    "msg.figreload": "\u5e76\u5237\u65b0\u9875\u9762\u3002",
    "msg.loadfail": "\u56fe\u8868\u52a0\u8f7d\u5931\u8d25\u3002",
    "msg.stale_a": "\u7f13\u5b58\u7531\u65e7\u7248\u672c\u751f\u6210",
    "msg.stale_b": "\u90e8\u5206\u5185\u5bb9\u53ef\u80fd\u4e0d\u5b8c\u6574\u3002\u8bf7\u91cd\u5efa\uff1a",
    "msg.noplotly": "\u56fe\u8868\u9700\u8981 plotly.js\uff0c\u4f46\u672a\u80fd\u52a0\u8f7d\u3002\u672c\u9875\u5176\u4f59\u5185\u5bb9\u4e0d\u53d7\u5f71\u54cd\u3002",
    "msg.figlang": "\u672c\u8bed\u8a00\u7684\u56fe\u8868\u5c1a\u672a\u751f\u6210\uff0c\u5f53\u524d\u663e\u793a\u82f1\u6587\u3002\u8bf7\u8fd0\u884c\uff1a",

    "foot.sources": "\u6570\u636e\u6765\u6e90\uff1aFRED \u00b7 Yahoo Finance \u00b7 multpl.com",
    "foot.disclaimer": "\u4ee5\u4e0a\u5185\u5bb9\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002",
  },
};

let LANG = "en";

function t(key) {
  const table = I18N[LANG] || I18N.en;
  const v = table[key];
  return v === undefined ? (I18N.en[key] !== undefined ? I18N.en[key] : key) : v;
}

function currentLang() { return LANG; }

/** Swap every data-i18n element, then let the caller re-render generated text. */
function applyLanguage(lang, rerender) {
  LANG = I18N[lang] ? lang : "en";
  document.documentElement.lang = LANG === "zh" ? "zh-Hans" : "en";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.title = t("app.title_full");
  if (typeof rerender === "function") rerender();
}

const DEFAULT_LANG = "en";

/* Every page load starts in English.
 *
 * The choice is deliberately NOT persisted: a remembered language is
 * indistinguishable from a wrong default once you have forgotten you picked
 * it, which is precisely the confusion it caused. The radio buttons still
 * switch freely within a session. To make it sticky instead, save LANG to
 * localStorage in applyLanguage() and read it back here.
 *
 * navigator.language is also deliberately not sniffed, so a Chinese-locale
 * browser still opens in English. */
function initLanguage() {
  // Clear any preference left by an earlier build that did persist it.
  try { localStorage.removeItem("mw-lang"); } catch (e) { /* noop */ }
  return DEFAULT_LANG;
}
