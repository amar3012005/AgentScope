"""Shared logging helpers for BLAIQ services.

The goal is consistent, low-noise operational logging across core and
subagents. Every record gets a service tag and relative timestamp, and
high-level workflow events can be rendered as compact key-value strings.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

_PROCESS_START = time.monotonic()
_CONFIGURED_SERVICE: str | None = None
_ORIGINAL_RECORD_FACTORY = logging.getLogRecordFactory()
_NOISY_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "opentelemetry",
    "temporalio",
    "redis",
    "websockets",
)

_FLOW_EVENT_EMOJIS: dict[str, str] = {
    "wf_submit_received": "📥",
    "wf_dispatch_start": "🚀",
    "wf_routing_decision": "🧭",
    "wf_temporal_started": "⏱️",
    "wf_resume_received": "🔁",
    "wf_resume_start": "🔄",
    "wf_resume_signal_sent": "📨",
    "wf_node_transition": "🧩",
    "wf_hitl_blocked": "🛑",
    "wf_complete": "✅",
    "wf_error": "❌",
    "wf_regenerate_received": "♻️",
    "wf_regenerate_start": "🔧",
    "design_pipeline_start": "🎨",
    "design_generation_start": "🖌️",
    "design_generation_complete": "🖼️",
    "design_generation_error": "💥",
    "gap_analysis_start": "🔎",
    "gap_analysis_complete": "📊",
    "gap_analysis_error": "⚠️",
    "governance": "🛡️",
    "planner": "🧠",
    "graphrag": "📚",
    "content": "📝",
    "temporal_connected": "🔗",
    "worker_start": "👷",
}


def _event_emoji(event: str) -> str | None:
    if event in _FLOW_EVENT_EMOJIS:
        return _FLOW_EVENT_EMOJIS[event]
    lower = event.lower()
    if "error" in lower or "fail" in lower:
        return "❌"
    if "complete" in lower or "done" in lower or "success" in lower:
        return "✅"
    if "start" in lower or "received" in lower:
        return "🚀"
    if "resume" in lower:
        return "🔁"
    if "routing" in lower or "plan" in lower:
        return "🧭"
    return None


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _ORIGINAL_RECORD_FACTORY(*args, **kwargs)
    if not hasattr(record, "service"):
        record.service = "unknown"
    if not hasattr(record, "reltime_ms"):
        record.reltime_ms = int((time.monotonic() - _PROCESS_START) * 1000)
    return record


class ServiceFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service_name
        record.reltime_ms = int((time.monotonic() - _PROCESS_START) * 1000)
        return True


class FlowOnlyFilter(logging.Filter):
    """Keep log output focused on workflow flow events.

    If ``BLAIQ_FLOW_LOGS_ONLY=true`` (or ``FLOW_LOGS_ONLY=true``), INFO/DEBUG
    records are only emitted when they are produced via ``log_flow`` (message
    starts with ``event=``). Warnings and errors are always kept.
    """

    def __init__(self) -> None:
        super().__init__()
        value = os.getenv("BLAIQ_FLOW_LOGS_ONLY", os.getenv("FLOW_LOGS_ONLY", "false"))
        self.enabled = str(value).strip().lower() in {"1", "true", "yes", "on"}

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.enabled:
            return True
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        return msg.startswith("event=")


def _configure_noisy_loggers() -> None:
    quiet = os.getenv("BLAIQ_QUIET_LIB_LOGS", "true").strip().lower() in {"1", "true", "yes", "on"}
    if not quiet:
        return
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_service_logging(service_name: str, level: str | None = None) -> None:
    """Configure a compact, structured log format for a service process."""
    global _CONFIGURED_SERVICE

    if _CONFIGURED_SERVICE == service_name:
        return

    logging.setLogRecordFactory(_record_factory)
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(ServiceFilter(service_name))
    handler.addFilter(FlowOnlyFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(name)s [svc=%(service)s rel=%(reltime_ms)06dms] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, (level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO))
    _configure_noisy_loggers()
    _CONFIGURED_SERVICE = service_name


def format_flow_event(event: str, **fields: Any) -> str:
    """Render a compact key-value workflow event string.

    Lists and dicts are JSON-encoded so the output stays single-line and
    machine-readable.
    """

    def encode(value: Any) -> str:
        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return str(value)

    parts = [f"event={event}"]
    emoji = _event_emoji(event)
    if emoji:
        parts.append(f"icon={emoji}")
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={encode(value)}")
    return " ".join(parts)


def log_flow(logger: logging.Logger, event: str, level: str = "info", **fields: Any) -> None:
    """Log a flow event using the configured service logger."""
    message = format_flow_event(event, **fields)
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message)
