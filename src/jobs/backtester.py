from collections import defaultdict
from datetime import date

import pandas as pd
from tabulate import tabulate

from src.core.models import BacktestSummary
from src.providers.yfinance_client import YFinanceClient
from src.utils.database import DatabaseService
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_VERDICT_ICON = {"HIT": "✅", "MISS": "❌", "N/A": "—"}


class Backtester:
    """
    Intraday performance check for Polymarket equity signals.
    Fetches 5-min yfinance bars, determines HIT/MISS per signal,
    and persists aggregate metrics to the backtest_history table.
    """

    def __init__(self) -> None:
        self.db        = DatabaseService()
        self.yf_client = YFinanceClient()

    def run(self, limit: int | None = None) -> None:
        # 1. Load signals
        print("Loading signals from Supabase…", flush=True)
        signals = self.db.load_signals_for_backtest(limit)
        if not signals:
            print("No signals found — run a harvest first.")
            return
        label = f"{len(signals)} of {limit} requested" if limit else str(len(signals))
        print(f"  {label} signals loaded.", flush=True)

        # 2. Group by ticker
        by_ticker: dict[str, list[dict]] = defaultdict(list)
        for s in signals:
            by_ticker[s["ticker"]].append(s)

        unique = sorted(by_ticker)
        print(f"  {len(unique)} unique tickers: {', '.join(unique)}\n", flush=True)

        # 3. Fetch intraday bars
        print("Fetching 5-min bars (5-day window) from yfinance…", flush=True)
        cache: dict[str, pd.DataFrame] = {}
        for ticker in unique:
            df = self.yf_client.fetch_intraday(ticker)
            cache[ticker] = df
            if not df.empty:
                print(
                    f"  {ticker:<6}  {len(df):>4} bars  "
                    f"{df.index[0].strftime('%Y-%m-%d %H:%M')} → "
                    f"{df.index[-1].strftime('%Y-%m-%d %H:%M')} UTC",
                    flush=True,
                )
            else:
                print(f"  {ticker:<6}  ⚠ no data returned", flush=True)

        # 4. Build per-signal result rows
        rows: list[dict] = []
        for ticker in sorted(by_ticker):
            df      = cache[ticker]
            current = float(df["Close"].iloc[-1]) if not df.empty else None

            for s in by_ticker[ticker]:
                ts     = pd.to_datetime(s["created_at"], utc=True)
                entry  = self.yf_client.closest_close(df, ts)
                impact = s["impact_type"]
                score  = int(s["relevance_score"])

                if entry is not None and current is not None:
                    pct  = (current - entry) / entry * 100
                    verd = self._calc_verdict(impact, entry, current)
                else:
                    pct  = None
                    verd = "N/A"

                rows.append(dict(
                    ticker=ticker, impact=impact, score=score,
                    entry=entry, current=current, pct=pct, verdict=verd,
                ))

        rows.sort(key=lambda r: (-r["score"], r["ticker"]))

        # 5. Detect pre-market
        judged     = [r for r in rows if r["verdict"] != "N/A"]
        _today     = date.today()
        _last_dates = [df.index[-1].date() for df in cache.values() if not df.empty]
        pre_market = bool(_last_dates) and all(d < _today for d in _last_dates)

        # 6. Print detail table
        self._print_detail(rows, pre_market, _last_dates)

        # 7. Per-ticker summary
        self._print_ticker_summary(rows, by_ticker)

        # 8. Compute per-ticker + aggregate summaries
        summaries = self._compute_aggregate(rows, judged, by_ticker, pre_market, _last_dates, cache)

        # 9. Persist all rows to Supabase in one bulk insert
        self.db.save_backtest_results(summaries)
        ticker_count = len(summaries) - 1  # subtract the aggregate row
        print(f"  💾 Saved → backtest_history ({ticker_count} ticker rows + 1 aggregate)")

        if pre_market:
            print("\n  ℹ  Re-run after 9:30 AM ET for live intraday price movement.\n")

    # ------------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_verdict(impact: str, entry: float, current: float) -> str:
        if impact == "Bullish":
            return "HIT" if current > entry else "MISS"
        if impact == "Bearish":
            return "HIT" if current < entry else "MISS"
        return "N/A"

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pct(n: int, d: int) -> str:
        return f"{n / d * 100:.1f}%  ({n}/{d})" if d else "—"

    def _print_detail(
        self,
        rows: list[dict],
        pre_market: bool,
        last_dates: list[date],
    ) -> None:
        print("\n" + "═" * 78)
        print("  POLYMARKET SIGNAL BACKTEST — INTRADAY PERFORMANCE")
        if pre_market:
            last_bar = max(last_dates).isoformat() if last_dates else "unknown"
            print(f"  ⚠  Pre-market: most recent bar is {last_bar} (yesterday's close).")
            print("     Signals created today map to yesterday's close — % Δ will be 0 for most rows.")
        print("═" * 78)

        detail_rows = [
            [
                r["ticker"],
                r["impact"],
                r["score"],
                f"${r['entry']:.2f}"   if r["entry"]   is not None else "—",
                f"${r['current']:.2f}" if r["current"] is not None else "—",
                f"{r['pct']:+.2f}%"    if r["pct"]     is not None else "—",
                _VERDICT_ICON[r["verdict"]] + " " + r["verdict"],
            ]
            for r in rows
        ]
        print(tabulate(
            detail_rows,
            headers=["Ticker", "Signal", "Score", "Entry", "Current", "% Δ", "Verdict"],
            tablefmt="rounded_outline",
        ))

    def _print_ticker_summary(
        self,
        rows: list[dict],
        by_ticker: dict[str, list[dict]],
    ) -> None:
        print("\n" + "─" * 54)
        print("  PER-TICKER SUMMARY")
        print("─" * 54)

        summary = []
        for ticker in sorted(by_ticker):
            t_rows   = [r for r in rows if r["ticker"] == ticker]
            t_judged = [r for r in t_rows if r["verdict"] != "N/A"]
            t_hits   = [r for r in t_judged if r["verdict"] == "HIT"]
            avg_sc   = sum(r["score"] for r in t_rows) / len(t_rows)
            win_rate = f"{len(t_hits)/len(t_judged)*100:.0f}%" if t_judged else "—"
            summary.append([ticker, len(t_rows), f"{avg_sc:.1f}", win_rate])

        print(tabulate(summary, headers=["Ticker", "Signals", "Avg Score", "Win Rate"], tablefmt="simple"))

    def _build_ticker_summary(
        self,
        ticker: str,
        t_rows: list[dict],
        generated_at: str,
        pre_market: bool,
        last_bar_date: str | None,
    ) -> BacktestSummary:
        t_judged  = [r for r in t_rows if r["verdict"] != "N/A"]
        t_hits    = [r for r in t_judged if r["verdict"] == "HIT"]
        t_bull    = [r for r in t_judged if r["impact"] == "Bullish"]
        t_bear    = [r for r in t_judged if r["impact"] == "Bearish"]
        t_bull_h  = [r for r in t_bull   if r["verdict"] == "HIT"]
        t_bear_h  = [r for r in t_bear   if r["verdict"] == "HIT"]
        t_hc      = [r for r in t_judged if r["score"] >= 8]
        t_hc_hits = [r for r in t_hc     if r["verdict"] == "HIT"]
        t_neutral = len(t_rows) - len(t_judged)
        t_avg     = sum(r["score"] for r in t_rows) / len(t_rows) if t_rows else 0.0
        return BacktestSummary(
            ticker=ticker,
            generated_at=generated_at,
            pre_market=pre_market,
            last_bar_date=last_bar_date,
            total_signals=len(t_rows),
            judged=len(t_judged),
            neutral=t_neutral,
            avg_score=round(t_avg, 2),
            overall_win_rate_pct=round(len(t_hits) / len(t_judged) * 100, 1) if t_judged else None,
            bullish_win_rate_pct=round(len(t_bull_h) / len(t_bull) * 100, 1) if t_bull else None,
            bearish_win_rate_pct=round(len(t_bear_h) / len(t_bear) * 100, 1) if t_bear else None,
            hc_win_rate_pct=round(len(t_hc_hits) / len(t_hc) * 100, 1) if t_hc else None,
            hc_count=len(t_hc),
            hc_hits=len(t_hc_hits),
            top3_by_pct=[],
        )

    def _compute_aggregate(
        self,
        rows: list[dict],
        judged: list[dict],
        by_ticker: dict[str, list[dict]],
        pre_market: bool,
        last_dates: list[date],
        cache: dict[str, pd.DataFrame],
    ) -> list[BacktestSummary]:
        hits     = [r for r in judged if r["verdict"] == "HIT"]
        bull_j   = [r for r in judged if r["impact"] == "Bullish"]
        bear_j   = [r for r in judged if r["impact"] == "Bearish"]
        bull_hit = [r for r in bull_j  if r["verdict"] == "HIT"]
        bear_hit = [r for r in bear_j  if r["verdict"] == "HIT"]
        hc       = [r for r in judged  if r["score"] >= 8]
        hc_hits  = [r for r in hc      if r["verdict"] == "HIT"]
        neutral  = len(rows) - len(judged)
        avg_score = sum(r["score"] for r in rows) / len(rows) if rows else 0

        print("\n" + "─" * 44)
        print("  AGGREGATE SUMMARY")
        print("─" * 44)
        print(f"  Total signals:              {len(rows)}")
        print(f"  Neutral (excluded):         {neutral}")
        print(f"  Judged (Bull + Bear):       {len(judged)}")
        print(f"  Avg confidence score:       {avg_score:.2f} / 10")
        print()
        print(f"  Overall win rate:           {self._pct(len(hits), len(judged))}")
        print(f"    └─ Bullish hit rate:      {self._pct(len(bull_hit), len(bull_j))}")
        print(f"    └─ Bearish hit rate:      {self._pct(len(bear_hit), len(bear_j))}")
        print()
        print(f"  High Conviction (≥8):       {self._pct(len(hc_hits), len(hc))}")
        print("─" * 44)

        generated_at  = pd.Timestamp.now("UTC").isoformat()
        last_bar_date = max(last_dates).isoformat() if last_dates else None

        # Per-ticker summaries
        ticker_summaries = [
            self._build_ticker_summary(
                ticker, [r for r in rows if r["ticker"] == ticker],
                generated_at, pre_market, last_bar_date,
            )
            for ticker in sorted(by_ticker)
        ]

        # Top-3 tickers by absolute % change (global aggregate only)
        ticker_pct: dict[str, float] = {}
        for ticker in by_ticker:
            tr = [r for r in rows if r["ticker"] == ticker and r["pct"] is not None]
            if tr:
                best = max(tr, key=lambda r: abs(r["pct"]))
                ticker_pct[ticker] = best["pct"]
        top3 = sorted(ticker_pct.items(), key=lambda x: abs(x[1]), reverse=True)[:3]

        global_summary = BacktestSummary(
            ticker=None,
            generated_at=generated_at,
            pre_market=pre_market,
            last_bar_date=last_bar_date,
            total_signals=len(rows),
            judged=len(judged),
            neutral=neutral,
            avg_score=round(avg_score, 2),
            overall_win_rate_pct=round(len(hits) / len(judged) * 100, 1) if judged else None,
            bullish_win_rate_pct=round(len(bull_hit) / len(bull_j) * 100, 1) if bull_j else None,
            bearish_win_rate_pct=round(len(bear_hit) / len(bear_j) * 100, 1) if bear_j else None,
            hc_win_rate_pct=round(len(hc_hits) / len(hc) * 100, 1) if hc else None,
            hc_count=len(hc),
            hc_hits=len(hc_hits),
            top3_by_pct=[{"ticker": t, "pct": round(p, 4)} for t, p in top3],
        )

        return ticker_summaries + [global_summary]
