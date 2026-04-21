FROM node:20-alpine AS frontend-build

WORKDIR /app/static
ARG VITE_API_BASE=
ARG VITE_TENANT_ID=default
ARG VITE_API_KEY=
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_TENANT_ID=$VITE_TENANT_ID
ENV VITE_API_KEY=$VITE_API_KEY

COPY static/package*.json ./
RUN npm ci

COPY static/ ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic \
    jinja2 \
    httpx \
    openai \
    websockets \
    python-multipart \
    pypdf \
    python-docx \
    neo4j \
    qdrant-client \
    "langgraph>=0.4" \
    "langgraph-checkpoint-redis>=0.1" \
    "temporalio>=1.8" \
    "redis>=5.0" \
    "opentelemetry-sdk>=1.25" \
    "opentelemetry-instrumentation-fastapi>=0.46b0" \
    pyyaml \
    python-dotenv

COPY src/ ./src/
COPY static/ ./static/
COPY --from=frontend-build /app/static/dist ./static/dist
COPY brand_dna/ ./brand_dna/
COPY config.yaml* ./

ENV PYTHONPATH=/app/src:/app
ENV PYTHONUNBUFFERED=1

EXPOSE 6000 6002

CMD ["python", "-m", "uvicorn", "src.orchestrator.orchestrator_api:app", "--host", "0.0.0.0", "--port", "8010"]
