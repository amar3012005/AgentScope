#!/bin/bash

echo "======================================"
echo "GraphRAG System Health Check"
echo "======================================"

# 1. Docker Status
echo -e "\n📦 DOCKER CONTAINERS"
echo "────────────────────────────────────"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "NAME|graphrag"

# 2. Configuration Check
echo -e "\n⚙️  CONFIGURATION"
echo "────────────────────────────────────"

echo "Qdrant config in config.prod.yaml:"
grep -A 3 "^qdrant:" config.prod.yaml | head -4

# 3. Environment Variables
echo -e "\n🔐 ENVIRONMENT VARIABLES"
echo "────────────────────────────────────"
echo "QDRANT_URL: $(grep QDRANT_URL .env | cut -d= -f2)"
echo "QDRANT_API_KEY: $(grep QDRANT_API_KEY .env | cut -d= -f2 | head -c 10)..."
echo "OPENAI_API_KEY: $(grep OPENAI_API_KEY .env | cut -d= -f2 | head -c 10)..."

# 4. API Health Checks
echo -e "\n🏥 API HEALTH"
echo "────────────────────────────────────"

# Pipeline API
echo "Testing Pipeline API..."
PIPELINE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/)
if [ "$PIPELINE_RESPONSE" = "200" ]; then
    echo "✅ Pipeline API: Healthy (HTTP 200)"
    curl -s http://localhost:8000/ | jq -r '.status, .service'
else
    echo "❌ Pipeline API: Error (HTTP $PIPELINE_RESPONSE)"
fi

# Retriever API
echo -e "\nTesting Retriever API..."
RETRIEVER_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/)
if [ "$RETRIEVER_RESPONSE" = "200" ]; then
    echo "✅ Retriever API: Healthy (HTTP 200)"
    curl -s http://localhost:8001/ | jq -r '.status, .mode'
    
    # Detailed status
    echo -e "\nDetailed Status:"
    curl -s http://localhost:8001/status | jq '.'
else
    echo "❌ Retriever API: Error (HTTP $RETRIEVER_RESPONSE)"
    curl -s http://localhost:8001/ 2>&1
fi

# 5. Recent Logs
echo -e "\n📋 RECENT LOGS"
echo "────────────────────────────────────"

echo "Pipeline (last 10 lines):"
docker logs --tail 10 graphrag-pipeline 2>&1

echo -e "\nRetriever (last 10 lines):"
docker logs --tail 10 graphrag-retriever 2>&1

# 6. Look for specific errors
echo -e "\n🔍 ERROR DETECTION"
echo "────────────────────────────────────"

RETRIEVER_ERRORS=$(docker logs graphrag-retriever 2>&1 | grep -i "failed to initialize\|error\|exception" | tail -3)
if [ -z "$RETRIEVER_ERRORS" ]; then
    echo "✅ No critical errors in retriever"
else
    echo "❌ Retriever errors found:"
    echo "$RETRIEVER_ERRORS"
fi

echo -e "\n======================================"
echo "SUMMARY"
echo "======================================"

if [ "$PIPELINE_RESPONSE" = "200" ] && [ "$RETRIEVER_RESPONSE" = "200" ]; then
    echo "✅ System Status: READY"
    echo ""
    echo "You can now:"
    echo "  1. Process documents via Pipeline API (port 8000)"
    echo "  2. Query documents via Retriever API (port 8001)"
else
    echo "❌ System Status: NOT READY"
    [ "$PIPELINE_RESPONSE" != "200" ] && echo "  - Pipeline API: DOWN"
    [ "$RETRIEVER_RESPONSE" != "200" ] && echo "  - Retriever API: DOWN"
fi
