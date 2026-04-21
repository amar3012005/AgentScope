FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install only the dependencies the temporal worker actually needs
# (subset of pyproject.toml — avoids heavy deps like camelot, docling, tesseract)
RUN pip install --no-cache-dir \
    "fastapi>=0.118.3" \
    "uvicorn>=0.37.0" \
    "pydantic>=2.11.7" \
    "httpx>=0.28.1" \
    "openai>=1.0" \
    "websockets>=15.0.1" \
    "python-dotenv>=1.1.1" \
    "pyyaml>=6.0" \
    "temporalio>=1.8" \
    "langgraph>=0.4" \
    "langgraph-checkpoint-redis>=0.1" \
    "redis>=5.0" \
    "opentelemetry-sdk>=1.25" \
    "opentelemetry-instrumentation-fastapi>=0.46b0" \
    "opentelemetry-exporter-otlp-proto-grpc>=1.25"

COPY src/ ./src/
COPY brand_dna/ ./brand_dna/
COPY config.yaml .

ENV PYTHONPATH=/app/src:/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "orchestrator.temporal_worker"]
