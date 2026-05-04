## Objective
Build a Polymarket Signal Scanner to identify prediction market outcomes that impact public equities (AI & Crypto focus).

## Core Requirements
- **Automated Ingestion:** Scheduled pipeline (Cron) to pull Polymarket data.
- **Intelligent Filtering:** LLM-based logic to discard noise and keep equity-relevant signals.
- **Impact Quantification:** Quantify signals (Bullish/Bearish) with financial rationale.
- **Web Interface:** Streamlit dashboard for analysts to browse signals and reports.
- **Email Alerts:** Send an automated email for any signal with a relevance score > 8.

## Constraints
- **Timeline:** 2 Weeks (Final Deadline: 14 days from today).
- **Frontend:** Direct access to dashboard (no login/auth).
- **Data Retention:** Keep 30 days of `market_prices` history before archiving/purging.