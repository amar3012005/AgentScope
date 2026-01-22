#!/bin/bash

# GraphRAG Optimization Quick Start Script
# This script helps you get the optimized GraphRAG system running quickly

set -e

echo "=========================================="
echo "GraphRAG Optimization - Quick Start"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Redis is running
echo -e "${YELLOW}[1/5] Checking Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis is running${NC}"
else
    echo -e "${RED}❌ Redis is not running${NC}"
    echo ""
    echo "Starting Redis with Docker..."
    docker run -d --name graphrag-redis -p 6379:6379 redis:7-alpine
    echo -e "${GREEN}✅ Redis started${NC}"
fi
echo ""

# Check environment variables
echo -e "${YELLOW}[2/5] Checking environment variables...${NC}"

if [ -z "$QDRANT_URL" ] && [ -z "$QDRANT_HOST" ]; then
    echo -e "${RED}⚠️  QDRANT_URL or QDRANT_HOST not set${NC}"
    echo "Please set one of these environment variables:"
    echo "  export QDRANT_URL=https://your-qdrant-instance"
    echo "  OR"
    echo "  export QDRANT_HOST=localhost"
    echo "  export QDRANT_PORT=6333"
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}⚠️  OPENAI_API_KEY not set${NC}"
    echo "Please set: export OPENAI_API_KEY=your_key"
fi

if [ -z "$NEO4J_PASSWORD" ]; then
    echo -e "${YELLOW}⚠️  NEO4J_PASSWORD not set (graph features will be disabled)${NC}"
fi

# Set default cache settings if not set
export REDIS_URL=${REDIS_URL:-"redis://localhost:6379"}
export ENABLE_CACHE=${ENABLE_CACHE:-"true"}
export CACHE_TTL=${CACHE_TTL:-"3600"}

echo -e "${GREEN}✅ Environment configured${NC}"
echo "   REDIS_URL: $REDIS_URL"
echo "   ENABLE_CACHE: $ENABLE_CACHE"
echo "   CACHE_TTL: $CACHE_TTL"
echo ""

# Check Python dependencies
echo -e "${YELLOW}[3/5] Checking Python dependencies...${NC}"
if python3 -c "import redis.asyncio; import qdrant_client" 2>/dev/null; then
    echo -e "${GREEN}✅ Core dependencies installed${NC}"
else
    echo -e "${RED}❌ Missing dependencies${NC}"
    echo "Installing with uv..."
    uv pip install redis qdrant-client
fi
echo ""

# Show available scripts
echo -e "${YELLOW}[4/5] Available commands:${NC}"
echo ""
echo "  ${GREEN}1. Start Optimized API:${NC}"
echo "     python src/retriever/retriever_api_optimized.py"
echo ""
echo "  ${GREEN}2. Run Performance Benchmark:${NC}"
echo "     python benchmark_performance.py"
echo ""
echo "  ${GREEN}3. Check Cache Statistics:${NC}"
echo "     curl http://localhost:8001/cache/stats"
echo ""
echo "  ${GREEN}4. Clear Cache:${NC}"
echo "     curl -X POST http://localhost:8001/cache/clear"
echo ""

# Offer to start the API
echo -e "${YELLOW}[5/5] Ready to start!${NC}"
echo ""
read -p "Start the optimized API now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Starting optimized GraphRAG API...${NC}"
    echo ""
    python src/retriever/retriever_api_optimized.py
else
    echo ""
    echo "To start manually, run:"
    echo "  python src/retriever/retriever_api_optimized.py"
    echo ""
fi

echo ""
echo "=========================================="
echo "For more information, see:"
echo "  - IMPLEMENTATION_SUMMARY.md"
echo "  - OPTIMIZATION_GUIDE.md"
echo "=========================================="
