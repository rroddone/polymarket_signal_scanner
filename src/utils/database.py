import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client, create_client

from src.core.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from src.core.models import BacktestSummary

logger = logging.getLogger(__name__)

CLEANUP_DAYS = 30

DEFAULT_WATCHLIST: list[dict[str, str]] = [
    {"ticker": "NVDA",  "sector": "AI/Semiconductors"},
    {"ticker": "AMD",   "sector": "AI/Semiconductors"},
    {"ticker": "INTC",  "sector": "AI/Semiconductors"},
    {"ticker": "AAPL",  "sector": "AI/Technology"},
    {"ticker": "MSFT",  "sector": "AI/Technology"},
    {"ticker": "GOOGL", "sector": "AI/Technology"},
    {"ticker": "META",  "sector": "AI/Technology"},
    {"ticker": "AMZN",  "sector": "AI/Technology"},
    {"ticker": "TSLA",  "sector": "AI/EV/Technology"},
    {"ticker": "PLTR",  "sector": "AI/Software"},
    {"ticker": "ORCL",  "sector": "AI/Cloud"},
    {"ticker": "IBM",   "sector": "AI/Enterprise"},
    {"ticker": "COIN",  "sector": "Crypto/Exchange"},
    {"ticker": "MSTR",  "sector": "Crypto/Bitcoin"},
    {"ticker": "MARA",  "sector": "Crypto/Mining"},
    {"ticker": "RIOT",  "sector": "Crypto/Mining"},
    {"ticker": "CLSK",  "sector": "Crypto/Mining"},
    {"ticker": "HUT",   "sector": "Crypto/Mining"},
    {"ticker": "BTBT",  "sector": "Crypto/Mining"},
    {"ticker": "BMNR",  "sector": "Crypto/Mining"},
    {"ticker": "SQ",    "sector": "Crypto/Fintech"},
    {"ticker": "PYPL",  "sector": "Crypto/Fintech"},
    {"ticker": "SPCE",  "sector": "Space/Technology"},
]


class DatabaseService:
    def __init__(self) -> None:
        self._client: Client = create_client(
            SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def upsert_markets(self, signals: list[dict[str, Any]]) -> None:
        rows = [
            {
                "id": s["id"],
                "slug": s["slug"],
                "question": s["question"],
                "end_date": s["end_date"],
                "category": s["category"],
                "active": True,
            }
            for s in signals
            if s["id"]
        ]
        if not rows:
            return
        try:
            self._client.table("markets").upsert(rows, on_conflict="id").execute()
            logger.info("Upserted %d rows into markets.", len(rows))
        except Exception as e:
            logger.error("Failed to upsert markets: %s", e)
            raise

    def insert_prices(self, signals: list[dict[str, Any]]) -> None:
        rows = [
            {
                "market_id": s["id"],
                "price": round(s["probability"], 2),
                "volume_24h": s["volume"],
            }
            for s in signals
            if s["id"]
        ]
        if not rows:
            return
        try:
            self._client.table("market_prices").insert(rows).execute()
            logger.info("Inserted %d rows into market_prices.", len(rows))
        except Exception as e:
            logger.error("Failed to insert market_prices: %s", e)
            raise

    def cleanup_old_prices(self) -> None:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=CLEANUP_DAYS)
        ).isoformat()
        try:
            self._client.table("market_prices").delete().lt("timestamp", cutoff).execute()
            logger.info("Cleaned up market_prices older than %d days.", CLEANUP_DAYS)
        except Exception as e:
            logger.error("Cleanup failed: %s", e)
            raise

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def seed_watchlist(self) -> None:
        result = self._client.table("watchlists").select("ticker").limit(1).execute()
        if result.data:
            logger.info("Watchlist already seeded. Skipping.")
            return
        self._client.table("watchlists").insert(DEFAULT_WATCHLIST).execute()
        logger.info("Seeded watchlist with %d tickers.", len(DEFAULT_WATCHLIST))

    def fetch_watchlist(self) -> list[str]:
        result = self._client.table("watchlists").select("ticker").execute()
        return [row["ticker"] for row in result.data]

    def fetch_unanalyzed_markets(self) -> list[dict[str, Any]]:
        analyzed = self._client.table("equity_signals").select("market_id").execute()
        analyzed_ids: list[str] = [row["market_id"] for row in analyzed.data]

        query = (
            self._client.table("markets")
            .select("id, slug, question, category")
            .eq("active", True)
        )
        if analyzed_ids:
            query = query.not_.in_("id", analyzed_ids)
        return query.execute().data

    def save_signal(
        self,
        market_id: str,
        ticker: str,
        relevance_score: int,
        impact_type: str,
        rationale: str,
        citations: list[dict[str, str]],
        provider: str,
    ) -> None:
        self._client.table("equity_signals").insert({
            "market_id":       market_id,
            "ticker":          ticker,
            "relevance_score": relevance_score,
            "impact_type":     impact_type,
            "rationale":       rationale,
            "citations":       citations,
            "provider":        provider,
        }).execute()

    # ------------------------------------------------------------------
    # Backtest
    # ------------------------------------------------------------------

    def load_signals_for_backtest(self, limit: int | None = None) -> list[dict[str, Any]]:
        q = (
            self._client.table("equity_signals")
            .select("id, ticker, impact_type, relevance_score, created_at")
            .order("created_at", desc=False)
        )
        if limit:
            q = q.limit(limit)
        return q.execute().data

    def save_backtest_results(self, summaries: list[BacktestSummary]) -> None:
        rows = [s.model_dump() for s in summaries]
        try:
            self._client.table("backtest_history").insert(rows).execute()
            logger.info(
                "Saved %d backtest rows (%d ticker + 1 aggregate).",
                len(rows), len(rows) - 1,
            )
        except Exception as e:
            logger.error("Failed to save backtest results: %s", e)
            raise
