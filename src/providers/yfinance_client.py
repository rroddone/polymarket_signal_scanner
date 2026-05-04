import logging
from datetime import timezone

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceClient:

    def fetch_intraday(self, ticker: str) -> pd.DataFrame:
        """
        Return a UTC-indexed DataFrame of 5-min Close bars for the past 5 trading days.
        Returns an empty DataFrame on any failure.
        """
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="5m")
            if df.empty:
                return df
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            return df[["Close"]]
        except Exception as e:
            logger.error("yfinance error for %s: %s", ticker, e)
            return pd.DataFrame()

    @staticmethod
    def closest_close(df: pd.DataFrame, ts: pd.Timestamp) -> float | None:
        if df.empty:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        idx = df.index.get_indexer([ts], method="nearest")[0]
        return float(df["Close"].iloc[idx]) if idx >= 0 else None
