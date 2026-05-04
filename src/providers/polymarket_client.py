import json
import logging
from datetime import datetime
from typing import Any

import httpx

from src.core.models import MarketSignal

logger = logging.getLogger(__name__)

GAMMA_BASE_URL    = "https://gamma-api.polymarket.com"
EVENTS_ENDPOINT   = f"{GAMMA_BASE_URL}/events"
VOLUME_THRESHOLD  = 1_000
REQUEST_TIMEOUT   = 20

TARGET_SLUGS: dict[str, str] = {
    "business": "Business",
    "crypto":   "Crypto",
    "tech":     "Tech",
}


class PolymarketClient:

    def fetch_polymarket_data(self) -> list[dict[str, Any]]:
        seen_ids: set[str] = set()
        results:  list[dict[str, Any]] = []

        with httpx.Client() as client:
            for slug, label in TARGET_SLUGS.items():
                logger.info("Fetching category: %s (tag_slug=%s)", label, slug)
                events = self._fetch_events_by_slug(client, slug)
                logger.info("  → %d events returned", len(events))

                for event in events:
                    event_id = event.get("id")
                    if event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)

                    parsed = self._parse_event(event, label)
                    if parsed:
                        results.append(parsed)

        results.sort(key=lambda x: x["volume"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_events_by_slug(
        self, client: httpx.Client, tag_slug: str
    ) -> list[dict[str, Any]]:
        params = {
            "limit":     50,
            "active":    "true",
            "closed":    "false",
            "order":     "volume24hr",
            "ascending": "false",
            "tag_slug":  tag_slug,
        }
        try:
            response = client.get(EVENTS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching slug '%s': %s", tag_slug, e)
            return []
        except httpx.RequestError as e:
            logger.error("Request error fetching slug '%s': %s", tag_slug, e)
            return []

    @staticmethod
    def _extract_yes_price(market: dict[str, Any]) -> float | None:
        raw = market.get("outcomePrices")
        if not raw:
            return None
        try:
            prices = json.loads(raw) if isinstance(raw, str) else raw
            outcomes_raw = market.get("outcomes", "[]")
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            try:
                yes_index = [o.strip().lower() for o in outcomes].index("yes")
            except ValueError:
                yes_index = 0
            return float(prices[yes_index])
        except (json.JSONDecodeError, IndexError, ValueError, TypeError):
            return None

    def _parse_event(
        self, event: dict[str, Any], category_label: str
    ) -> dict[str, Any] | None:
        markets: list[dict[str, Any]] = event.get("markets", [])
        if not markets:
            return None

        active_markets = [m for m in markets if m.get("active") and not m.get("closed")]
        if not active_markets:
            active_markets = markets

        primary_market = active_markets[0]
        yes_price = self._extract_yes_price(primary_market)
        volume = float(event.get("volume") or primary_market.get("volume") or 0)

        if volume < VOLUME_THRESHOLD or yes_price is None:
            return None

        end_date_raw = event.get("endDate") or event.get("end_date")
        end_date: str | None = None
        if end_date_raw:
            try:
                end_date = datetime.fromisoformat(
                    end_date_raw.replace("Z", "+00:00")
                ).isoformat()
            except (ValueError, AttributeError):
                end_date = None

        question = event.get("title") or primary_market.get("question") or "N/A"

        raw_signal = {
            "id":           event.get("id"),
            "slug":         event.get("slug"),
            "question":     question,
            "category":     category_label,
            "end_date":     end_date,
            "probability":  yes_price,
            "volume":       volume,
            "market_count": len(markets),
        }

        try:
            validated = MarketSignal(**raw_signal)
            return validated.model_dump()
        except Exception as e:
            logger.warning("Skipping event %s — validation failed: %s", event.get("id"), e)
            return None

    @staticmethod
    def print_summary(signals: list[dict[str, Any]]) -> None:
        if not signals:
            print("\nNo signals found above volume threshold.\n")
            return

        col_q, col_c, col_p, col_v = 60, 10, 13, 15
        header  = (
            f"{'Question':<{col_q}} {'Category':<{col_c}} "
            f"{'Probability':>{col_p}} {'Volume ($)':>{col_v}}"
        )
        divider = "-" * len(header)

        print(f"\n{'POLYMARKET SIGNAL SCANNER — Active Events':^{len(header)}}")
        print(divider)
        print(header)
        print(divider)

        for s in signals:
            q = s["question"]
            if len(q) > col_q:
                q = q[:col_q - 3] + "..."
            print(
                f"{q:<{col_q}} {s['category']:<{col_c}} "
                f"{s['probability']:>{col_p}.1%} {s['volume']:>{col_v},.0f}"
            )

        print(divider)
        print(f"Total signals: {len(signals)}\n")
