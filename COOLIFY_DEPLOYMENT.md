# Coolify Deployment Guide - GraphRAG Optimized

## 📋 Overview
This guide shows you how to deploy the GraphRAG Optimized service in Coolify, following the same pattern as your existing RAG service.

## 🚀 Quick Setup Steps

### Step 1: Create New Service in Coolify

1. **Log into Coolify Dashboard**
2. **Navigate to**: Projects → blaiq-amar → Create New Service
3. **Select**: Docker Compose
4. **Service Name**: `graphrag-optimized`

### Step 2: Prepare Service Directory

Once Coolify creates the service, note the **SERVICE_ID** (e.g., `xyz123abc456...`)

```bash
# SSH into your Coolify server
ssh your-server

# Navigate to the new service directory
cd /data/coolify/services/<SERVICE_ID>

# Create the application directory
mkdir -p graphrag-optimized

# Copy your GraphRAG code to the service directory
# Option 1: From local machine (run on your local machine)
scp -r /root/blaiq/* your-server:/data/coolify/services/<SERVICE_ID>/graphrag-optimized/

# Option 2: Clone from git (run on server)
cd /data/coolify/services/<SERVICE_ID>
git clone <your-repo-url> graphrag-optimized
```

### Step 3: Update docker-compose.yml

Replace the Coolify-generated `docker-compose.yml` with the customized version:

```bash
cd /data/coolify/services/<SERVICE_ID>

# Backup original
cp docker-compose.yml docker-compose.yml.backup

# Copy the Coolify-compatible compose file
cp /root/blaiq/docker-compose.coolify.yml docker-compose.yml

# IMPORTANT: Update the SERVICE_ID placeholder
sed -i 's/<SERVICE_ID>/<YOUR_ACTUAL_SERVICE_ID>/g' docker-compose.yml
```

### Step 4: Configure Environment Variables

Create or update the `.env` file:

```bash
cd /data/coolify/services/<SERVICE_ID>
nano .env
```

Add the following required variables:

```bash
# ============================================================
# REQUIRED: Qdrant Vector Database
# ============================================================
QDRANT_URL=https://qdrant.api.blaiq.ai
QDRANT_API_KEY=wZ0BbfJdj41n5aSR9rfuU3vlNBQXxdbSFCfXcUQRg9RFB5nuUTEXkVey2EiifyYZ8hNQBN6w2kY56WtUJBFhJxltJ45WGh3w
QDRANT_COLLECTION=bundb_app_blaiq_ai_knowledgeglobal_421765297988070tsxTz6itX0BGb9_nXy35B
QDRANT_PORT=443

# ============================================================
# REQUIRED: OpenAI-Compatible LLM
# ============================================================
OPENAI_API_KEY=sk-MQ3-oISrdPQ2VkhICMLRXA
OPENAI_API_BASE_URL=https://api.blaiq.ai/v1
OPENAI_MODEL=gpt-4o-mini

# LiteLLM Model Configuration
LITELLM_PLANNER_MODEL=gpt-4o-mini
LITELLM_PRE_MODEL=gpt-4o-mini
LITELLM_POST_MODEL=gpt-4o-mini

# ============================================================
# OPTIONAL: Neo4j Graph Database
# ============================================================
NEO4J_URI=bolt+s://neo4j.api.blaiq.ai:7689
NEO4J_USER=neo4j
NEO4J_PASSWORD=xyDgCUAC7BXOHKmBprNb

# ============================================================
# OPTIONAL: BGE-M3 Embedding Service
# ============================================================
BGE_M3_SERVICE_URL=https://local-llm-cloudblue.api.blaiq.ai
BGE_M3_API_KEY=BoTBeqtiavWdrW1fQ2Y1E1Gd4ETMivZXTUrfxDf10LkRm7Rd6LPItVPxRmXKo4Ue0yO05J8Gf3a4si1yIBIxuhu48FxnfZbe
BGE_M3_MODEL_ID=bge-m3

# ============================================================
# Redis Cache Configuration
# ============================================================
REDIS_URL=redis://redis:6379/0
ENABLE_CACHE=true
CACHE_TTL=3600

# ============================================================
# API Security
# ============================================================
API_KEY=your_secure_api_key_here

# ============================================================
# Service Configuration
# ============================================================
VERSION=latest
LOG_LEVEL=INFO
```

### Step 5: Build and Deploy

```bash
cd /data/coolify/services/<SERVICE_ID>

# Build the service
docker compose build

# Start the service
docker compose up -d

# Check logs
docker compose logs -f graphrag-optimized
```

## 🔍 Verification

### Check Service Status
```bash
# Check running containers
docker ps | grep graphrag

# Check Redis
docker exec redis-graphrag-optimized redis-cli ping
# Should return: PONG

# Check GraphRAG API health
curl http://localhost:8445/
```

### Test the API
```bash
# Health check
curl http://localhost:8445/

# Test query
curl -X POST "http://localhost:8445/query/graphrag" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secure_api_key_here" \
  -d '{
    "query": "What are the main topics?",
    "k": 20,
    "use_cache": true
  }'
```

## 🌐 Configure Domain (Optional)

If you want to expose this service via a domain:

### Option 1: Via Coolify UI
1. Go to Service Settings in Coolify
2. Add domain: `rag-optimized.demo.davinciai.eu`
3. Coolify will automatically configure Traefik

### Option 2: Manual Traefik Labels
Uncomment these labels in `docker-compose.yml`:
```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.graphrag-optimized.rule=Host(`rag-optimized.demo.davinciai.eu`)
  - traefik.http.services.graphrag-optimized.loadbalancer.server.port=8001
```

## 📊 Service Ports

| Service | Internal Port | External Port | URL |
|---------|---------------|---------------|-----|
| GraphRAG Optimized API | 8001 | 8445 | http://localhost:8445 |
| Redis Cache | 6379 | - | Internal only |

## 🔧 Common Operations

### View Logs
```bash
# All services
docker compose logs -f

# Just GraphRAG
docker compose logs -f graphrag-optimized

# Just Redis
docker compose logs -f redis
```

### Restart Services
```bash
docker compose restart
```

### Rebuild After Code Changes
```bash
docker compose build --no-cache
docker compose up -d
```

### Clear Cache
```bash
curl -X POST http://localhost:8445/cache/clear
```

### Stop Services
```bash
docker compose down
```

## 🐛 Troubleshooting

### Issue: Build fails with "schemas/ not found"
**Solution**: The Dockerfile expects a `schemas/` directory. Either:
1. Create an empty schemas directory: `mkdir -p graphrag-optimized/schemas`
2. Or modify the Dockerfile to make it optional

### Issue: Redis connection failed
**Solution**:
```bash
# Check Redis is running
docker ps | grep redis

# Check Redis logs
docker logs redis-graphrag-optimized

# Test connection
docker exec redis-graphrag-optimized redis-cli ping
```

### Issue: Qdrant connection failed
**Solution**:
```bash
# Verify QDRANT_URL in .env
cat .env | grep QDRANT_URL

# Test connection
curl -H "api-key: $QDRANT_API_KEY" $QDRANT_URL/collections
```

### Issue: Container keeps restarting
**Solution**:
```bash
# Check logs for errors
docker compose logs graphrag-optimized

# Check health status
docker inspect graphrag-optimized | grep -A 10 Health
```

## 📁 Directory Structure

After setup, your service directory should look like:

```
/data/coolify/services/<SERVICE_ID>/
├── docker-compose.yml          # Coolify-managed compose file
├── .env                        # Environment variables
└── graphrag-optimized/         # Your application code
    ├── Dockerfile
    ├── pyproject.toml
    ├── uv.lock
    ├── config.yaml
    ├── src/
    │   ├── retriever/
    │   ├── pipeline/
    │   └── utils/
    └── data/                   # Persistent data (mounted volume)
```

## 🔐 Security Checklist

- [ ] `.env` file has proper permissions (600)
- [ ] API_KEY is set to a strong random value
- [ ] Qdrant API key is valid and secured
- [ ] OpenAI API key is valid and secured
- [ ] SSL certificates configured (if using HTTPS)
- [ ] Firewall rules configured for port 8445

## 🎯 Next Steps

1. **Monitor Performance**: Check cache hit rates and response times
2. **Set Up Monitoring**: Add Prometheus/Grafana (optional)
3. **Configure Backups**: Set up volume backups for Redis data
4. **Load Testing**: Test with production-like load
5. **Documentation**: Document your specific configuration

## 📞 Support

If you encounter issues:
1. Check logs: `docker compose logs -f`
2. Verify environment variables: `cat .env`
3. Test connectivity to external services (Qdrant, Neo4j, OpenAI)
4. Check Coolify dashboard for service status
