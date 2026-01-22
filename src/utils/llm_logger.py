# src/utils/llm_logger.py

import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

LOG_PATH = os.getenv("LLM_ERROR_LOG_PATH", "logs/llm_error.log")
MAX_BYTES = int(os.getenv("LLM_ERROR_LOG_MAX_BYTES", "5242880"))  # 5MB
BACKUP_COUNT = int(os.getenv("LLM_ERROR_LOG_BACKUP_COUNT", "5"))

_logger = None


def _get_llm_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("llm")
    logger.setLevel(logging.INFO)

    # logs: Auto create directory
    os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)

    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
    )
    # JSON - only one line, so format is message
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(handler)
    _logger = logger
    return logger


def log_llm_event(event_type: str, data: dict) -> None:
    """
    event_type example:
      - "llm_error"
      - "llm_fallback_success"
    """
    logger = _get_llm_logger()

    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event": event_type,
        **data,
    }

    try:
        logger.info(json.dumps(entry, ensure_ascii=False))
    except Exception:
        # logging because this logic should not die
        pass
