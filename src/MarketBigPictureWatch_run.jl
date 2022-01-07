println("Loading packages...")
using PyPlot
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
    data = filter(x->!isnan(x.value), data)
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
    data = filter(x->!isnan(x.value), data)
    sort!(data, [:date])
    return data
end

function calc_two_dataframes(data1::DataFrame, operator::String, data2::DataFrame)::DataFrame
    data = innerjoin(data1, data2, on=:date, makeunique=true)
    data = data[completecases(data), :]
    if operator == "/"
        data[!, :value] = data[!, :value] ./ data[!, :value_1]
    elseif operator == "*"
        data[!, :value] = data[!, :value] .* data[!, :value_1]
    elseif operator == "+"
        data[!, :value] = data[!, :value] .+ data[!, :value_1]
    elseif operator == "-"
        data[!, :value] = data[!, :value] .- data[!, :value_1]
    else
        error("Unknown dataframe operator $operator")
    end
    data = data[!, ["date", "value"]]

    return data
end


isdownloaded = false
quandl = Quandl(ENV["QUANDL_API_KEY"])

date_plotstart = date_plotend - Day(Int(round(macro_yrs_ultralong*365.25, digits=0)))
date_future_plotstart_long = date_plotend -  Day(Int(round(future_yrs_long*365.25, digits=0)))
date_future_plotstart_short = date_plotend - Day(Int(round(future_yrs_short*365.25, digits=0)))

cities_of_interest = ["National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego", "Portland", "Seattle", "Phoenix", "Dallas"]
colors = ["black", "green", "blue", "cyan", "magenta", "red", "yellow", "darkblue", "pink", "purple", "orange",
            "brown"]

close("all")

if !isdownloaded
    println("Downloading data from Fred, Yahoo, and Quandl...\n")

    # Permalink of any Quandl data set: https://www.quandl.com/data/xxx/yyy
    # where xxx/yyy is the Quandl Code

    # S&P500 index
    println("************** S&P500 (Fred) **************")
    SP500 = get_daily_data_from_yahoo("^GSPC", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
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

    # Money Supply - Monetary Base, millions of dollars
    println("\n************** Monetary Base (Fred) **************")
    MB = get_daily_data_from_fred("BOGMBASEW", date_plotstart, date_plotend, isverbose, nrows_verbose)
    MB[!, :value] /= 1000  # convert millions of dollars to billions of dollars
    
    # Money Supply - M2, billions of dollars
    println("\n************** M2 (Fred) **************")
    M2 = get_daily_data_from_fred("M2", date_plotstart, date_plotend, isverbose, nrows_verbose)
    
    # S&P500 / M2
    SP500_M2 = calc_two_dataframes(SP500, "/", M2)
    
    # US Treasury Zero-Coupon Yield Curve
    println("\n************** US Treasury Zero-Coupon Yield Curve (Quandl) **************")
    treasury_yield1, treasury_yield2, treasury_yield5, treasury_yield10, treasury_yield15, treasury_yield20 = 
        get_daily_data_from_quandl(quandl, "FED/SVENY", date_plotstart, date_plotend, ["Date", "SVENY01", "SVENY02", "SVENY05", "SVENY10", "SVENY15", "SVENY20"], isverbose, nrows_verbose)
    # short term interest rate (1 Yr) / long term interest rate (15 Yr)
    treasury_yield_spread = calc_two_dataframes(treasury_yield1, "/", treasury_yield15)
    
    # US GDP, billions of dollars
    println("\n************** GDP (Fred) **************")
    GDP = get_daily_data_from_fred("GDP", date_plotstart, date_plotend, isverbose, nrows_verbose)
    # Real GDP, Billions of Chained 2012 Dollars,
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
    population = get_daily_data_from_fred("POP", date_plotstart, date_plotend, isverbose, nrows_verbose)  # unit: thousands of persons
    # Working age population (age 15-64)
    println("\n************** Working age population (age 15-64) (Fred) **************")
    wa_population = get_daily_data_from_fred("LFWA64TTUSM647N", date_plotstart, date_plotend, isverbose, nrows_verbose)  # unit: persons
    wa_population[!, :value] /= 1000  # convert unit to thousands of persons
    # population values below are all in thousands of persons
    println("\n************** White population (Fred) **************")
    ratio_white = calc_two_dataframes(get_daily_data_from_fred("LNU00000003", date_plotstart, date_plotend, isverbose, nrows_verbose), "/", population)
    println("\n************** Black population (Fred) **************")
    ratio_black = calc_two_dataframes(get_daily_data_from_fred("LNU00000006", date_plotstart, date_plotend, isverbose, nrows_verbose), "/", population)
    println("\n************** Hispanic population (Fred) **************")
    ratio_hispanic = calc_two_dataframes(get_daily_data_from_fred("LNU00000009", date_plotstart, date_plotend, isverbose, nrows_verbose), "/", population)
    println("\n************** Asian population (Fred) **************")
    ratio_asian = calc_two_dataframes(get_daily_data_from_fred("LNU00032183", date_plotstart, date_plotend, isverbose, nrows_verbose), "/", population)
    gdp_per_capita = calc_two_dataframes(GDP, "/", population)  # billions of dollars per thousands of persons
    gdp_per_capita[!, :value] *= (1e6 / 1e3)   # thousand $ per person
    realgdp_per_capita = calc_two_dataframes(RealGDP, "/", population)
    realgdp_per_capita[!, :value] *= (1e6 / 1e3)   # thousand $ per person

    # Labor Market
    # Civilian Employment-Population ratio
    println("\n************** Civilian Employment-Population ratio (Fred) **************")
    epr = get_daily_data_from_fred("EMRATIO", date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    # Civilian Unemployment Rate
    println("\n************** Civilian Unemployment Rate (Fred) **************")
    uer = get_daily_data_from_fred("UNRATE", date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    # Civilian Labor Force Participation Rate
    println("\n************** Civilian Labor Force Participation Rate (Fred) **************")
    lfpr = get_daily_data_from_fred("CIVPART", date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    
    
    # S&P/Case-Shiller Housing Indexes
    CaseShillerIndexID = Dict("City20"=>"SPCS20RSA", "Chicago"=>"CHXRSA", "SanFrancisco"=>"SFXRSA", "LosAngeles"=>"LXXRSA",
    "SanDiego"=>"SDXRSA", "NewYork"=>"NYXRSA", "Portland"=>"POXRSA", "Seattle"=>"SEXRSA",
    "Atlanta"=>"ATXRSA", "Boston"=>"BOXRSA", "Charlotte"=>"CRXRSA", "Cleveland"=>"CEXRSA",
    "Dallas"=>"DAXRSA", "Denver"=>"DNXRSA", "Detroit"=>"DEXRSA", "LasVegas"=>"LVXRSA", "Miami"=>"MIXRSA",
    "Minneapolis"=>"MNXRSA", "Phoenix"=>"PHXRSA", "Tampa"=>"TPXRSA", "WashingtonDC"=>"WDXRSA",
    "City10"=>"SPCS10RSA", "National"=>"CSUSHPISA")
    caseshiller = Dict()
    for city in cities_of_interest
        println("\n************** Case Shiller Index: " * city * " (Fred) **************")
        caseshiller[city] = get_daily_data_from_fred(CaseShillerIndexID[city], date_plotstart, date_plotend, isverbose, nrows_verbose)  # thousands
    end
    
    # Commodity and Energy Prices represented in Continuous Front-Month Future Contracts
    futures_underlying = ["USDIndex", "EURIndex", "JPYIndex", "5YrYield", "10YrYield", "Gold", "Silver", "Copper",
                            "CrudeOil", "BrentCrudeOil", "Gasoline", "NaturalGas", "Wheat", "Corn", "LiveCattle",
                            "Cotton", "Sugar", "Coffee", "Cocoa", "OrangeJuice"]

    futures_symbols = ["DX=F", "6E=F", "6J=F", "^FVX", "^TNX", "GC=F", "SI=F", "HG=F",
                        "CL=F", "BZ=F", "RB=F", "NG=F", "ZW=F", "ZC=F", "LE=F",
                        "CT=F", "SB=F", "KC=F", "CC=F", "OJ=F"]

    futures_contracts = Dict(zip(futures_underlying, futures_symbols))
    futures_prices = Dict()
    for comdty in futures_underlying
        println("\n************** Futures: " * comdty * " (Yahoo) **************")
        futures_prices[comdty] = get_daily_data_from_yahoo(futures_contracts[comdty], date_plotstart, date_plotend, isverbose, nrows_verbose)
    end
    
    println("\nAll downloads finished!")
    isdownloaded = true
end

if isdownloaded
    println("\nPlotting...")
    nfig = 0
    #########################################################################
    # Plots

    fig = figure(facecolor="w", figsize=figsize, dpi=dpi)
    
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
    grid(true, linestyle=":")
    PyPlot.title("Stock and Gold as of " * todaystr)

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500_gold[!, :date], SP500_gold[!, :value], "b-")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    grid(true, linestyle=":")
    PyPlot.title("S&P500 / Gold as of " * todaystr)

    #...........................

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    baseline_yearsago = 10
    baseline_year = year(Dates.today()) - baseline_yearsago
    baseline_date = Date(baseline_year, month(Dates.today()), day(Dates.today()))
    baseline_cpi = filter(x->x.date >= baseline_date, cpi)[1, :value]
    ax.plot(cpi[!, :date], cpi[!, :value] / baseline_cpi * 100, ":", color="blue", linewidth=4, label="CPI")
    baseline_cpi_food = filter(x->x.date >= baseline_date, cpi_food)[1, :value]
    ax.plot(cpi_food[!, :date], cpi_food[!, :value] / baseline_cpi_food * 100, "-", color="green", label="CPI:Food")
    baseline_cpi_housing = filter(x->x.date >= baseline_date, cpi_housing)[1, :value]
    ax.plot(cpi_housing[!, :date], cpi_housing[!, :value] / baseline_cpi_housing * 100, "-", color="aqua", label="CPI:Housing")
    baseline_cpi_medical = filter(x->x.date >= baseline_date, cpi_medical)[1, :value]
    ax.plot(cpi_medical[!, :date], cpi_medical[!, :value] / baseline_cpi_medical * 100, "-", color="magenta", label="CPI:Medical")
    baseline_cpi_education = filter(x->x.date >= baseline_date, cpi_education)[1, :value]
    ax.plot(cpi_education[!, :date], cpi_education[!, :value] / baseline_cpi_education * 100, "-", color="gold", label="CPI:Education")
    baseline_gdpdef = filter(x->x.date >= baseline_date, gdpdef)[1, :value]
    ax.plot(gdpdef[!, :date], gdpdef[!, :value] / baseline_gdpdef * 100, ":", color="red", linewidth=4, label="GDP Deflator")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.set_ylabel("Index")
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    grid(true, linestyle=":")
    plt.title("Inflation Index ($baseline_yearsago years ago = 100) as of " * todaystr)
    
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
    grid(true, linestyle=":")
    plt.title("S&P500 vs. GDP and M2 as of " * todaystr)

    #...........................
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(MB[!, :date], MB[!, :value], "b-", label="MB")
    ax.plot(M2[!, :date], M2[!, :value], "r-", label="M2")
    ax.plot(GDP[!, :date], GDP[!, :value], "-", label="GDP")
    ax.plot(RealGDP[!, :date], RealGDP[!, :value], "-", color="darkgreen", label="Real GDP (2009 USD)")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.set_ylabel("USD Bln")
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(MB_GDP[!, :date], MB_GDP[!, :value], "m--", label="MB/GDP")
    ax2.plot(M2_GDP[!, :date], M2_GDP[!, :value], "c--", label="M2/GDP")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
    grid(true, linestyle=":")
    plt.title("Money Supply and GDP as of " * todaystr)
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(ShillerPE10[!, :date], ShillerPE10[!, :value], "b-", label="Shiller P/E 10")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(TobinQ[!, :date], TobinQ[!, :value], "r-", label="Tobin's Q")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
    grid(true, linestyle=":")
    plt.title("Stock Market Valuation - Ratios as of " * todaystr)
    
    tight_layout()

    nfig += 1
    savefig(joinpath(@__DIR__, "pictures", "BigPicture$nfig.png"))

    #-------------------------------------------------------------------------

    figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows = 3
    ncols = 2
    nplot = 0
    
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(treasury_yield20[!, :date], treasury_yield20[!, :value], "-",  color="blue", linewidth=0.5, label="20 Yr")
    ax.plot(treasury_yield10[!, :date], treasury_yield10[!, :value], "-",  color="green", linewidth=0.5, label="10 Yr")
    ax.plot(treasury_yield5[!, :date], treasury_yield5[!, :value], "-",  color="yellow", linewidth=0.5, label="5 Yr")
    ax.plot(treasury_yield2[!, :date], treasury_yield2[!, :value], "-", color="orange", linewidth=0.5, label="2 Yr")
    ax.plot(treasury_yield1[!, :date], treasury_yield1[!, :value], "-", color="red", linewidth=0.5, label="1 Yr")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.set_ylabel("%")
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    grid(true, linestyle=":")
    plt.title("Treasury Zero-Coupon Yield as of " * todaystr)
    
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500[!, :date], SP500[!, :value], "-", color="blue", label="S&P500")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(treasury_yield_spread[!, :date], treasury_yield_spread[!, :value], "-",
                color="magenta", linewidth=1, label="1Yr/15Yr")
    ax2.plot(treasury_yield_spread_adj[!, :date], treasury_yield_spread_adj[!, :value], "-",
                color="cyan", linewidth=1, label="1Yr/15Yr_MBAdj")
    ax2.plot([treasury_yield_spread[!, :date][1], treasury_yield_spread[!, :date][end]], [1, 1], "-",
                color="red")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
    grid(true, linestyle=":")
    plt.title("Stock Market and Interest Rate Structure as of " * todaystr)

    #...........................

    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    # ax.plot(SP500[!, :date], SP500[!, :value], "-", color="blue", label="S&P500")
    ax.plot(vix[!, :date], vix[!, :value], "-", color="blue", label="VIX")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(ted_spread[!, :date], ted_spread[!, :value], "-",
                color="magenta", linewidth=1, label="TED Spread")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.set_ylabel("%")
    # ax.set_yscale("log")
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper right")
    grid(true, linestyle=":")
    plt.title("Financial Stress Indicators (1) as of " * todaystr)
    
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500[!, :date], SP500[!, :value], "-", color="blue", label="S&P500")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(stl_fsi[!, :date], stl_fsi[!, :value], "-",
                color="red", linewidth=1, label="St. Louis Fed FSI")
    ax2.plot(kc_fsi[!, :date], kc_fsi[!, :value], "-",
                color="green", linewidth=1, label="Kansas City FSI")
    ax2.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
    grid(true, linestyle=":")
    plt.title("Financial Stress Indicators (2) as of " * todaystr)
    
    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    tedspreadvix = innerjoin(ted_spread, vix, on=:date, makeunique=true)
    ax.plot(tedspreadvix[!, :value_1], tedspreadvix[!, :value], "b.")
    ax.set_xlabel("VIX")
    ax.set_ylabel("TED Spread")
    corr = cor(tedspreadvix[!, :value_1], tedspreadvix[!, :value])
    grid(true, linestyle=":")
    plt.title("VIX ~ TED Spread, corr = $(round(corr*100, digits=2))%")
    
    #...........................

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(SP500[!, :date], SP500[!, :value], "-", color="blue", label="S&P500")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(c_fsi[!, :date], c_fsi[!, :value], "-",
                color="red", linewidth=1, label="Cleveland FSI")
    ax2.plot(n_fci[!, :date], n_fci[!, :value], "-",
                color="green", linewidth=1, label="Chicago Fed National FCI")
    ax2.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
    grid(true, linestyle=":")
    plt.title("Financial Stress Indicators (3) as of " * todaystr)

    tight_layout()

    nfig += 1
    savefig(joinpath(@__DIR__, "pictures", "BigPicture$nfig.png"))
    #-----------------------------------------------------------------------

    figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows = 2
    ncols = 2
    nplot = 0

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(population[!, :date], population[!, :value]/1e6, "--",
            color="blue", linewidth=1, label="Population")
    ax.plot(wa_population[!, :date], wa_population[!, :value]/1e6, "--",
            color="magenta", linewidth=1, label="Working Age (15-64) Population")
    ax.set_ylabel("Bln Persons")
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(gdp_per_capita[!, :date], gdp_per_capita[!, :value], "-",
                color="red", linewidth=1, label="GDP Per Capita")
    ax2.plot(realgdp_per_capita[!, :date], realgdp_per_capita[!, :value], "-",
                color="green", linewidth=1, label="Real GDP Per Capita (2009 USD)")
    ax2.set_ylabel("K USD")
    ax2.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="lower right")
    grid(true, linestyle=":")
    plt.title("Population as of " * todaystr)

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    ax.plot(epr[!, :date], epr[!, :value], "-",
            color="green", linewidth=1, label="Employment-Population Ratio")
    ax.plot(lfpr[!, :date], lfpr[!, :value], "-",
            color="blue", linewidth=1, label="Labor Force Participation Rate")
    ax.set_xlim([date_plotstart, date_plotend])
    ax.set_ylabel("%")
    # ax.set_yscale("log")
    # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="lower left")
    ax2 = ax.twinx()
    ax2.plot(uer[!, :date], uer[!, :value], "-",
                color="red", linewidth=1, label="Unemployment Rate")
    ax2.set_xlim([date_plotstart, date_plotend])
    ax2.set_ylabel("%")
    # ax.set_yscale("log")
    ax2.legend(prop=Dict("size" => legend_fontsize), loc="upper center")
    grid(true, linestyle=":")
    plt.title("Labor Market Condition as of " * todaystr)

    nplot += 1
    ax = subplot(nrows, ncols, nplot)
    for (n, city) in enumerate(cities_of_interest)
        ax.plot(caseshiller[city][!, :date], caseshiller[city][!, :value], "-", color=colors[n],
                linewidth =  city in ["National", "Chicago", "SanFrancisco"] ? 3 : 1, label=city)
    end
    ax.set_xlim([date_plotstart, date_plotend])
    # ax.set_yscale("log")
    # ax.yaxis.set_major_formatter(fmt)
    ax.legend(prop=Dict("size" => legend_fontsize), loc="upper left")
    grid(true, linestyle=":")
    plt.title("S&P/Case-Shiller Home Price Indices as of " * todaystr)

    tight_layout()

    nfig += 1
    savefig(joinpath(@__DIR__, "pictures", "BigPicture$nfig.png"))
    #----------------------------------------------------------------------

    figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows = 4
    ncols = 5
    nplot = 0

    for comdty in futures_underlying
        global nplot
        local ax
        nplot += 1
        ax = subplot(nrows, ncols, nplot)
        ax.plot(futures_prices[comdty][!, :date], futures_prices[comdty][!, :value], "-",
                color="blue", linewidth=1, label=comdty)
        ax.set_xlim([date_future_plotstart_long, date_plotend])
        # ax.yaxis.set_major_formatter(fmt)
        ax.legend(prop=Dict("size" => legend_fontsize), loc=0)
        grid(true, linestyle=":")
        if nplot == Int(round(ncols/2+0.01, digits=0))
            ax.set_title("Futures - Long Term ($future_yrs_long-year) as of $todaystr")
        end    
        tick_params(axis="both", which="major", labelsize=8)
        tick_params(axis="both", which="minor", labelsize=8)
    end

    tight_layout()

    nfig += 1
    savefig(joinpath(@__DIR__, "pictures", "BigPicture$nfig.png"))
    #--------------------------------------------------------------------------
    figure(facecolor="w", figsize=figsize, dpi=dpi)

    nrows = 4
    ncols = 5
    nplot = 0

    for comdty in futures_underlying
        global nplot
        local ax
        nplot += 1
        ax = subplot(nrows, ncols, nplot)
        ind = (date_future_plotstart_short .<= futures_prices[comdty][!, :date] .<= date_plotend)
        ax.plot(futures_prices[comdty][ind, :date], futures_prices[comdty][ind, :value], "-",
                color="red", linewidth=1, label=comdty)
        ax.set_xlim([date_future_plotstart_short, date_plotend])
        # ax.yaxis.set_major_formatter(fmt)
        ax.legend(prop=Dict("size" => legend_fontsize), loc=0)
        grid(true, linestyle=":")
        if nplot == Int(round(ncols/2+0.01, digits=0))
            ax.set_title("Futures - Short Term ($future_yrs_short-year) as of $todaystr")
        end
        tick_params(axis="both", which="major", labelsize=7)
        tick_params(axis="both", which="minor", labelsize=7)
    end

    tight_layout()

    nfig += 1
    savefig(joinpath(@__DIR__, "pictures", "BigPicture$nfig.png"))
    #------------------------------------------------------------------------

    println("Plots opened in new windows.\nThe script finished.")
else
    println("Downloading failed!\nThe script aborted.")
end



