# Dockerfile for Optimized GraphRAG Service
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir \
    redis \
    qdrant-client \
    neo4j \
    langchain \
    langchain-openai \
    langchain-core \
    fastapi \
    uvicorn \
    python-dotenv \
    pyyaml \
    sentence-transformers \
    pydantic

# Copy application code
COPY src/ ./src/
COPY config.yaml ./

# Create directories
RUN mkdir -p data/_pipeline logs

# Expose API port
EXPOSE 8001

# Set python path so 'utils' and 'core' imports work
ENV PYTHONPATH=/app/src:/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8001/ || exit 1

# Run optimized API
CMD ["python", "-m", "uvicorn", "src.retriever.retriever_api_optimized:app", "--host", "0.0.0.0", "--port", "8001"]
