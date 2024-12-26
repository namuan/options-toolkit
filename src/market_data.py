import pandas as pd
import yfinance as yf
from persistent_cache import PersistentCache


@PersistentCache()
def download_ticker_data(ticker, start, end):
    try:
        ticker_df = yf.download(ticker, start=start, end=end)
        ticker_df.columns = ticker_df.columns.droplevel("Ticker")
        return ticker_df
    except:
        print(f"Unable to fetch data for ticker: {ticker}")
        return pd.DataFrame()
