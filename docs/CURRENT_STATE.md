## Last Action
- **Session 17 — GitHub Pre-Push Polish (2026-05-04): Complete**
  - `dashboard/app.py` — Replaced `use_container_width=True` with `width="stretch"` on `st.dataframe` (×2) and `st.plotly_chart` (×1). Buttons retain `use_container_width` (still valid API, not a deprecation source).
  - `dashboard/app.py` — Removed sidebar "Agent pulse log snippet" (`st.code` block); debugging now via the in-dashboard Audit Log Browser and `logs/app.log`.
  - `README.md` — Full rewrite with founder-style tone. How to Run uses `python main.py --harvest / --backtest --limit 10 / --serve`. Project tree matches current `src/` layout.
  - `docs/SUMMARY.md` — Full rewrite with strategic framing; architecture in three narrative layers.

- **Session 16 — Alpha Terminal Dashboard (2026-05-01): Complete**
  - `dashboard/app.py` — full overhaul: "Alpha Terminal" branding, institutional color palette (Emerald/Crimson/Slate).
  - Top KPI row (4 cards): Global Win Rate, HC Accuracy, Signals Generated (24h), Top Performing Ticker — all sourced from `backtest_history` aggregate row + `load_counts()`.
  - Tab 1 "Signal Terminal": inline keyword search (Ticker/Question/Rationale), Conviction Score slider filter, color-coded Sentiment column.
  - Tab 2 "Quant Audit": Accuracy by Asset horizontal bar chart (emerald ≥50%, crimson <50%, 50% dotted baseline), Backtest Log table (last 15 per-ticker rows).
  - New data loaders: `load_backtest_aggregate()`, `load_backtest_tickers()`, `load_backtest_log()`.
  - `load_counts()` extended with `signals_24h` (equity_signals in last 24h).
  - `main.py` — `--serve` branch wrapped in `try/except KeyboardInterrupt` for clean shutdown.
  - Syntax-verified: both files parse clean.

- **Session 15 — Ticker-Aware Backtesting (2026-05-01): Complete**
  - `backtest_history` — `ticker TEXT NULLABLE` column added via Supabase MCP migration.
  - `BacktestSummary` (models.py) — `ticker: str | None = None` added; NULL = global aggregate.
  - `DatabaseService.save_backtest_results()` (database.py) — signature changed to `list[BacktestSummary]`; single bulk INSERT.
  - `Backtester._build_ticker_summary()` (backtester.py) — new method; per-ticker judged/hits/bull/bear/HC stats; `top3_by_pct=[]`.
  - `Backtester._compute_aggregate()` (backtester.py) — return type changed from `BacktestSummary` → `list[BacktestSummary]`; calls `_build_ticker_summary` per ticker, appends global aggregate row.
  - Validated end-to-end: `--backtest --limit 10` → 4 ticker rows + 1 aggregate saved to Supabase. Supabase query confirmed IDs 2–6 with correct ticker symbols and win rates.

- **Session 14 — Standardize Project Structure (2026-05-01): Complete**
  - `logs/`: `automation.log`, `app.log` moved here.
  - `data/`: `latest_results.json`, `test_results.json` moved here.
  - `database/`: `schema_export.sql`, `security_policies.sql`, `seed_data.sql` moved here.
  - `tests/`: `test_backtest_logic.py` moved here; `OUT_FILE` updated to `data/test_results.json`; stale comments cleaned.
  - `src/core/config.py`: `LOGS_DIR` and `DATA_DIR` path constants added; `LOG_FILE` repointed to `logs/automation.log`.
  - `src/utils/logger.py`: `LOG_FILE.parent.mkdir(parents=True, exist_ok=True)` guard added before `FileHandler`.
  - `harvest.sh`: `LOG_FILE` repointed to `logs/automation.log`; `mkdir -p logs/` guard added.
  - Root now contains only `main.py`, `harvest.sh`, `CLAUDE.md`, `README.md`.
  - Verified: no stale path references remain in any `.py` or `.sh` file.

- **Session 13 — Lift & Shift Modular Refactor (2026-04-30): Complete**
  - Full "lift and shift" into professional Python package structure under `src/`.
  - `src/core/`: `config.py` (PROJECT_ROOT-derived paths), `models.py` (Pydantic: MarketSignal, LLMAnalysisResult, BacktestSummary).
  - `src/providers/`: `PolymarketClient`, `YFinanceClient`, `LLMFactory` (full rate-limit + failover logic preserved).
  - `src/utils/`: `DatabaseService`, `NotificationService` (signal alerts + backtest Discord push), `cron_utils`, `logger` (GracefulExit).
  - `src/jobs/`: `Harvester` (pidfile guard + ingest + analyze), `Backtester` (saves to `backtest_history` Supabase table).
  - `dashboard/app.py`: moved from root, imports from `src.*`, paths via `PROJECT_ROOT`.
  - `main.py`: single CLI entrypoint — `--harvest [--limit N]`, `--backtest [--limit N]`, `--serve`.
  - `harvest.sh`: updated — single `python main.py --harvest` call replaces two separate script calls.
  - `backtest_history` table created in Supabase (15 columns, RLS enabled). `latest_results.json` retired.
  - All old root-level scripts removed. `.md` files moved to `docs/`. CLAUDE.md updated.
  - Import dry-run: all modules import cleanly. `main.py --help` verified.

## LLM Status
- **Groq llama-3.1-8b-instant:** ✅ Primary. 30 RPM free tier. Header-aware 429 retry. RATE_LIMIT_DELAY_GROQ=2.5s.
- **Gemini 2.0 Flash:** ✅ Failover. Activates if Groq exhausts 3 retries. Header-aware wait preserved.

## Production Module Versions

| Module | Version | Status |
|---|---|---|
| `src/core/config.py` | v1 | ✅ Active — PROJECT_ROOT-derived paths |
| `src/core/models.py` | v1 | ✅ Active — Pydantic: MarketSignal, LLMAnalysisResult, BacktestSummary |
| `src/providers/polymarket_client.py` | v1 | ✅ Active — PolymarketClient class |
| `src/providers/yfinance_client.py` | v1 | ✅ Active — YFinanceClient class |
| `src/providers/llm_factory.py` | v1 | ✅ Active — LLMFactory; Groq primary, Gemini failover |
| `src/utils/database.py` | v1 | ✅ Active — DatabaseService; all Supabase ops |
| `src/utils/notifications.py` | v1 | ✅ Active — NotificationService; signal alerts + backtest push |
| `src/utils/cron_utils.py` | v1 | ✅ Active — paths from PROJECT_ROOT |
| `src/jobs/harvester.py` | v1 | ✅ Active — Harvester; pidfile guard + ingest + analyze |
| `src/jobs/backtester.py` | v2 | ✅ Active — Backtester; per-ticker rows + aggregate row in backtest_history |
| `dashboard/app.py` | v2 | ✅ Active — Alpha Terminal: 4-KPI cards, Signal Terminal tab, Quant Audit tab |
| `main.py` | v1 | ✅ Active — CLI: --harvest, --backtest, --serve |
| `harvest.sh` | v3 | ✅ Active — calls main.py --harvest |

## Database State

| Table | Rows | RLS | Notes |
|---|---|---|---|
| `markets` | ~130 | ✅ Enabled | 3 categories; refreshed each cycle |
| `market_prices` | ~130 | ✅ Enabled | Refreshed each cron cycle |
| `equity_signals` | **~108** | ✅ Enabled | Pydantic-validated on write |
| `watchlists` | 23 | ✅ Enabled | AI + Crypto + Fintech tickers |
| `backtest_history` | 6 | ✅ Enabled | ticker-aware: 1 row/ticker + 1 aggregate per run |

## Current Status
- **Phases 1–20:** ✅ Complete. System fully production-ready.
- **Ticker-Aware Backtesting:** ✅ Validated. `--backtest --limit 10` outputs correct per-ticker + aggregate console summary; 4 ticker rows + 1 aggregate confirmed in Supabase.
- **Alpha Terminal Dashboard:** ✅ Validated. Clean startup, exit code 0 on Ctrl+C, no traceback.
- **Next Step:** Run `venv/bin/python main.py --harvest` for a full production harvest cycle.

## Known Blockers
- None. System fully operational.

## Throughput Model (Production)
| Provider | Delay | Markets/min | 199 markets |
|---|---|---|---|
| Groq llama-3.1-8b-instant (primary) | 2.5s | 24 | **~8 min** |
| Gemini 2.0 Flash (failover) | 5s | 12 | **~17 min on fresh quota** |

## Production File Tree
```
polymarket_scanner/
├── src/
│   ├── core/
│   │   ├── config.py          ← PROJECT_ROOT, LOGS_DIR, DATA_DIR, LOG_FILE, LOCK_FILE + env vars
│   │   └── models.py          ← Pydantic models: MarketSignal, LLMAnalysisResult, BacktestSummary
│   ├── providers/
│   │   ├── polymarket_client.py  ← PolymarketClient (fetch + parse Gamma API)
│   │   ├── yfinance_client.py    ← YFinanceClient (5-min bars)
│   │   └── llm_factory.py        ← LLMFactory (Groq primary, Gemini failover, 429 handlers)
│   ├── utils/
│   │   ├── database.py           ← DatabaseService (all Supabase ops)
│   │   ├── notifications.py      ← NotificationService (Discord signal + backtest alerts)
│   │   ├── cron_utils.py         ← crontab management + lock file helpers
│   │   └── logger.py             ← GracefulExit + setup_logger (auto-creates logs/)
│   └── jobs/
│       ├── harvester.py          ← Harvester (ingest + analyze pipeline)
│       └── backtester.py         ← Backtester (intraday HIT/MISS → backtest_history)
├── dashboard/
│   └── app.py                    ← Streamlit dashboard (imports from src.*)
├── docs/                         ← All .md documentation
├── database/                     ← schema_export.sql, security_policies.sql, seed_data.sql
├── logs/                         ← automation.log, app.log (runtime — gitignored)
├── data/                         ← latest_results.json, test_results.json (runtime — gitignored)
├── tests/
│   └── test_backtest_logic.py    ← HIT/MISS smoke test; writes to data/test_results.json
├── main.py                       ← CLI: --harvest, --backtest, --serve
├── harvest.sh                    ← Cron wrapper: python main.py --harvest
├── .env                          (gitignored)
├── .env.example                  (safe to commit)
├── CLAUDE.md
├── README.md
└── venv/
```
