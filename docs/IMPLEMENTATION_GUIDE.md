## Polymarket Gamma API
- **Endpoint:** `https://gamma-api.polymarket.com/markets`
- **Query Params:** `limit=100`, `active=true`, `order=volume24hr`, `ascending=false`
- **Pre-Filter:** Only process `Business`, `Crypto`, and `Tech` categories.

## Gemini Analysis Prompt
- **Context:** Act as a BIT Capital Equity Analyst.
- **Logic:** Cross-reference market question with current `watchlists`.
- **Search Tool:** Must search for at least one recent (last 7 days) news article to ground the analysis.
- **Output Format:** Strict JSON.

## Email Alert Logic
- **Trigger:** `relevance_score >= 8` AND `impact_type != 'Neutral'`.
- **Frequency:** Immediate upon discovery in `analyze.py`.