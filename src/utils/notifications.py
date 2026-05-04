import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import requests

from src.core.config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 8
REQUEST_TIMEOUT = 15

_IMPACT_COLORS = {
    "Bullish": 0x16a34a,
    "Bearish": 0xdc2626,
    "Neutral": 0x6b7280,
}
_IMPACT_EMOJI = {
    "Bullish": "📈",
    "Bearish": "📉",
    "Neutral": "➡️",
}
_PLACEHOLDER = "your-discord-webhook-url"


class NotificationService:

    # ------------------------------------------------------------------
    # Signal alerts (called after every high-score save in Harvester)
    # ------------------------------------------------------------------

    def maybe_send_alert(self, signal: dict[str, Any], question: str) -> None:
        score = int(signal.get("relevance_score") or 0)
        if score >= ALERT_THRESHOLD:
            logger.info(
                "Score %d >= %d threshold — triggering Discord alert for %s.",
                score, ALERT_THRESHOLD, signal.get("ticker"),
            )
            self._send_signal_alert(signal, question)

    def _send_signal_alert(self, signal: dict[str, Any], question: str) -> bool:
        if not DISCORD_WEBHOOK_URL:
            print("[!] Notification skipped: DISCORD_WEBHOOK_URL not configured in .env")
            return False

        embed = self._build_signal_embed(signal, question)
        payload = {"embeds": [embed]}

        try:
            response = httpx.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            logger.info(
                "Discord alert sent for %s signal on %s (score=%d).",
                signal.get("impact_type"), signal["ticker"], signal["relevance_score"],
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "Discord webhook HTTP error for %s: %s — %s",
                signal["ticker"], e, e.response.text,
            )
            return False
        except httpx.RequestError as e:
            logger.error("Discord webhook request error for %s: %s", signal["ticker"], e)
            return False

    def _build_signal_embed(self, signal: dict[str, Any], question: str) -> dict[str, Any]:
        ticker    = signal["ticker"]
        score     = int(signal["relevance_score"])
        impact    = signal.get("impact_type") or "Neutral"
        rationale = signal.get("rationale") or "N/A"
        if len(rationale) > 1000:
            rationale = rationale[:1000] + "… [Truncated]"
        citations: list[dict[str, str]] = signal.get("citations") or []

        polymarket_url = next(
            (c["uri"] for c in citations if "polymarket.com" in c.get("uri", "")), None
        )
        source_links = " | ".join(
            f"[{c.get('title') or c['uri']}]({c['uri']})"
            for c in citations
            if "polymarket.com" not in c.get("uri", "")
        )

        emoji = _IMPACT_EMOJI.get(impact, "➡️")
        color = _IMPACT_COLORS.get(impact, 0x6b7280)

        fields: list[dict[str, Any]] = [
            {"name": "📝 Market Question",  "value": question[:1024],    "inline": False},
            {"name": "📋 Rationale",        "value": rationale[:1024],   "inline": False},
            {"name": "📊 Relevance Score",  "value": f"**{score} / 10**","inline": True},
            {"name": f"{emoji} Impact",     "value": f"**{impact}**",    "inline": True},
        ]
        if source_links:
            fields.append({"name": "🔗 Sources", "value": source_links[:1024], "inline": False})

        return {
            "title":     f"🔔  ${ticker} — {impact} Signal",
            "url":       polymarket_url or "",
            "color":     color,
            "fields":    fields,
            "footer":    {"text": "Polymarket Signal Scanner  •  BIT Capital Research"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Backtest results (called from Backtester after run completes)
    # ------------------------------------------------------------------

    def send_backtest_result(self, results: dict[str, Any]) -> None:
        if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == _PLACEHOLDER:
            print("[!] Notification skipped: DISCORD_WEBHOOK_URL not configured in .env")
            return

        payload = self._build_backtest_payload(results)
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 204:
            logger.info("Backtest results posted to Discord.")
        else:
            logger.error("Discord returned HTTP %d: %s", resp.status_code, resp.text[:200])

    @staticmethod
    def _pct_line(rate: float | None, hits: int | None = None, total: int | None = None) -> str:
        if rate is None:
            return "—"
        s = f"{rate:.1f}%"
        if hits is not None and total is not None:
            s += f"  ({hits}/{total})"
        return s

    def _build_backtest_payload(self, r: dict[str, Any]) -> dict[str, Any]:
        overall  = r.get("overall_win_rate_pct")
        bullish  = r.get("bullish_win_rate_pct")
        bearish  = r.get("bearish_win_rate_pct")
        hc_rate  = r.get("hc_win_rate_pct")
        hc_count = r.get("hc_count", 0)
        hc_hits  = r.get("hc_hits", 0)
        judged   = r.get("judged", 0)
        neutral  = r.get("neutral", 0)
        total    = r.get("total_signals", 0)
        pre_mkt  = r.get("pre_market", False)
        ts       = r.get("generated_at", "")

        overall_hits = round(overall / 100 * judged) if (overall and judged) else 0

        top3 = r.get("top3_by_pct", [])
        top3_lines = []
        for i, entry in enumerate(top3, 1):
            pct   = entry["pct"]
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
            top3_lines.append(f"{i}. **{entry['ticker']}** {arrow} {pct:+.2f}%")
        top3_str = "\n".join(top3_lines) if top3_lines else "—"

        if pre_mkt:
            color = 0xF59E0B
        elif overall is not None and overall >= 50:
            color = 0x22C55E
        else:
            color = 0xEF4444

        description = ""
        if pre_mkt:
            last_bar = r.get("last_bar_date", "unknown")
            description = (
                f"⚠️ **Pre-market data** — most recent bar: `{last_bar}`.\n"
                "Results will be stale until the market opens.\n\n"
            )

        fields: list[dict[str, Any]] = [
            {
                "name":   "📊 Signals",
                "value":  f"`{total}` total · `{judged}` judged · `{neutral}` neutral",
                "inline": False,
            },
            {"name": "🎯 Overall Win Rate", "value": self._pct_line(overall, overall_hits, judged), "inline": True},
            {"name": "📈 Bullish",          "value": self._pct_line(bullish),                        "inline": True},
            {"name": "📉 Bearish",          "value": self._pct_line(bearish),                        "inline": True},
            {
                "name":   f"💎 High Conviction (≥8) — {hc_hits}/{hc_count}",
                "value":  self._pct_line(hc_rate, hc_hits, hc_count),
                "inline": False,
            },
            {"name": "🏆 Top 3 by % Change", "value": top3_str, "inline": False},
        ]

        return {
            "embeds": [{
                "title":       "🔔 Market Open Backtest Results",
                "description": description,
                "color":       color,
                "fields":      fields,
                "footer":      {"text": "Polymarket Signal Scanner"},
                "timestamp":   ts if ts else None,
            }]
        }
