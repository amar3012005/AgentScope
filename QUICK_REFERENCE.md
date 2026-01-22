# GraphRAG Optimized - Quick Reference Card

## 🚀 One-Command Setup

```bash
# 1. Configure
cp .env.example .env && nano .env

# 2. Start
docker-compose -f docker-compose.optimized.yml up -d

# 3. Test
curl http://localhost:8002/
```

---

## 🔑 Required API Keys

| Key | Where to Get | Purpose |
|-----|--------------|---------|
| **QDRANT_URL** | https://cloud.qdrant.io/ | Vector database |
| **QDRANT_API_KEY** | Qdrant dashboard | Authentication |
| **OPENAI_API_KEY** | https://platform.openai.com/api-keys | LLM operations |

**Optional**:
- **NEO4J_PASSWORD** - For graph features (system works without it)
- **API_KEY** - For securing your API endpoints

---

## 📡 Service Endpoints

| Service | Port | URL |
|---------|------|-----|
| GraphRAG API | 8002 | http://localhost:8002 |
| Cache Stats | 8002 | http://localhost:8002/cache/stats |
| Redis | 6380 | redis://localhost:6380 |

---

## 🧪 Test Query

```bash
curl -X POST "http://localhost:8002/query/graphrag" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{
    "query": "What are the main topics?",
    "k": 20,
    "use_cache": true
  }'
```

---

## 🛠️ Common Commands

```bash
# View logs
docker-compose -f docker-compose.optimized.yml logs -f

# Restart
docker-compose -f docker-compose.optimized.yml restart

# Stop
docker-compose -f docker-compose.optimized.yml down

# Clear cache
curl -X POST http://localhost:8002/cache/clear

# Check cache stats
curl http://localhost:8002/cache/stats
```

---

## ⚡ Performance Expectations

| Scenario | Response Time |
|----------|---------------|
| Cache Hit | <100ms ✅ |
| Cache Miss | 1-2s ✅ |
| Original System | 5-10s ❌ |

**Speedup**: 5x faster on average

---

## 🐛 Quick Troubleshooting

**Redis not working?**
```bash
docker logs graphrag-redis-optimized
docker exec graphrag-redis-optimized redis-cli ping
```

**Qdrant not connecting?**
```bash
curl -H "api-key: $QDRANT_API_KEY" $QDRANT_URL/collections
```

**OpenAI errors?**
```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

---

## 📚 Full Documentation

- **DOCKER_GUIDE.md** - Complete deployment guide
- **IMPLEMENTATION_SUMMARY.md** - What was built
- **OPTIMIZATION_GUIDE.md** - Detailed usage
- **ARCHITECTURE.md** - System design

---

## 🎯 Minimum .env Configuration

```bash
# Copy this to .env and fill in your values
QDRANT_URL=https://qdrant.api.blaiq.ai
QDRANT_API_KEY=your_qdrant_key
OPENAI_API_KEY=your_openai_key
```

That's it! System will work with just these 3 keys.
