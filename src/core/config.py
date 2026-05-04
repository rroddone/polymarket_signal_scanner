import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root: src/core/config.py → src/core → src → project root
PROJECT_ROOT: Path = Path(__file__).parent.parent.parent

# Runtime directories
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATA_DIR: Path = PROJECT_ROOT / "data"

# Runtime files
LOG_FILE:  Path = LOGS_DIR / "automation.log"
LOCK_FILE: Path = PROJECT_ROOT / "harvest.lock"

# Supabase
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# LLM providers
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY:   str | None = os.getenv("GROQ_API_KEY")

# Notifications
DISCORD_WEBHOOK_URL: str | None = os.getenv("DISCORD_WEBHOOK_URL")

if SUPABASE_URL is None:
    raise EnvironmentError("Missing required environment variable: SUPABASE_URL")
if GEMINI_API_KEY is None:
    raise EnvironmentError("Missing required environment variable: GEMINI_API_KEY")

# LLM configuration
GROQ_MODEL:   str = "llama-3.1-8b-instant"
GEMINI_MODEL: str = "gemini-2.0-flash"
PRIMARY_LLM:  str = "GROQ"   # "GEMINI" or "GROQ"

POLYMARKET_BASE: str = "https://polymarket.com/event"
