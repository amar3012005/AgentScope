# Docker Deployment Guide - Optimized GraphRAG

## 🚀 Quick Start (3 Steps)

### Step 1: Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your actual values
nano .env  # or use your preferred editor
```

**Required API Keys**:
1. **`QDRANT_URL`** - Your Qdrant instance URL
2. **`QDRANT_API_KEY`** - Qdrant authentication key
3. **`OPENAI_API_KEY`** - OpenAI API key (or compatible provider)

**Optional** (for full features):
4. **`NEO4J_PASSWORD`** - Neo4j password (for graph features)
5. **`API_KEY`** - Your custom API key for securing endpoints

---

### Step 2: Build and Start Services

```bash
# Build the optimized API
docker-compose -f docker-compose.optimized.yml build

# Start Redis + GraphRAG API
docker-compose -f docker-compose.optimized.yml up -d

# Check logs
docker-compose -f docker-compose.optimized.yml logs -f graphrag-optimized
```

**Expected output**:
```
✅ Redis cache connected: redis://redis:6379
✅ Qdrant connected via URL: https://qdrant.api.blaiq.ai
✅ Neo4j connected at bolt://...
✅ Embeddings ready (model=BAAI/bge-m3, dim=1024)
✅ GraphRAG Retriever initialized
```

---

### Step 3: Test the API

```bash
# Health check
curl http://localhost:8002/

# Test query
curl -X POST "http://localhost:8002/query/graphrag" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key_here" \
  -d '{
    "query": "What are the main topics in the documents?",
    "k": 20,
    "use_cache": true
  }'
```

**Success response**:
```json
{
  "query": "What are the main topics...",
  "answer": "...",
  "total_time": 1.234,
  "cached": false,
  "cache_stats": {
    "enabled": true,
    "hit_rate": 0.0
  }
}
```

---

## 📋 Detailed Configuration

### Required API Keys Explained

#### 1. Qdrant (Vector Database)
```bash
QDRANT_URL=https://qdrant.api.blaiq.ai
QDRANT_API_KEY=your_key_here
```

**Where to get**:
- **Cloud**: https://cloud.qdrant.io/ (free tier available)
- **Self-hosted**: Run your own Qdrant instance
- **Existing**: You already have `https://qdrant.api.blaiq.ai`

**Test connection**:
```bash
curl -H "api-key: YOUR_KEY" https://qdrant.api.blaiq.ai/collections
```

---

#### 2. OpenAI (LLM Provider)
```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

**Where to get**:
- **OpenAI**: https://platform.openai.com/api-keys
- **Azure OpenAI**: Use Azure endpoint + key
- **Compatible providers**: Groq, Together AI, etc.

**Test connection**:
```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer YOUR_KEY"
```

**Cost optimization**:
- Use `gpt-4o-mini` for lower costs (~$0.15/1M tokens)
- Use `gpt-4o` for better quality (~$2.50/1M tokens)

---

#### 3. Neo4j (Optional - Graph Features)
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

**Where to get**:
- **Cloud**: https://neo4j.com/cloud/aura/ (free tier)
- **Self-hosted**: Run Neo4j container (see below)
- **Existing**: You already have a Neo4j instance

**If you don't have Neo4j**:
```bash
# The system will work WITHOUT Neo4j
# Graph features will be disabled, but vector + keyword search still work
```

---

### Optional: Run with Neo4j

If you want graph features, add Neo4j to your setup:

```bash
# Start Neo4j alongside GraphRAG
docker run -d \
  --name graphrag-neo4j \
  --network graphrag-optimized_graphrag-optimized \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5.15-community

# Update .env
NEO4J_URI=bolt://graphrag-neo4j:7687
NEO4J_PASSWORD=your_password

# Restart GraphRAG
docker-compose -f docker-compose.optimized.yml restart graphrag-optimized
```

---

## 🔧 Service Ports

| Service | Port | URL |
|---------|------|-----|
| **Optimized GraphRAG API** | 8002 | http://localhost:8002 |
| **Redis Cache** | 6380 | redis://localhost:6380 |
| **Neo4j Browser** (optional) | 7474 | http://localhost:7474 |
| **Neo4j Bolt** (optional) | 7687 | bolt://localhost:7687 |

**Note**: Using port 8002 to avoid conflicts with existing GraphRAG API on 8001

---

## 📊 Monitoring

### Check Cache Statistics
```bash
curl http://localhost:8002/cache/stats
```

Response:
```json
{
  "enabled": true,
  "connected": true,
  "hits": 42,
  "misses": 18,
  "hit_rate": 0.7,
  "ttl": 3600
}
```

### Check Service Health
```bash
curl http://localhost:8002/
```

### View Logs
```bash
# All services
docker-compose -f docker-compose.optimized.yml logs -f

# Just GraphRAG
docker-compose -f docker-compose.optimized.yml logs -f graphrag-optimized

# Just Redis
docker-compose -f docker-compose.optimized.yml logs -f redis
```

---

## 🛠️ Common Operations

### Clear Cache
```bash
curl -X POST http://localhost:8002/cache/clear
```

### Restart Services
```bash
docker-compose -f docker-compose.optimized.yml restart
```

### Stop Services
```bash
docker-compose -f docker-compose.optimized.yml down
```

### Stop and Remove Data
```bash
docker-compose -f docker-compose.optimized.yml down -v
```

### Update Code
```bash
# Rebuild after code changes
docker-compose -f docker-compose.optimized.yml build --no-cache
docker-compose -f docker-compose.optimized.yml up -d
```

---

## 🔐 Security Best Practices

### 1. Secure API Key
```bash
# Generate strong API key
openssl rand -hex 32

# Add to .env
API_KEY=your_generated_key_here
```

### 2. Use in Requests
```bash
curl -X POST "http://localhost:8002/query/graphrag" \
  -H "X-API-Key: your_generated_key_here" \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
```

### 3. Don't Commit .env
```bash
# .env is in .gitignore by default
# Never commit API keys to git!
```

---

## 🐛 Troubleshooting

### Issue: "Redis connection failed"
**Solution**:
```bash
# Check Redis is running
docker ps | grep redis

# Check Redis logs
docker logs graphrag-redis-optimized

# Test Redis connection
docker exec graphrag-redis-optimized redis-cli ping
# Should return: PONG
```

---

### Issue: "Qdrant connection failed"
**Solution**:
```bash
# Verify QDRANT_URL in .env
echo $QDRANT_URL

# Test connection
curl -H "api-key: $QDRANT_API_KEY" $QDRANT_URL/collections

# Check if collection exists
curl -H "api-key: $QDRANT_API_KEY" $QDRANT_URL/collections/graphrag_chunks
```

---

### Issue: "OpenAI API error"
**Solution**:
```bash
# Verify API key
echo $OPENAI_API_KEY

# Test API
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Check quota
# Visit: https://platform.openai.com/usage
```

---

### Issue: "Neo4j connection failed"
**This is OK!** Neo4j is optional. The system will work without it.

If you want graph features:
```bash
# Check Neo4j is running
docker ps | grep neo4j

# Check logs
docker logs graphrag-neo4j

# Verify password in .env matches Neo4j
```

---

## 📈 Performance Tuning

### Increase Cache TTL
```bash
# In .env
CACHE_TTL=7200  # 2 hours instead of 1
```

### Adjust Resource Limits
Edit `docker-compose.optimized.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 8G
```

### Scale Horizontally
```bash
# Run multiple instances
docker-compose -f docker-compose.optimized.yml up -d --scale graphrag-optimized=3
```

---

## 🔄 Integration with Existing Setup

Your existing GraphRAG runs on port **8001**.  
The optimized version runs on port **8002**.

**You can run both simultaneously**:
- Original API: `http://localhost:8001`
- Optimized API: `http://localhost:8002`

**To migrate**:
1. Test optimized API on port 8002
2. Verify performance improvements
3. Update your applications to use port 8002
4. Eventually deprecate port 8001

---

## 📞 Support Checklist

Before asking for help, check:
- [ ] `.env` file exists and has all required keys
- [ ] Redis is running: `docker ps | grep redis`
- [ ] Qdrant is accessible: `curl $QDRANT_URL/collections`
- [ ] OpenAI key is valid: `curl https://api.openai.com/v1/models`
- [ ] Logs show no errors: `docker-compose logs graphrag-optimized`

---

## 🎯 Next Steps

1. **Test with your data**: Upload documents to Qdrant
2. **Monitor cache hit rate**: Aim for >40%
3. **Benchmark performance**: Run `benchmark_performance.py`
4. **Set up monitoring**: Add Prometheus/Grafana (optional)
5. **Scale as needed**: Add more instances behind load balancer

---

**Questions?** See:
- `IMPLEMENTATION_SUMMARY.md` - What was built
- `OPTIMIZATION_GUIDE.md` - Detailed usage
- `ARCHITECTURE.md` - System design
