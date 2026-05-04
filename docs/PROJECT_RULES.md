## Python Conventions
- Use `httpx` for all async/sync API calls.
- Strict typing: Use Type Hints for all function signatures.
- Environment: Use `python-dotenv` for all secrets (`SUPABASE_URL`, `GEMINI_KEY`).
- Error Handling: All external API calls must be wrapped in `try-except` with logging.

## Financial Logic Rules
- **Volume Threshold:** Ignore any market with < $1,000 total volume.
- **Grounding Requirement:** Every entry in `equity_signals` must have at least one valid source link in the `citations` column.
- **Relevance Filter:** Only signals with `relevance_score` > 6 are displayed in the "High Priority" view of the dashboard.

## Database Rules
- Never use `SELECT *`. Always specify required columns.
- Use `UPSERT` logic for the `markets` table to avoid duplicate primary key errors.