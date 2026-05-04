import logging
import sys
from pathlib import Path

from src.core.config import LOG_FILE


class GracefulExit(Exception):
    """Raised to stop the pipeline cleanly without triggering the circuit breaker."""


def setup_logger(name: str = __name__) -> logging.Logger:
    """
    Configure the named logger to write to automation.log.

    FileHandler only — harvest.sh redirects stdout/stderr to the same file so
    a dual-handler setup would duplicate every INFO line.
    """
    _log_p = Path(LOG_FILE)
    _log_p.parent.mkdir(parents=True, exist_ok=True)
    # Rotate log when it exceeds 1 MB so the UI tail stays fast
    if _log_p.exists() and _log_p.stat().st_size > 1_000_000:
        kept = _log_p.read_text().splitlines()[-500:]
        _log_p.write_text("\n".join(kept) + "\n")

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.FileHandler(str(LOG_FILE), mode="a")
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def flush_logs() -> None:
    sys.stdout.flush()
    logging.shutdown()
