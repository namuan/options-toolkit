import pandas as pd
import yfinance as yf
from persistent_cache import PersistentCache


@PersistentCache()
def download_ticker_data(ticker, start, end):
    try:
        return yf.download(ticker, start=start, end=end, multi_level_index=False)
    except:
        print(f"Unable to fetch data for ticker: {ticker}")
        return pd.DataFrame()
