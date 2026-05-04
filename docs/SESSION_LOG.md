# Session Log — Polymarket Signal Scanner

Chronological record of all development sessions.

---

## Session 3 — 2026-04-28 (Full Day)
**Theme: Groq Migration, Score Calibration, and UI Completion**

### What We Solved

#### Problem 1: Gemini Free-Tier 429 Lockout (Critical Blocker)
The Gemini 2.0 Flash free tier has a hard daily RPD (requests-per-day) quota that was
exhausted at ~56 requests. `--no-search` mode did not bypass it — both modes share the
same daily bucket. The system was unable to run a full harvest.

**Solution — Dual-Provider Pipeline (Phase 11):**
- Installed `groq==1.2.0`; added `GROQ_API_KEY` to `.env`
- `config.py`: added `GROQ_MODEL`, `GEMINI_MODEL`, `PRIMARY_LLM = "GROQ"`
- `analyze.py` refactored with three layers:
  - `_analyze_groq()` — Groq primary; raises `RateLimitError`/`APIConnectionError` to
    signal failover (not retried on Groq)
  - `_analyze_gemini()` — Gemini fallback; retries with exponential backoff on 429
  - `analyze_market()` — failover wrapper; returns `(result, citations, provider, triggered_failover)`
- `run_analysis()` tracks `active_provider` and `rate_limit_delay` at session level:
  - Groq: 2 s inter-market delay
  - On failover: switches to Gemini, delay rises to 15 s for the rest of the run
- `equity_signals` table: `provider TEXT` column added via Supabase migration
- Test harvest `--limit 5`: 5/5 saved via Groq in ~30 s (vs. ~75 s+ with Gemini + 429s)
- Search grounding AFC instructions removed from prompt (Groq uses market context only)

#### Problem 2: High-Score Bias (All Signals Scoring 9–10)
The LLM was anchoring to a high score and backfilling justification. Every market was
coming back as "9" regardless of actual relevance.

**Solution — Skeptical Analyst Rubric + Chain-of-Thought (Phase 12):**
- Persona: "You are a skeptical hedge fund analyst. You are penalized for assigning a
  score above 7 unless the link is direct, undeniable, and material."
- Explicit four-band rubric in the prompt: 9–10 Critical / 7–8 Strong / 5–6 Moderate /
  1–4 Tenuous, with worked examples for each band
- Key CoT technique: JSON key order changed so `rationale` comes **before**
  `relevance_score` — the model writes its reasoning first, then derives the score from it
- Validation run `--limit 3`:
  - "Bitcoin above X on April 24?" → MSTR, Bullish, **10** (direct BTC/balance-sheet link ✅)
  - "Largest Company end of June?" → AAPL, Neutral, **5** (vague positioning, multi-hop ✅)
  - "Bitcoin all time high by X?" → MSTR, Bullish, **10** (BTC NAV impact, first-order ✅)

#### Problem 3: Static Dashboard (No Live Feedback During Harvest)
The dashboard only updated on browser refresh. No visibility into harvest progress.

**Solution — Live Intelligence Feed + Full Harvest Mode (Phases 13–14):**

*Phase 13 — Full Harvest Mode:*
- Removed `--limit 5` hardcoded arg from the sidebar harvest button
- `TIMEOUT_SECS` raised from 300 → 1800 (30 min) for full harvests
- `st.warning()` added above button explaining the full-harvest scope
- Button renamed "🚀 Start Full Harvest"

*Phase 14 — Live Intelligence Feed:*
- `_feed_entry(line)`: translates raw analyze.py log lines to human-readable events
- `_render_feed_html(entries)`: renders feed entries as a `max-height:300px; overflow-y:auto`
  scrollable HTML block (injected via `unsafe_allow_html=True`)
- `**bold**` / `*italic*` markdown converted to `<strong>` / `<em>` for the HTML path
- Progress bar (`st.progress`) advances on every `[i/total]` log marker
- `progress_cap` shows live "N signals captured" count
- Final "Analysis Complete" line parsed for authoritative saved/skipped counts
- Completion banner: `"✅ Harvest Complete: X New Signals, Y Markets Skipped."`

*Phase 15 — Status Indicator + Refresh UX:*
- `@st.cache_data(ttl=10)` on both `load_signals()` and `load_counts()` (was 300 s)
- "🔄 Refresh Market Data" button at top of sidebar: `st.cache_data.clear()` + `st.rerun()`
- `get_ai_status()` updated:
  - Added `🔵 Analyzing…` state when `harvest_running = True`
  - "System Active" renamed to "🟢 System Ready"
  - `_last_harvest_logs` cleared on successful completion so `🟡 Rate Limited` cannot persist
- `load_signals()` query: `.limit(1000)` safety ceiling added

### Database State at Session End

| Metric | Value |
|---|---|
| Total signals | **93** |
| High relevance (≥ 8) | **51** (55%) |
| Bullish | 48 |
| Bearish | 12 |
| Neutral | 32 |
| Active markets | 133 |
| Total markets | 133 |
| Watchlist tickers | 23 |
| Provider | `llama-3.3-70b-versatile` (100% Groq, no failover needed) |
| Last signal written | 2026-04-28 20:11 UTC |

### Files Changed This Session

| File | Version | Changes |
|---|---|---|
| `analyze.py` | v5 → v6 | Groq primary, Gemini failover, CoT rubric, `provider` field |
| `config.py` | v1 → v2 | `GROQ_API_KEY`, `GROQ_MODEL`, `GEMINI_MODEL`, `PRIMARY_LLM` |
| `app.py` | v6 → v9 | Live feed, progress bar, scroller, status fix, TTL=10, Full Harvest |
| `README.md` | — | Full rewrite to reflect dual-provider pipeline and new features |
| `SESSION_LOG.md` | — | Created (this file) |
| `CURRENT_STATE.md` | — | Updated with final DB state |
| `SESSION_HANDOFF.md` | — | Updated with next-session handover note |
| `.env` | — | `GROQ_API_KEY` added |
| `.env.example` | — | `GROQ_API_KEY` placeholder added |
| Supabase | — | `equity_signals.provider TEXT` column added via migration |

---

## Session 2 — 2026-04-28 (Morning)
**Theme: Rate Limit Hardening, No-Search Mode, Dashboard Polish, Code Quality**

- `analyze.py` v3 → v5: `RATE_LIMIT_DELAY` 5 s → 15 s; `BACKOFF_BASE` 15 s → 20 s;
  backoff capped at 60 s; `--no-search` flag added (`tools=[]`, internal-knowledge prompt);
  adaptive delay constants (`RATE_LIMIT_DELAY_SEARCH` / `RATE_LIMIT_DELAY_NO_SEARCH`)
- `app.py` v5 → v6: AI Status Indicator (🟢/🟡/⚪), 3-card metrics row, Impact
  color coding, Rationale `max_chars=160` tooltip, harvest log persistence for 429 badge
- Root cause confirmed: Gemini 429s hit the daily RPD quota (not just Search Grounding RPM)
- Code quality pass: `POLYMARKET_BASE` moved to `config.py`; colour palette consolidated;
  stale comments and task-doc references removed from all files

---

## Session 1 — 2026-04-26 / 2026-04-27
**Theme: Foundation, Ingestion, Analysis, Notifications, Dashboard, DB Security**

- **Phase 1:** Supabase schema (`markets`, `market_prices`, `equity_signals`, `watchlists`),
  Python venv, `.env` / `.env.example`
- **Phase 2:** `ingest.py` — Polymarket Gamma API, volume filter, UPSERT logic;
  132 markets seeded across Business, Crypto, Tech
- **Phase 3:** `analyze.py` — Gemini 2.0 Flash + Google Search grounding, JSON response
  parsing, circuit breaker (3 consecutive failures → exit), exponential backoff,
  AFC response parsing (`extract_text_from_response`)
- **Phase 4:** `notifications.py` — Discord webhook, rich embed format, score ≥ 8 threshold,
  graceful skip if URL not configured
- **Phase 5:** `app.py` — Streamlit dashboard, sidebar filters, metrics row, Plotly stacked
  bar chart, live harvest log streaming via `subprocess.Popen` + `select`
- **Phase 6:** RLS enabled on all 4 tables (8 policies); `schema_export.sql`,
  `security_policies.sql`, `seed_data.sql` generated and applied
