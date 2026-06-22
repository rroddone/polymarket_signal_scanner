import json
import logging
import random
import re
import time
from typing import Any

import groq as groq_lib
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from src.core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    POLYMARKET_BASE,
    PRIMARY_LLM,
)
from pydantic import ValidationError

from src.core.models import LLMAnalysisResult
from src.utils.logger import GracefulExit

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY_GROQ   = 2.5  # 24 effective RPM — do not reduce
RATE_LIMIT_DELAY_GEMINI = 5    # 12 effective RPM
GROQ_FAILOVER_COOLDOWN  = 10
MAX_RETRIES             = 4
BACKOFF_BASE            = 20
MIN_RELEVANCE_SCORE     = 1
MAX_429_RETRIES         = 3


class LLMFactory:

    def __init__(self) -> None:
        self.gemini: genai.Client = genai.Client(api_key=GEMINI_API_KEY)
        self.groq: groq_lib.Groq | None = (
            groq_lib.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        )
        self.use_groq: bool = PRIMARY_LLM == "GROQ" and self.groq is not None
        if PRIMARY_LLM == "GROQ" and self.groq is None:
            logger.warning("PRIMARY_LLM=GROQ but GROQ_API_KEY is not set. Falling back to Gemini.")

    @property
    def rate_limit_delay(self) -> float:
        return RATE_LIMIT_DELAY_GROQ if self.use_groq else RATE_LIMIT_DELAY_GEMINI

    @property
    def active_provider_label(self) -> str:
        return "groq" if self.use_groq else "gemini"

    # ------------------------------------------------------------------
    # Public dispatch
    # ------------------------------------------------------------------

    def analyze_market(
        self,
        question: str,
        tickers: list[str],
        slug: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]], str, bool]:
        """
        Route to Groq (primary) or Gemini (failover) with header-aware 429 retry.
        Returns (result, citations, provider_label, triggered_failover).
        """
        if self.use_groq and self.groq is not None:
            return self._groq_primary(question, tickers, slug)
        return self._gemini_primary(question, tickers, slug)

    # ------------------------------------------------------------------
    # Prompt + parsing
    # ------------------------------------------------------------------

    @staticmethod
    def build_prompt(question: str, tickers: list[str]) -> str:
        watchlist_str = ", ".join(tickers)
        return (
            "You are a quantitative equity analyst at a tier-1 macro hedge fund. Evaluate whether "
            "a prediction market outcome has a DIRECT, MATERIAL transmission mechanism to a specific "
            "publicly-traded US equity from the watchlist.\n\n"

            "CHAIN OF THOUGHT MANDATE — before selecting any ticker you must first answer this "
            "internally: 'Is there a direct, highly-documented supply chain, balance sheet, or "
            "macroeconomic transmission mechanism connecting this event to a specific public US "
            "equity? If the answer is tenuous or relies on generalized sentiment, you must reject it.'\n\n"

            "REJECTION CRITERIA — set impact_type 'None', final_ticker null, relevance_score 0 if:\n"
            "- Connection relies on vague sentiment or 'investor confidence' with no P&L line\n"
            "- Event is a product announcement, date, or news item with no quantifiable impact\n"
            "- Multiple tickers apply equally (diversified macro with no single primary vehicle)\n"
            "- No specific revenue, cost, or balance-sheet line is affected\n\n"

            "SCORING RUBRIC:\n"
            "9-10 = Core business / direct balance-sheet hit\n"
            "7-8  = Strong, documented sector transmission mechanism\n"
            "5-6  = Material but one step removed\n"
            "1-4  = Tenuous, atmospheric, or speculative\n"
            "0    = No transmission mechanism — null ticker, impact_type 'None'\n\n"

            "--- FEW-SHOT EXAMPLES ---\n\n"

            "EXAMPLE 1 (Direct Macro Hit):\n"
            'Market: "Will the Federal Reserve cut rates by 50bps or more at the September 2025 FOMC meeting?"\n'
            "Tickers: SPY, JPM, BAC, XLF, TLT\n"
            "Output: "
            '{"fundamental_reasoning":"A 50bps rate cut directly expands equity multiples via a lower '
            "DCF discount rate and compresses net interest margins for banks. SPY is the broadest and "
            "most liquid transmission vehicle — the S&P 500 has a well-documented inverse relationship "
            "with the Fed Funds rate through the equity risk premium. This is a primary macroeconomic "
            'event with a concrete, immediate balance-sheet transmission to US equities.",'
            '"impact_type":"Bullish","final_ticker":"SPY","relevance_score":9}\n\n'

            "EXAMPLE 2 (Supply Chain Hit):\n"
            'Market: "Will TSMC halt all Taiwan fab production for more than 72 hours due to conflict or disaster?"\n'
            "Tickers: NVDA, AMD, AAPL, QCOM, INTC\n"
            "Output: "
            '{"fundamental_reasoning":"TSMC manufactures ~90% of advanced semiconductors below 7nm. '
            "NVDA sources 100% of its GPU wafers from TSMC — the H100/H200/B200 data-center line "
            "drives ~80% of NVDA revenue. A 72-hour halt creates an immediate wafer shortage and "
            "revenue-miss risk documented in NVDA's 10-K under single-source supplier risk. "
            'Transmission: TSMC halt → wafer gap → NVDA revenue miss. Direct supply-chain hit.",'
            '"impact_type":"Bearish","final_ticker":"NVDA","relevance_score":8}\n\n'

            "EXAMPLE 3 (Hard Rejection):\n"
            'Market: "Will OpenAI announce a release date for SearchGPT before December 31?"\n'
            "Tickers: GOOGL, MSFT, META, AAPL\n"
            "Output: "
            '{"fundamental_reasoning":"While OpenAI competes in search advertising with GOOGL, an '
            "announcement of a release DATE is a sentiment event, not a balance-sheet event. GOOGL "
            "search revenue will not change on announcement day — impact depends on future user "
            "adoption and advertiser behavior, neither quantifiable from this single event. "
            'No direct supply-chain, revenue, or cost transmission exists at announcement time. Rejected as noise.",'
            '"impact_type":"None","final_ticker":null,"relevance_score":0}\n\n'

            "--- NOW ANALYZE ---\n"
            f'Market: "{question}"\n'
            f"Tickers: {watchlist_str}\n\n"

            "Reply with ONLY valid JSON — no markdown, no prose, no extra keys:\n"
            '{"fundamental_reasoning":"<chain-of-thought>","impact_type":"Bullish|Bearish|Neutral|None",'
            '"final_ticker":"TICKER or null","relevance_score":0}'
        )

    @staticmethod
    def parse_llm_response(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            for m in re.finditer(r"\{[^{}]+\}", cleaned):
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    continue
            return None

    def validate_result(self, raw: dict[str, Any] | None) -> dict[str, Any] | None:
        """Run Pydantic validation on the raw LLM dict; returns None on failure."""
        if not raw:
            return None
        try:
            validated = LLMAnalysisResult(**raw)
            return validated.model_dump()
        except ValidationError as e:
            logger.warning("LLM schema validation failed: %s — raw: %s", e, raw)
            return None
        except Exception as e:
            logger.warning("LLM result parsing error: %s — raw: %s", e, raw)
            return None

    # ------------------------------------------------------------------
    # Groq-primary path
    # ------------------------------------------------------------------

    def _groq_primary(
        self,
        question: str,
        tickers: list[str],
        slug: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]], str, bool]:
        assert self.groq is not None
        for attempt_429 in range(MAX_429_RETRIES + 1):
            try:
                result, citations = self._call_groq(question, tickers, slug)
                return result, citations, GROQ_MODEL, False
            except groq_lib.RateLimitError as rate_err:
                if attempt_429 < MAX_429_RETRIES:
                    wait = self._groq_429_wait(rate_err, attempt_429)
                    logger.warning(
                        "Groq 429 (attempt %d/%d) — Waiting %ds.",
                        attempt_429 + 1, MAX_429_RETRIES, wait,
                    )
                    time.sleep(wait)
                else:
                    raise GracefulExit(
                        "Groq rate limit reached after max retries. Will resume on next cycle."
                    )
            except groq_lib.APIConnectionError:
                raise GracefulExit("Groq connection error. Sleeping until next cron cycle.")
        raise GracefulExit("Groq rate limit reached after max retries.")

    # ------------------------------------------------------------------
    # Gemini-primary path (with Groq failover)
    # ------------------------------------------------------------------

    def _gemini_primary(
        self,
        question: str,
        tickers: list[str],
        slug: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]], str, bool]:
        for attempt_429 in range(MAX_429_RETRIES + 1):
            try:
                result, citations = self._call_gemini(question, tickers, slug)
                return result, citations, GEMINI_MODEL, False
            except genai_errors.ClientError as rate_err:
                if rate_err.code != 429:
                    raise
                if attempt_429 < MAX_429_RETRIES:
                    wait = self._gemini_429_wait(rate_err, attempt_429)
                    logger.warning(
                        "Gemini 429 (attempt %d/%d) — Waiting %ds.",
                        attempt_429 + 1, MAX_429_RETRIES, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("Gemini 429 after %d retries — failing over to Groq.", MAX_429_RETRIES)
                    break

        if self.groq is None:
            raise GracefulExit("Gemini rate-limited and GROQ_API_KEY is not set.")

        logger.info("  Switching to Groq failover for this market.")
        for attempt_429 in range(MAX_429_RETRIES + 1):
            try:
                result, citations = self._call_groq(question, tickers, slug)
                return result, citations, GROQ_MODEL, True
            except groq_lib.RateLimitError as rate_err:
                if attempt_429 < MAX_429_RETRIES:
                    wait = self._groq_429_wait(rate_err, attempt_429)
                    logger.warning("Groq failover 429 (attempt %d/%d) — Waiting %ds.", attempt_429 + 1, MAX_429_RETRIES, wait)
                    time.sleep(wait)
                else:
                    raise GracefulExit("Both Gemini and Groq rate-limited after max retries.")
            except groq_lib.APIConnectionError:
                raise GracefulExit("Groq connection error during failover.")
        raise GracefulExit("Both providers exhausted.")

    # ------------------------------------------------------------------
    # Low-level API callers
    # ------------------------------------------------------------------

    def _call_groq(
        self,
        question: str,
        tickers: list[str],
        slug: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        prompt    = self.build_prompt(question, tickers)
        citations: list[dict[str, str]] = []
        if slug:
            citations.append({"title": "Polymarket Event", "uri": f"{POLYMARKET_BASE}/{slug}"})

        for attempt in range(MAX_RETRIES):
            try:
                completion = self.groq.chat.completions.create(  # type: ignore[union-attr]
                    messages=[{"role": "user", "content": prompt}],
                    model=GROQ_MODEL,
                    temperature=0.1,
                    max_tokens=500,
                )
                text   = completion.choices[0].message.content or ""
                parsed = self.parse_llm_response(text)
                if parsed is None:
                    print(f"[PARSE ERROR] Groq returned unparseable response:\n{text[:600]}", flush=True)
                return parsed, citations
            except (groq_lib.RateLimitError, groq_lib.APIConnectionError):
                raise
            except groq_lib.APIError as e:
                wait = min(BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5), 60)
                logger.warning("Groq API error (attempt %d/%d): %s. Retrying in %.0fs.", attempt + 1, MAX_RETRIES, e, wait)
                time.sleep(wait)
            except Exception as e:
                logger.error("Unexpected Groq error for '%s': %s", question[:60], e)
                return None, citations

        logger.error("Max retries exceeded (Groq) for: %s", question[:60])
        return None, citations

    def _call_gemini(
        self,
        question: str,
        tickers: list[str],
        slug: str | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        prompt = self.build_prompt(question, tickers)

        for attempt in range(MAX_RETRIES):
            try:
                response = self.gemini.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(tools=[], temperature=0.1, max_output_tokens=600),
                )
                text      = self._extract_text(response)
                citations = self._extract_citations(response)
                if slug:
                    pm_url = f"{POLYMARKET_BASE}/{slug}"
                    if not any(c["uri"] == pm_url for c in citations):
                        citations.append({"title": "Polymarket Event", "uri": pm_url})
                if not text:
                    logger.warning("  → Empty Gemini response (finish_reason=%s). Skipping.", self._finish_reason(response))
                    return {}, citations
                parsed = self.parse_llm_response(text)
                if parsed is None:
                    print(f"[PARSE ERROR] Gemini returned unparseable response:\n{text[:600]}", flush=True)
                return parsed, citations
            except genai_errors.ClientError as e:
                if e.code == 429:
                    raise
                logger.error("Gemini API error for '%s': %s", question[:60], e)
                return None, []
            except Exception as e:
                logger.error("Unexpected Gemini error for '%s': %s", question[:60], e)
                return None, []

        logger.error("Max retries exceeded (Gemini) for: %s", question[:60])
        return None, []

    # ------------------------------------------------------------------
    # Gemini response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            t = response.text
            if t:
                return t
        except Exception:
            pass
        try:
            for candidate in (response.candidates or []):
                parts = getattr(candidate.content, "parts", []) or []
                for part in parts:
                    t = getattr(part, "text", None)
                    if t:
                        return t
        except (AttributeError, TypeError):
            pass
        return ""

    @staticmethod
    def _finish_reason(response: Any) -> str:
        try:
            reason = response.candidates[0].finish_reason
            return reason.name if hasattr(reason, "name") else str(reason)
        except (AttributeError, IndexError, TypeError):
            return "UNKNOWN"

    @staticmethod
    def _extract_citations(response: Any) -> list[dict[str, str]]:
        citations: list[dict[str, str]] = []
        try:
            candidate = response.candidates[0]
            meta = candidate.grounding_metadata
            if not meta or not meta.grounding_chunks:
                return citations
            for chunk in meta.grounding_chunks:
                if chunk.web and chunk.web.uri:
                    citations.append({"title": chunk.web.title or "", "uri": chunk.web.uri})
        except (AttributeError, IndexError):
            pass
        return citations

    # ------------------------------------------------------------------
    # Rate-limit wait helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_reset_duration(s: str) -> int:
        total = 0
        m = re.search(r"(\d+)m", s)
        if m:
            total += int(m.group(1)) * 60
        m = re.search(r"([\d.]+)s", s)
        if m:
            total += int(float(m.group(1)))
        if not total:
            m = re.search(r"(\d+)ms", s)
            if m:
                total = 1
        return max(total, 1)

    def _groq_429_wait(self, error: groq_lib.RateLimitError, attempt: int) -> int:
        _FALLBACK = [90, 180, 360]
        try:
            hdrs = error.response.headers
            retry_after = hdrs.get("retry-after")
            if retry_after and retry_after.isdigit():
                secs = int(retry_after) + 10
                logger.info("  Groq Retry-After header: %ss → waiting %ds", retry_after, secs)
                return secs
            for header in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                reset_str = hdrs.get(header)
                if reset_str:
                    secs = self._parse_reset_duration(reset_str) + 10
                    logger.info("  Groq %s: %s → waiting %ds", header, reset_str, secs)
                    return secs
        except Exception:
            pass
        fallback = _FALLBACK[min(attempt, len(_FALLBACK) - 1)]
        logger.info("  No Groq rate-limit headers — using fallback: %ds", fallback)
        return fallback

    def _gemini_429_wait(self, error: genai_errors.ClientError, attempt: int) -> int:
        _FALLBACK = [30, 60, 120]
        try:
            hdrs = error.response.headers
            retry_after = hdrs.get("retry-after")
            if retry_after and retry_after.isdigit():
                secs = int(retry_after) + 10
                logger.info("  Gemini Retry-After header: %ss → waiting %ds", retry_after, secs)
                return secs
            for header in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                reset_str = hdrs.get(header)
                if reset_str:
                    secs = self._parse_reset_duration(reset_str) + 10
                    logger.info("  Gemini %s: %s → waiting %ds", header, reset_str, secs)
                    return secs
        except Exception:
            pass
        try:
            for detail in (getattr(error, "details", None) or []):
                if isinstance(detail, dict) and "retryDelay" in detail:
                    delay_str = str(detail["retryDelay"])
                    if delay_str.endswith("s"):
                        secs = int(float(delay_str[:-1])) + 5
                        logger.info("  Gemini retryDelay: %s → waiting %ds", delay_str, secs)
                        return secs
        except Exception:
            pass
        fallback = _FALLBACK[min(attempt, len(_FALLBACK) - 1)]
        logger.info("  No Gemini rate-limit info — using fallback: %ds", fallback)
        return fallback
