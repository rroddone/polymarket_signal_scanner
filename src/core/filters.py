import re

CATEGORY_BLOCKLIST: frozenset[str] = frozenset({
    "Crypto", "Pop Culture", "Sports", "Politics", "Creator Economy",
})

# Compiled once at import — word-boundary anchors prevent partial matches
# (e.g. "Meme" won't fire on "Moment", "IPO" won't fire on "repo")
_KEYWORD_PATTERN = re.compile(
    r"\b(?:XRP|Solana|Dogecoin|NFT|Meme|IPOs?|Strava|Hourly)\b"
    r"|\bUp\s+or\s+Down\b"
    r"|\bPrice\s+[Bb]et\b"
    r"|\bDaily\s+[Cc]lose\b"
    r"|\b2PM\s*ET\b",
    re.IGNORECASE,
)


class MarketPreFilter:
    """Deterministic triage gates — zero LLM calls involved."""

    def failed_category_gate(self, market: dict) -> bool:
        """Stage 1: drop if category is in the noise blocklist."""
        return market.get("category", "") in CATEGORY_BLOCKLIST

    def failed_keyword_blocklist(self, title: str) -> bool:
        """Stage 2: drop if title contains a hard-blocked keyword/phrase."""
        return bool(_KEYWORD_PATTERN.search(title))
