# docker/retriever/Dockerfile

FROM python:3.12-slim

# Install uv (copy from official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy project files (dependencies info first for better caching)
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY config.prod.yaml ./config.yaml
COPY schemas/ ./schemas/
COPY README.md ./  
# Install dependencies using uv (frozen lock file)
RUN uv sync --frozen --no-dev

# Create job storage directory
RUN mkdir -p _jobs && chmod -R 777 _jobs

# Expose retriever API port
EXPOSE 8001

# Health check with API key authentication
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD /app/.venv/bin/python -c "import requests; import os; requests.get('http://localhost:8001/', headers={'X-API-Key': os.environ.get('API_KEY', '')})" || exit 1

# Run retriever API using uvicorn from the uv-managed venv
CMD ["/app/.venv/bin/uvicorn", "src.retriever.retriever_api:app", "--host", "0.0.0.0", "--port", "8001"]