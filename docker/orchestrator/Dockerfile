FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic \
    httpx \
    openai \
    websockets \
    python-multipart \
    pypdf \
    python-docx \
    neo4j \
    qdrant-client

COPY src/ ./src/
COPY static/ ./static/

ENV PYTHONPATH=/app/src:/app
ENV PYTHONUNBUFFERED=1

EXPOSE 6000 6002

CMD ["python", "-m", "uvicorn", "src.orchestrator.orchestrator_api:app", "--host", "0.0.0.0", "--port", "8010"]
