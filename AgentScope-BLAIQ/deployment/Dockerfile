FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js and pnpm for React artifact bundling
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g pnpm && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.lock pyproject.toml README.md /app/
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /app/requirements.lock

# Install agentscope-runtime separately to preserve the heavy cache above
RUN pip install agentscope-runtime "agentscope-runtime[ext]"
RUN pip install groq

COPY src /app/src
COPY deployment /app/deployment

ENV PYTHONPATH=/app/src

RUN mkdir -p /app/data/uploads /app/data/artifacts /app/data/agent_profiles /app/logs

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8090/readyz || exit 1

CMD ["sh", "-c", "python /app/deployment/bootstrap.py --migrate && exec python -m uvicorn agentscope_blaiq.app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8090}"]
