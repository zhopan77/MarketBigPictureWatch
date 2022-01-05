println("Loading packages...")
using PyPlot
using HTTP
using DataFrames
using Dates
using QuandlAccess
using Statistics
using MarketData
println("Done.\n")

# REFERENCES
# http://www.financialsense.com/contributors/cris-sheridan/financial-stress-measures

# FOR MORE COMPLETE US STATISTICS
# https://www.quandl.com/c/usa
# http://www.multpl.com/sitemap

#########################################
# number of years to obtain data
macro_yrs_ultralong = 20
future_yrs_long = 8
future_yrs_short = 1
date_plotend = today()
#########################################

MonthNameToNumber = Dict("JAN"=>1, "FEB"=>2, "MAR"=>3, "APR"=>4, "MAY"=>5, "JUN"=>6, "JUL"=>7, "AUG"=>8, "SEP"=>9, "OCT"=>10, "NOV"=>11, "DEC"=>12)

legend_fontsize = 10
maxattempts = 2
dpi = 109
figsize = (1920/dpi, 1080/dpi)
fmt = "yyyy-mm-dd" # date format string
isverbose = true
nrows_verbose = 5

function get_daily_data_from_fred(series_name::String, date_start::Date, date_end::Date, isverbose::Bool=true, nrows_verbose::Int=5)::DataFrame
    data = DataFrame(MarketData.fred(series_name))
    if isverbose
        println(data[1:nrows_verbose, :], "\n...")
    end
    DataFrames.rename!(data, [:date, :valuestr])
    data = data[date_start .<= data[!, :date] .<= date_end, :]
    data[!, :value] = zeros(Float64, size(data, 1))
    if typeof(data[1, :valuestr]) <: String
        for n = 1:size(data, 1)
            if data[n, :valuestr] == "."
                data[n, :value] = NaN
            else
                data[n, :value] = parse.(Float64, data[n, :valuestr])
            end
        end
    else
        data[!, :value] = data[!, :valuestr]
    end
    data = data[!, ["date", "value"]]
    data = data[completecases(data), :]
    sort!(data, [:date])
    return data
end

function get_daily_data_from_quandl(quandl::Quandl, series_name::String, date_start::Date, date_end::Date, cols::Vector{String}, isverbose::Bool=true, nrows_verbose::Int=5)
    data = quandl(QuandlAccess.TimeSeries(series_name); start_date = date_start, end_date = date_end)
    if isverbose
        println(data[1:nrows_verbose, :], "\n...")
    end
    data = data[!, cols]
    data = data[completecases(data), :]
    if length(cols) == 2
        DataFrames.rename!(data, [:date, :value])
        sort!(data, [:date])
        return data
    else
        datas = []
        for n = 1:(length(cols)-1)
            datatmp = data[!, [cols[1], cols[1+n]]]
            DataFrames.rename!(datatmp, [:date, :value])
            sort!(datatmp, [:date])
            push!(datas, datatmp)
        end
        return Tuple(datas)
    end
end

function get_daily_data_from_yahoo(symbol::String, date_start::Date, date_end::Date, isverbose::Bool=true, nrows_verbose::Int=5)::DataFrame
    data = DataFrame(MarketData.yahoo(symbol, MarketData.YahooOpt(period1 = DateTime(date_start), period2 = DateTime(date_end))))
    if isverbose
        println(data[1:nrows_verbose, :], "\n...")
    end
    data = data[!, ["timestamp", "Close"]]
    DataFrames.rename!(data, [:date, :value])
    data = data[completecases(data), :]
    sort!(data, [:date])
    return data
end

function calc_two_dataframes(data1::DataFrame, operator::String, data2::DataFrame)::DataFrame
    data = innerjoin(data1, data2, on=:date, makeunique=true)
    data = data[completecases(data), :]
    if operator == "/"
        data[!, :ratio] = data[!, :value] ./ data[!, :value_1]
    elseif operator == "*"
        data[!, :ratio] = data[!, :value] .* data[!, :value_1]
    elseif operator == "+"
        data[!, :ratio] = data[!, :value] .+ data[!, :value_1]
    elseif operator == "-"
        data[!, :ratio] = data[!, :value] .- data[!, :value_1]
    else
        error("Unknown dataframe operator $operator")
    end

    return data
end


function main()
    for n = 1:40; println(); end;

    qd_authtoken = ""
    try
        qd_authtoken = ENV["QUANDL_API_KEY"]
    catch 
        error("Quandl key needs to be configured properly in enviromental variables QUANDL_API_KEY first!")
    end

    quandl = Quandl(qd_authtoken)
    
    date_plotstart = date_plotend - Day(Int(round(macro_yrs_ultralong*365.25, digits=0)))
    date_future_plotstart_long = date_plotend -  Day(Int(round(future_yrs_long*365.25, digits=0)))
    date_future_plotstart_short = date_plotend - Day(Int(round(future_yrs_short*365.25, digits=0)))
    
    cities_of_interest = ["National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego", "Portland", "Seattle"]
    colors = ["black", "green", "blue", "cyan", "magenta", "red", "yellow", "darkblue", "pink", "purple", "orange",
              "brown"]
    plotfolder = "./StockMarketBigPictureWatchPlots"
    
    println("Downloading data from Quandl, Fred, Yahoo, and S&P...\n")
    
    flag_downloaded = false
    nattempts = 0

    SP500, gold, SP500gold, SP500_gold = nothing, nothing, nothing, nothing
    close("all")

    # Permalink of any Quandl data set: https://www.quandl.com/data/xxx/yyy
    # where xxx/yyy is the Quandl Code

    # S&P500 index
    println("************** S&P500 (Fred) **************")
    SP500 = get_daily_data_from_fred("SP500", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # Gold price
    println("\n************** Gold price (Quandl) **************")
    gold = get_daily_data_from_quandl(quandl, "LBMA/GOLD", date_plotstart, date_plotend, ["Date", "USD (PM)"], isverbose, nrows_verbose)

    # S&P500 / Gold
    SP500_gold = calc_two_dataframes(SP500, "/", gold)
    
    # Shiller P/E 10 ratio
    println("\n************** Shiller P/E 10 (Quandl) **************")
    ShillerPE10 = get_daily_data_from_quandl(quandl, "MULTPL/SHILLER_PE_RATIO_MONTH", date_plotstart, date_plotend, ["Date", "Value"], isverbose, nrows_verbose)

    # Tobin"s Q ratio
    # Nonfinancial Corporate Business; Corporate Equities; Liability, Level            
    println("\n************** Nonfinancial Corporate Business; Corporate Equities; Liability, Level (Fred) **************")
    equity = get_daily_data_from_fred("MVEONWMVBSNNCB", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Nonfinancial Corporate Business; Net Worth, Level
    println("\n************** Nonfinancial Corporate Business; Net Worth, Level (Fred) **************")
    networth = get_daily_data_from_fred("TNWMVBSNNCB", date_plotstart, date_plotend, isverbose, nrows_verbose)
    TobinQ = calc_two_dataframes(equity, "/", networth)

    # Inflation - CPI
    println("\n************** CPI (Fred) **************")
    cpi = get_daily_data_from_fred("CPIAUCSL", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # CPI By Group
    println("\n************** CPI: Food (Fred) **************")
    cpi_food = get_daily_data_from_fred("CPIUFDSL", date_plotstart, date_plotend, isverbose, nrows_verbose)
    println("\n************** CPI: Housing (Fred) **************")
    cpi_housing = get_daily_data_from_fred("CPIHOSSL", date_plotstart, date_plotend, isverbose, nrows_verbose)
    println("\n************** CPI: Medical (Fred) **************")
    cpi_medical = get_daily_data_from_fred("CPIMEDSL", date_plotstart, date_plotend, isverbose, nrows_verbose)
    println("\n************** CPI: Education (Fred) **************")
    cpi_education = get_daily_data_from_fred("CUSR0000SAE1", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # Inflation - GDP Deflator
    println("\n************** GDP Deflator (Fred) **************")
    gdpdef = get_daily_data_from_fred("GDPDEF", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # S&P500 / GDP Deflator
    SP500_gdpdef = calc_two_dataframes(SP500, "/", gdpdef)
   
    # Money Supply - Monetary Base
    println("\n************** Monetary Base (Fred) **************")
    MB = get_daily_data_from_fred("BOGMBASEW", date_plotstart, date_plotend, isverbose, nrows_verbose)
    MB[!, :value] /= 1000  # convert millions of dollars to billions of dollars
    
    # Money Supply - M2
    println("\n************** M2 (Fred) **************")
    M2 = get_daily_data_from_fred("M2", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # S&P500 / M2
    SP500_M2 = calc_two_dataframes(SP500, "/", M2)
    
    # US Treasury Zero-Coupon Yield Curve
    println("\n************** US Treasury Zero-Coupon Yield Curve (Quandl) **************")
    treasury_yield1, treasury_yield15 = get_daily_data_from_quandl(quandl, "FED/SVENY", date_plotstart, date_plotend, ["Date", "SVENY01", "SVENY15"], isverbose, nrows_verbose)
    # short term interest rate (1 Yr) / long term interest rate (15 Yr)
    treasury_yield_spread = calc_two_dataframes(treasury_yield1, "/", treasury_yield15)
    
    # US GDP, billions
    println("\n************** GDP (Fred) **************")
    GDP = get_daily_data_from_fred("GDP", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Real GDP
    println("\n************** Real GDP (Fred) **************")
    RealGDP = get_daily_data_from_fred("GDPC1", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # S&P500 / GDP
    SP500_gdp = calc_two_dataframes(SP500, "/", GDP)
    
    # Deflated GDP
    GDP_deflated = calc_two_dataframes(GDP, "/", gdpdef)
    GDP_deflated[!, :value] *= 100
    
    # S&P500 / Deflated GDP
    SP500_deflgdp = calc_two_dataframes(SP500, "/", GDP_deflated)
    
    # Excess Monetary Base Explansion: MB / GDP
    MB_GDP = calc_two_dataframes(MB, "/", GDP)
    M2_GDP = calc_two_dataframes(M2, "/", GDP)
    # Normalized to pre-2008 era (1982 to May 2008) which was pretty flat
    MB_GDP_norm = copy(MB_GDP)
    MB_GDP_norm[!, :value] = MB_GDP[!, :value] / mean(filter(x -> Date(1982, 1, 1) < x.date < Date(2008, 5, 1), MB_GDP)[!, :value])
    
   
    # Adjust treasury yield spread using excess monetary base expansion
    treasury_yield_spread_adj = calc_two_dataframes(treasury_yield_spread, "*", MB_GDP_norm)
    
    # TED spread
    println("\n************** TED Spread (Fred) **************")
    ted_spread = get_daily_data_from_fred("TEDRATE", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # VIX
    println("\n************** VIX (Yahoo) **************")
    vix = get_daily_data_from_yahoo("^VIX", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # Financial Stress Indices
    # St. Louis Fed Financial Stress Index
    println("\n************** St. Louis Fed Financial Stress Index **************")
    stl_fsi = get_daily_data_from_fred("STLFSI", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Kansas City Financial Stress Index
    println("\n************** Kansas City Financial Stress Index **************")
    kc_fsi = get_daily_data_from_fred("KCFSI", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Cleveland Financial Stress Index
    println("\n************** Cleveland Financial Stress Index **************")
    c_fsi = get_daily_data_from_fred("CFSI", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Chicago Fed National Financial Conditions Index
    println("\n************** Chicago Fed National Financial Conditions Index **************")
    n_fci = get_daily_data_from_fred("NFCI", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # Population
    println("\n************** US Population (Fred) **************")
    population = get_daily_data_from_fred("POP", date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    # Working age population (age 15-64)
    println("\n************** Working age population (age 15-64) (Fred) **************")
    wa_population = get_daily_data_from_fred("LFWA64TTUSM647N", date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    # ratio_white = fred.get_series(series_id="LNU00000003").reindex(population.index,
    #                                                                method="ffill")/population.iloc[:, 0]*100
    # ratio_black = fred.get_series(series_id="LNU00000006").reindex(population.index,
    #                                                                method="ffill")/population.iloc[:, 0]*100
    # ratio_hispanic = fred.get_series(series_id="LNU00000009").reindex(population.index,
    #                                                                   method="ffill")/population.iloc[:, 0]*100
    # ratio_asian = fred.get_series(series_id="LNU00032183").reindex(population.index,
    #                                                                method="ffill")/population.iloc[:, 0]*100
    gdp_per_capita = calc_two_dataframes(GDP, "/", population)
    gdp_per_capita[!, :value] *= (1 / 1e3 / 1e3)   # thousand $ per person
    realgdp_per_capita = calc_two_dataframes(RealGDP, "/", population)
    realgdp_per_capita[!, :value] *= (1e9 / 1e3 / 1e3)   # thousand $ per person
    
   
#         # Labor Market
#         # Civilian Employment-Population ratio
#         println("\n************** Civilian Employment-Population ratio **************")
#         epr = qd.get("FRED/EMRATIO", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # Civilian Unemployment Rate
#         println("\n************** Civilian Unemployment Rate **************")
#         uer = qd.get("FRED/UNRATE", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # Civilian Labor Force Participation Rate
#         println("\n************** Civilian Labor Force Participation Rate **************")
#         lfpr = fred.get_series(series_id="CIVPART")
    
#         # S&P/Case-Shiller Housing Indexes
#         # The numbers on both Quandl are old; FRED only has 20-city and 10-city index, not city by city
#         # Export Excel files from S&P website directly and extract data
#         CaseShillerIndexID = dict(City20=10001890, Chicago=10001903, SanFrancisco=10001896, LosAngeles=10001893,
#                                   SanDiego=10001894, NewYork=10001911, Portland=10001913, Seattle=10001915,
#                                   Atlanta=10001901, Boston=10001905, Charlotte=10001908, Cleveland=10001912,
#                                   Dallas=10001914, Denver=10001897, Detroit=10001906, LasVegas=10001909, Miami=10001899,
#                                   Minneapolis=10001907, Phoenix=10001891, Tampa=10001900, WashingtonDC=10001898,
#                                   City10=10001889, National=10006000)
    
#         caseshiller = dict()
#         for city in cities_of_interest
#             println("\n************** Case Shiller Index: " * city * " **************")
#             fn = fn = "./MarketBigPictureWatch/CaseShiller_{:s}.xls".format(city)
#             open(fn, "wb") do f
#                 response = requests.get("http://us.spindices.com/idsexport/file.xls?hostIdentifier=48190c8c-42c4-46af-"
#                                         "8d1a-0cd5db894797&selectedModule=PerformanceGraphView&selectedSubModule=Graph&"
#                                         "yearFlag=all&indexId={:d}".format(CaseShillerIndexID[city]))
#                 if not response.ok
#                     print("Download {:s} failed!".format(fn))
#                 end
#                 for block in response.iter_content(1024)
#                     if not block
#                         break
#                     end
#                     f.write(block)
#                 end
#             end
#             open(fn, "rb") do f
#                 caseshiller[city] = pd.read_excel(f, header=6, skip_footer=4)
#                 dateindex = []
#                 for d in caseshiller[city].ix[:, 0]
#                     dd = d.strip()
#                     month = MonthNameToNumber[dd.split("-")[0].upper()]
#                     year = dd.split("-")[1]
#                     dateindex.append(pd.Timestamp("{:s}-{:d}-{:d}".format(year, month, 15)))
#                 end
#                 caseshiller[city].index = dateindex
#             end
#         # caseshiller_20 = qd.get("SANDP/HPI_COMPOSITE20_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_CHI = qd.get("SANDP/HPI_CHICAGO_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_SF = qd.get("SANDP/HPI_SANFRANCISCO_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_LA = qd.get("SANDP/HPI_LOSANGELES_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_NY = qd.get("SANDP/HPI_NEWYORK_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_SD = qd.get("SANDP/HPI_SANDIEGO_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_POR = qd.get("SANDP/HPI_PORTLAND_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
#         # caseshiller_SEA = qd.get("SANDP/HPI_SEATTLE_SA", trim_start=date_plotstart, trim_end=date_plotend, authtoken=qd_authtoken)
    
#         # Commodity and Energy Prices represented in Continuous Front-Month Future Contracts
#         futures_underlying = ["USD", "EUR", "JPY", "2YrNote", "10YrNote", "Gold", "Silver", "Copper",
#                               "CrudeOil", "BrentCrudeOil", "Gasoline", "NaturalGas", "Wheat", "Corn", "LiveCattle",
#                               "Cotton", "Sugar", "Coffee", "Cocoa", "OrangeJuice"]
#         futures_symbols = ["ICE_DX1", "CME_EC1", "CME_JY1", "CME_TU1", "CME_TY1", "CME_GC1", "CME_SI1", "CME_HG1",
#                            "CME_CL1", "CME_BZ1", "CME_RB1", "CME_NG1", "CME_W1", "CME_C1", "CME_LC1",
#                            "ICE_CT1", "ICE_SB1", "ICE_KC1", "ICE_CC1", "ICE_CC1"]
#         futures_contracts = dict(zip(futures_underlying, futures_symbols))
    
#         futures_prices = dict()
#         for comdty in futures_underlying
#             println("\n************** Futures: " * comdty * " **************")
#             tmp = qd.get("CHRIS/" + futures_contracts[comdty], trim_start=date_future_plotstart_long, trim_end=date_plotend,
#                          authtoken=qd_authtoken).loc[:, "Settle"]
#             tmp[tmp == 0] = np.nan
#             futures_prices[comdty] = tmp.dropna()
#         end
    
    print("\nAll downloads finished!\n")
    nfig = 0
    #########################################################################
    # Plots

    figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows = 3
    ncols = 2

    #...........................
    todaystr = Dates.format(today(), fmt)

    nplot = 0

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500[!, :date], SP500[!, :value], "b-", label="S&P500")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(gold[!, :date], gold[!, :value], "r-", label="Gold")
    ax2.set_ylabel("USD/OZ")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="lower right")
    grid(true)
    PyPlot.title("Stock and Gold as of " * todaystr)

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500_gold[!, :date], SP500_gold[!, :ratio], "b-")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    grid(true)
    PyPlot.title("S&P500 / Gold as of " * todaystr)

    #...........................

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(cpi[!, :date], cpi[!, :value], ":", color="blue", linewidth=4, label="CPI")
    ax.plot(cpi_food[!, :date], cpi_food[!, :value], "-", color="green", label="CPI:Food")
    ax.plot(cpi_housing[!, :date], cpi_housing[!, :value], "-", color="aqua", label="CPI:Housing")
    ax.plot(cpi_medical[!, :date], cpi_medical[!, :value], "-", color="magenta", label="CPI:Medical")
    ax.plot(cpi_education[!, :date], cpi_education[!, :value], "-", color="gold", label="CPI:Education")
    ax.plot(gdpdef[!, :date], gdpdef[!, :value], ":", color="red", linewidth=4, label="GDP Deflator")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    plt.grid(true)
    plt.title("Inflation as of " * todaystr)
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500_gdp[!, :date], SP500_gdp[!, :value], "b-", label="S&P500 / GDP")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(SP500_M2[!, :date], SP500_M2[!, :value], "r-", label="S&P500 / M2")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
    plt.title("S&P500 / M2 as of " * todaystr)
    plt.grid(true)
    plt.title("S&P500 vs. GDP and M2 as of " * todaystr)

    #...........................
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(MB.index, MB.iloc[:, 0], "b-", label="MB")
#         ax.plot(M2.index, M2.iloc[:, 0], "r-", label="M2")
#         ax.plot(GDP.index, GDP.iloc[:, 0], "-", label="GDP")
#         ax.plot(RealGDP.index, np.array(RealGDP), "-", color="darkgreen", label="Real GDP (2009$)")
#         ax.set_xlim([date_plotstart, date_plotend])
#         ax.set_ylabel("Bln$")
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(MB_GDP.index, np.array(MB_GDP), "m--", label="MB/GDP")
#         ax2.plot(M2_GDP.index, np.array(M2_GDP), "c--", label="M2/GDP")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
#         plt.grid(true)
#         plt.title("Money Supply and GDP as of " * todaystr)
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(ShillerPE10.index, ShillerPE10.iloc[:, 0], "b-", label="Shiller P/E 10")
#         ax.set_xlim([date_plotstart, date_plotend])
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(TobinQ.index, np.array(TobinQ), "r-", label="Tobin's Q")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
#         plt.grid(true)
#         plt.title("Stock Market Valuation - Ratios as of " * todaystr)
    
#         nfig += 1
#         plt.savefig("./MarketBigPictureWatch/BigPicture{:d}.png".format(nfig))
    
#         #-------------------------------------------------------------------------
    
#         plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    
#         nrows = 3
#         ncols = 2
#         nplot = 0
    
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(treasury_yield.index, treasury_yield["SVENY01"], "-", color="red", linewidth=0.5, label="1 Yr")
#         ax.plot(treasury_yield.index, treasury_yield["SVENY02"], "-", color="orange", linewidth=0.5, label="2 Yr")
#         ax.plot(treasury_yield.index, treasury_yield["SVENY05"], "-",  color="yellow", linewidth=0.5, label="5 Yr")
#         ax.plot(treasury_yield.index, treasury_yield["SVENY10"], "-",  color="green", linewidth=0.5, label="10 Yr")
#         ax.plot(treasury_yield.index, treasury_yield["SVENY20"], "-",  color="blue", linewidth=0.5, label="20 Yr")
#         ax.set_xlim([date_plotstart, date_plotend])
#         ax.set_ylabel("%")
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
#         plt.grid(true)
#         plt.title("Treasury Zero-Coupon Yield as of " * todaystr)
    
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(SP500.index, SP500["Close"], "-", color="blue", label="S&P500")
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(treasury_yield_spread.index, np.array(treasury_yield_spread), "-",
#                  color="magenta", linewidth=1, label="1Yr/15Yr")
#         ax2.plot(treasury_yield_spread_adj.index, np.array(treasury_yield_spread_adj), "-",
#                  color="cyan", linewidth=1, label="1Yr/15Yr_MBAdj")
#         ax2.plot([treasury_yield_spread.index[0], treasury_yield_spread.index[-1]], [1, 1], "-",
#                  color="red")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="lower center")
#         plt.grid(true)
#         plt.title("Stock Market and Interest Rate Structure as of " * todaystr)
    
#         #...........................
    
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         # ax.plot(SP500.index, SP500["Close"], "-", color="blue", label="S&P500")
#         ax.plot(vix.index, vix["VIX Close"], "-", color="blue", label="VIX")
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(ted_spread.index, ted_spread.iloc[:, 0], "-",
#                  color="magenta", linewidth=1, label="TED Spread")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         ax2.set_ylabel("%")
#         # ax.set_yscale("log")
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
#         plt.grid(true)
#         plt.title("Financial Stress Indicators (1) as of " * todaystr)
    
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(SP500.index, SP500["Close"], "-", color="blue", label="S&P500")
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(stl_fsi.index, np.array(stl_fsi), "-",
#                  color="red", linewidth=1, label="St. Louis Fed FSI")
#         ax2.plot(kc_fsi.index, np.array(kc_fsi), "-",
#                  color="green", linewidth=1, label="Kansas City FSI")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
#         plt.grid(true)
#         plt.title("Financial Stress Indicators (2) as of " * todaystr)
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ted_spread["vix"] = vix["VIX Close"]
#         ted_spread = ted_spread.dropna()
#         ax.plot(ted_spread["vix"], ted_spread.iloc[:, 0], "b.")
#         ax.set_xlabel("VIX")
#         ax.set_ylabel("TED Spread")
#         corr = np.corrcoef(np.array(ted_spread["vix"]), np.array(ted_spread.iloc[:, 0]))[0, 1]
#         plt.grid(true)
#         plt.title("VIX ~ TED Spread, corr = {0:.2f}%".format(corr*100))
    
#         #...........................
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(SP500.index, SP500["Close"], "-", color="blue", label="S&P500")
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(c_fsi.index, np.array(c_fsi), "-",
#                  color="red", linewidth=1, label="Cleveland FSI")
#         ax2.plot(n_fci.index, np.array(n_fci), "-",
#                  color="green", linewidth=1, label="Chicago Fed National FCI")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
#         plt.grid(true)
#         plt.title("Financial Stress Indicators (3) as of " * todaystr)
    
#         nfig += 1
#         plt.savefig("./MarketBigPictureWatch/BigPicture{:d}.png".format(nfig))
#         #-----------------------------------------------------------------------
    
#         plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    
#         nrows = 2
#         ncols = 2
#         nplot = 0
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(population.index, population.iloc[:, 0]/1e6, "--",
#                 color="blue", linewidth=1, label="Population")
#         ax.plot(wa_population.index, np.array(wa_population)/1e9, "--",
#                 color="magenta", linewidth=1, label="Working Age (15-64) Population")
#         ax.set_ylabel("Bln")
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         ax2 = ax.twinx()
#         ax2.plot(gdp_per_capita.index, np.array(gdp_per_capita), "-",
#                  color="red", linewidth=1, label="GDP Per Capita")
#         ax2.plot(realgdp_per_capita.index, np.array(realgdp_per_capita), "-",
#                  color="green", linewidth=1, label="Real GDP Per Capita (2009$)")
#         ax2.set_ylabel("K$")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="lower right")
#         plt.grid(true)
#         plt.title("Population as of " * todaystr)
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         ax.plot(epr.index, epr.iloc[:, 0], "-",
#                 color="green", linewidth=1, label="Employment-Population Ratio")
#         ax.plot(lfpr.index, np.array(lfpr), "-",
#                 color="blue", linewidth=1, label="Labor Force Participation Rate")
#         ax.set_xlim([date_plotstart, date_plotend])
#         ax.set_ylabel("%")
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="lower left")
#         ax2 = ax.twinx()
#         ax2.plot(uer.index, uer.iloc[:, 0], "-",
#                  color="red", linewidth=1, label="Unemployment Rate")
#         ax2.set_xlim([date_plotstart, date_plotend])
#         ax2.set_ylabel("%")
#         # ax.set_yscale("log")
#         ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
#         plt.grid(true)
#         plt.title("Labor Market Condition as of " * todaystr)
    
#         nplot += 1
#         ax = subplot(nrows, ncols, nplot)
#         for (n, city) in enumerate(cities_of_interest)
#             ax.plot(caseshiller[city].index, np.array(caseshiller[city].ix[:, 1]), "-", color=colors[n],
#                     linewidth =  city in ["National", "Chicago", "SanFrancisco"] ? 3 : 1, label=city)
#         end
#         ax.set_xlim([date_plotstart, date_plotend])
#         # ax.set_yscale("log")
#         ax.yaxis.set_major_formatter(fmt)
#         ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
#         plt.grid(true)
#         plt.title("S&P/Case-Shiller Home Price Indices as of " * todaystr)
    
#         nfig += 1
#         plt.savefig("./MarketBigPictureWatch/BigPicture{:d}.png".format(nfig))
#         #----------------------------------------------------------------------
    
#         plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    
#         nrows = 4
#         ncols = 5
#         nplot = 0
    
#         for comdty in futures_underlying
#             nplot += 1
#             ax = subplot(nrows, ncols, nplot)
#             ax.plot(futures_prices[comdty].index, np.array(futures_prices[comdty]), "-",
#                     color="blue", linewidth=1, label=comdty)
#             ax.set_xlim([date_future_plotstart_long, date_plotend])
#             ax.yaxis.set_major_formatter(fmt)
#             ax.legend(prop=Dict("size" => legend_fontsize), loc=0)
#             plt.grid(true)
#             if nplot == Int(round(ncols/2+0.01, digits=0))
#                 ax.set_title("Futures - Long Term ({:d} year{:s}) as of {:s}".format(future_yrs_long, future_yrs_long > 1 ? "s" : "", today))
#             end    
#             plt.tick_params(axis="both", which="major", labelsize=8)
#             plt.tick_params(axis="both", which="minor", labelsize=8)
#         end
    
#         nfig += 1
#         plt.savefig("./MarketBigPictureWatch/BigPicture{:d}.png".format(nfig))
#         #--------------------------------------------------------------------------
#         plt.figure(facecolor="w", figsize=figsize, dpi=dpi)
    
#         nrows = 4
#         ncols = 5
#         nplot = 0
    
#         for comdty in futures_underlying
#             nplot += 1
#             ax = subplot(nrows, ncols, nplot)
#             ind = ((futures_prices[comdty].index >= date_future_plotstart_short) & (futures_prices[comdty].index <=
#                                                                                     date_plotend))
#             ax.plot(futures_prices[comdty].index[ind], np.array(futures_prices[comdty])[ind], "-",
#                     color="red", linewidth=1, label=comdty)
#             ax.set_xlim([date_future_plotstart_short, date_plotend])
#             ax.yaxis.set_major_formatter(fmt)
#             ax.legend(prop=Dict("size" => legend_fontsize), loc=0)
#             plt.grid(true)
#             if nplot == int(np.round(ncols/2+0.01))
#                 ax.set_title("Futures - Short Term ({:d} year{:s}) as of {:s}".format(future_yrs_short, future_yrs_short > 1 ? "s" : "", today))
#             end
#             plt.tick_params(axis="both", which="major", labelsize=7)
#             plt.tick_params(axis="both", which="minor", labelsize=7)
#         end

#         nfig += 1
#         plt.savefig("./MarketBigPictureWatch/BigPicture{:d}.png".format(nfig))
#         #------------------------------------------------------------------------
    
#         print("Plots opening in new windows.")
    
#         plt.show()

end

println("\n************** Main script started...")
main()
println("\n************** Main script finished.")


