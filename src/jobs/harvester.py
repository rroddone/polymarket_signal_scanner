import atexit
import logging
import os
import sys
import time
from typing import Any

from src.core.config import LOG_FILE, PRIMARY_LLM, PROJECT_ROOT
from src.providers.llm_factory import (
    LLMFactory,
    RATE_LIMIT_DELAY_GEMINI,
    RATE_LIMIT_DELAY_GROQ,
    MIN_RELEVANCE_SCORE,
)
from src.providers.polymarket_client import PolymarketClient
from src.utils.database import DatabaseService
from src.utils.logger import GracefulExit, flush_logs, setup_logger
from src.utils.notifications import NotificationService

_PIDFILE = "/tmp/polymarket_analyze.pid"
CIRCUIT_BREAKER_THRESHOLD = 5

logger = setup_logger(__name__)


class Harvester:
    """
    Orchestrates a full harvest cycle: ingest Polymarket data, then run LLM
    analysis on all unanalyzed markets.  Writes results directly to Supabase.
    """

    def __init__(self) -> None:
        self.db            = DatabaseService()
        self.poly_client   = PolymarketClient()
        self.llm           = LLMFactory()
        self.notifications = NotificationService()

    def run(self, limit: int | None = None) -> None:
        self._check_already_running()
        atexit.register(self._remove_pidfile)
        self._ingest()
        self._analyze(limit=limit)

    # ------------------------------------------------------------------
    # Phase 1: Ingest
    # ------------------------------------------------------------------

    def _ingest(self) -> None:
        logger.info("=== Polymarket Signal Scanner — Ingestion Start ===")
        signals = self.poly_client.fetch_polymarket_data()
        self.poly_client.print_summary(signals)

        logger.info("Connecting to Supabase…")
        self.db.cleanup_old_prices()
        self.db.upsert_markets(signals)
        self.db.insert_prices(signals)
        logger.info("=== Ingestion Complete ===")

    # ------------------------------------------------------------------
    # Phase 2: Analysis
    # ------------------------------------------------------------------

    def _analyze(self, limit: int | None = None) -> None:
        mode_label = f"DRY RUN (limit={limit})" if limit else "FULL RUN"
        logger.info(
            "=== Polymarket Signal Analyzer — %s | Primary: %s ===",
            mode_label, PRIMARY_LLM,
        )

        self.db.seed_watchlist()
        tickers = self.db.fetch_watchlist()
        logger.info("Watchlist: %d tickers loaded.", len(tickers))

        recent_context = self.llm.format_recent_context(self.db.fetch_recent_signals())
        if recent_context:
            logger.info("Prompt context: %s", recent_context)

        markets = self.db.fetch_unanalyzed_markets()
        if limit:
            markets = markets[:limit]
        logger.info(
            "Pre-filter complete: %d new markets to analyze "
            "(already-analyzed markets skipped instantly, no sleep).",
            len(markets),
        )

        if not markets:
            logger.info("Nothing to analyze. Exiting.")
            return

        rate_limit_delay   = self.llm.rate_limit_delay
        active_provider    = self.llm.active_provider_label
        saved              = 0
        skipped            = 0
        consecutive_errors = 0

        for i, market in enumerate(markets):
            market_id: str   = market["id"]
            question:  str   = market["question"]
            category:  str   = market.get("category", "Unknown")
            slug: str | None = market.get("slug")

            print(f"DEBUG: Starting analysis for market {i+1}/{len(markets)}: {slug}", flush=True)
            logger.info(
                "[%d/%d] Analyzing (%s) via %s: %s",
                i + 1, len(markets), category, active_provider.upper(), question[:80],
            )

            try:
                result, citations, provider_label, triggered_failover = self.llm.analyze_market(
                    question=question,
                    tickers=tickers,
                    slug=slug,
                    recent_context=recent_context,
                )
            except GracefulExit as ge:
                logger.info("=== Graceful Stop: %s ===", ge)
                logger.info(
                    "=== Analysis Complete: %d saved, %d skipped "
                    "(session stopped early — will resume on next cycle) ===",
                    saved, skipped,
                )
                flush_logs()
                sys.exit(0)

            if triggered_failover:
                self.llm.use_groq  = False
                active_provider    = "gemini"
                rate_limit_delay   = RATE_LIMIT_DELAY_GEMINI
                logger.info(
                    "Adaptive throttling: provider switched to Gemini, delay → %ds.",
                    rate_limit_delay,
                )

            if result is None:
                consecutive_errors += 1
                logger.warning(
                    "  → No parseable result. Consecutive errors: %d/%d",
                    consecutive_errors, CIRCUIT_BREAKER_THRESHOLD,
                )
                if consecutive_errors >= CIRCUIT_BREAKER_THRESHOLD:
                    logger.error(
                        "Circuit breaker tripped: %d consecutive failures. Aborting.",
                        consecutive_errors,
                    )
                    flush_logs()
                    sys.exit(1)
                skipped += 1
            elif not result:
                consecutive_errors = 0
                skipped += 1
            else:
                consecutive_errors = 0
                validated = self.llm.validate_result(result)
                if validated is None:
                    skipped += 1
                else:
                    ticker          = validated["ticker"]
                    relevance_score = validated["relevance_score"]
                    impact_type     = validated["impact_type"]
                    rationale       = validated["rationale"]

                    if relevance_score < MIN_RELEVANCE_SCORE:
                        logger.info(
                            "  → No relevant ticker identified (score=%d). Skipping.",
                            relevance_score,
                        )
                        skipped += 1
                    else:
                        self.db.save_signal(
                            market_id=market_id,
                            ticker=ticker,
                            relevance_score=relevance_score,
                            impact_type=impact_type,
                            rationale=rationale,
                            citations=citations,
                            provider=provider_label,
                        )
                        logger.info(
                            "  → Saved: %s | %s | score=%d | provider=%s | citations=%d",
                            ticker, impact_type, relevance_score, provider_label, len(citations),
                        )
                        saved += 1

                        self.notifications.maybe_send_alert(
                            signal={
                                "ticker":          ticker,
                                "relevance_score": relevance_score,
                                "impact_type":     impact_type,
                                "rationale":       rationale,
                                "citations":       citations,
                            },
                            question=question,
                        )

            if i < len(markets) - 1:
                time.sleep(rate_limit_delay)

        logger.info("=== Analysis Complete: %d saved, %d skipped ===", saved, skipped)
        flush_logs()

    # ------------------------------------------------------------------
    # PID guard
    # ------------------------------------------------------------------

    @staticmethod
    def _check_already_running() -> None:
        if os.path.exists(_PIDFILE):
            try:
                pid = int(open(_PIDFILE).read().strip())
                os.kill(pid, 0)
                print(f"ERROR: Analysis already in progress (pid {pid}). Exiting.", flush=True)
                sys.exit(1)
            except (ProcessLookupError, ValueError):
                pass  # stale pidfile
        with open(_PIDFILE, "w") as f:
            f.write(str(os.getpid()))

    @staticmethod
    def _remove_pidfile() -> None:
        try:
            os.unlink(_PIDFILE)
        except FileNotFoundError:
            pass
