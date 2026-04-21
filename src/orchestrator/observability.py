"""OpenTelemetry observability helpers with graceful degradation.

When the ``opentelemetry`` packages are installed the module configures a
``TracerProvider`` with a console exporter (for local dev) and an optional
OTLP exporter (when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set).  If the
packages are missing everything degrades to silent no-ops so the rest of
the application can run without any observability dependency.

Usage::

    from src.orchestrator.observability import setup_otel, get_tracer

    setup_otel("blaiq-orchestrator")
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("my_operation"):
        ...
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("blaiq-otel")

# ---------------------------------------------------------------------------
# Feature flag: detect whether OTel SDK is available
# ---------------------------------------------------------------------------
_OTEL_AVAILABLE = False

try:
    from opentelemetry import context, trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    _OTEL_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# No-op fallbacks
# ---------------------------------------------------------------------------

class _NoOpSpan:
    """Minimal stand-in when OTel is unavailable."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: ARG002
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Tracer replacement that yields ``_NoOpSpan`` instances."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:  # noqa: ARG002
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:  # noqa: ARG002
        return _NoOpSpan()


_noop_tracer = _NoOpTracer()
_propagator: Any = None
_setup_done = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_otel(service_name: str) -> None:
    """Configure the OpenTelemetry ``TracerProvider``.

    * Always attaches a ``ConsoleSpanExporter`` for local development
      visibility.
    * If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, also attaches the OTLP
      gRPC exporter for production collector pipelines.

    Safe to call multiple times; subsequent calls are no-ops.

    Args:
        service_name: Logical service name embedded in every span.
    """
    global _setup_done, _propagator  # noqa: PLW0603

    if _setup_done:
        return

    _setup_done = True

    if not _OTEL_AVAILABLE:
        logger.info(
            "opentelemetry SDK not installed — tracing disabled. "
            "Install opentelemetry-sdk to enable."
        )
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Console exporter — always active for local dev
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # OTLP exporter — activated by environment variable
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otel_insecure = os.getenv("OTEL_INSECURE", "false").lower() == "true"
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=otel_insecure))
            )
            logger.info("OTLP exporter configured endpoint=%s", otlp_endpoint)
        except ImportError:
            logger.warning(
                "OTEL_EXPORTER_OTLP_ENDPOINT is set but "
                "opentelemetry-exporter-otlp-proto-grpc is not installed — "
                "OTLP export disabled."
            )

    trace.set_tracer_provider(provider)
    _propagator = TraceContextTextMapPropagator()

    logger.info("OpenTelemetry initialised service=%s", service_name)


def get_tracer(name: str) -> Any:
    """Return a tracer bound to *name*.

    Returns a real ``trace.Tracer`` when OTel is initialised, otherwise a
    silent ``_NoOpTracer``.

    Args:
        name: Usually ``__name__`` of the calling module.
    """
    if not _OTEL_AVAILABLE:
        return _noop_tracer
    return trace.get_tracer(name)


def get_trace_headers() -> Dict[str, str]:
    """Inject W3C ``traceparent`` / ``tracestate`` from the current span.

    Returns an empty dict when OTel is unavailable or there is no active
    span.

    Returns:
        Header dict suitable for forwarding to downstream HTTP calls.
    """
    if not _OTEL_AVAILABLE or _propagator is None:
        return {}

    headers: Dict[str, str] = {}
    _propagator.inject(headers)
    return headers


def extract_trace_context(headers: Dict[str, str]) -> Any:
    """Extract W3C trace context from incoming HTTP headers.

    Args:
        headers: Incoming request headers (case-insensitive mapping).

    Returns:
        An OpenTelemetry ``Context`` that can be passed to
        ``tracer.start_as_current_span(context=...)``.  Returns ``None``
        when OTel is unavailable.
    """
    if not _OTEL_AVAILABLE or _propagator is None:
        return None

    return _propagator.extract(carrier=headers)


def trace_middleware(app: Any) -> None:
    """Instrument a FastAPI application with OpenTelemetry HTTP middleware.

    If the ``opentelemetry-instrumentation-fastapi`` package is installed,
    this applies automatic span creation for every inbound request.
    Otherwise it logs a warning and returns without side-effects.

    Args:
        app: A ``FastAPI`` application instance.
    """
    if not _OTEL_AVAILABLE:
        logger.info("OTel not available — skipping FastAPI instrumentation.")
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OTel instrumentation applied.")
    except ImportError:
        logger.warning(
            "opentelemetry-instrumentation-fastapi not installed — "
            "HTTP auto-instrumentation disabled."
        )


__all__ = [
    "extract_trace_context",
    "get_trace_headers",
    "get_tracer",
    "setup_otel",
    "trace_middleware",
]
