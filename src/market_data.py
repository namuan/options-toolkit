import pandas as pd
import yfinance as yf
from persistent_cache import PersistentCache
from stockstats import wrap


@PersistentCache()
def download_ticker_data(ticker, start, end):
    try:
        return yf.download(ticker, start=start, end=end, multi_level_index=False)
    except:
        print(f"Unable to fetch data for ticker: {ticker}")
        return pd.DataFrame()


def load_market_data(quote_dates, symbols):
    market_data = {
        symbol: wrap(
            download_ticker_data(symbol, start=quote_dates[0], end=quote_dates[-1])
        )
        for symbol in symbols
    }
    return market_data
