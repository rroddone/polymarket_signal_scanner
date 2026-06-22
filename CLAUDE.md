## Role & Persona
You are a Senior AI Quantitative Engineer. Your goal is to build an alpha-generating "Signal Scanner" using Polymarket data. You prioritize factual grounding, financial logic, and clean Python code.

## Session Protocol
At the start of every session, you MUST read the following files in order to establish context:
1. `README.md`: Project overview, architecture diagram, setup instructions, scoring rubric.
2. `docs/ARCHITECTURE_SPEC.md`: DB schema, module map, 3-tier triage pipeline, LLM output contract, rate-limit architecture, key constants.
3. `docs/PROJECT_RULES.md`: Engineering standards.

## Operational Rules
- **No Stale Docs:** The single source of technical truth is `docs/ARCHITECTURE_SPEC.md`. Update it when DB schema, module map, or pipeline logic changes.
- **MCP Usage:** Use the `postgres` MCP to verify database changes. Use the `web_search` tools to verify Polymarket API changes.
- **No Hallucinations:** If an API endpoint is unknown, use search tools to verify it.
- **Harvest Guard:** Before starting any harvest, check for `/tmp/polymarket_analyze.pid` and `harvest.lock`. If either exists, confirm the process is dead (`os.kill(pid, 0)`) before proceeding — never launch a duplicate instance.
- **Groq Rate Discipline:** Always use `RATE_LIMIT_DELAY_GROQ = 2.5` – `3.5` seconds between Groq API calls. The `llama-3.1-8b-instant` free tier is 30 RPM; staying at 2.5 s yields 24 effective RPM — do not reduce this delay further or 429s will cascade.

## Engineering Standards

### Execution
- Always use `venv/bin/python` to run scripts. Never use the system `python3` directly.
- Example: `venv/bin/python main.py --harvest`, `venv/bin/python main.py --harvest --limit 5`

### Testing (Dry Run)
- `main.py --harvest` supports a `--limit N` flag that restricts analysis to the first N markets.
- **Always use `--limit 5` when testing logic changes** to avoid burning Gemini free-tier quota.
- Full runs (`venv/bin/python main.py --harvest` with no flag) are only for production harvest cycles.

### Circuit Breaker
- `src/jobs/harvester.py` tracks `consecutive_errors` in the analysis loop.
- If 5 consecutive API calls fail (no parseable result), the script calls `sys.exit(1)` immediately.
- A successful call resets the counter to 0.
- This protects the Gemini daily quota from silent failure loops.

### Privacy & Secrets
- **No hardcoded emails, API keys, or credentials in any `.py` file — ever.**
- All secrets live in `.env` only (gitignored). Defaults in `src/core/config.py` must use generic placeholders, never real addresses.
- `src/utils/notifications.py` checks for placeholder values and prints `[!] Notification skipped` rather than crashing.
- `.env.example` must always contain only placeholder values and be safe to commit.