#!/bin/bash

# Deploy GraphRAG Optimized to Coolify
# Service ID: e0cwcccswckc8okk4k00skck

set -e

SERVICE_ID="e0cwcccswckc8okk4k00skck"
SERVICE_DIR="/data/coolify/services/${SERVICE_ID}"
APP_DIR="${SERVICE_DIR}/graphrag-optimized"

echo "🚀 Deploying GraphRAG Optimized to Coolify"
echo "Service ID: ${SERVICE_ID}"
echo "Service Directory: ${SERVICE_DIR}"
echo ""

# Step 1: Create application directory
echo "📁 Step 1: Creating application directory..."
mkdir -p "${APP_DIR}"

# Step 2: Copy application files
echo "📦 Step 2: Copying application files..."
rsync -av --exclude='.git' \
          --exclude='__pycache__' \
          --exclude='*.pyc' \
          --exclude='.venv' \
          --exclude='node_modules' \
          --exclude='data' \
          --exclude='logs' \
          /root/blaiq/ "${APP_DIR}/"

# Step 3: Copy docker-compose.yml
echo "🐳 Step 3: Setting up docker-compose.yml..."
cp /root/blaiq/docker-compose.coolify.yml "${SERVICE_DIR}/docker-compose.yml"

# Step 4: Copy .env file
echo "🔐 Step 4: Copying environment variables..."
if [ -f "${SERVICE_DIR}/.env" ]; then
    echo "⚠️  .env already exists, creating backup..."
    cp "${SERVICE_DIR}/.env" "${SERVICE_DIR}/.env.backup.$(date +%Y%m%d_%H%M%S)"
fi
cp /root/blaiq/.env "${SERVICE_DIR}/.env"

# Step 5: Create necessary directories
echo "📂 Step 5: Creating data directories..."
mkdir -p "${APP_DIR}/data"
mkdir -p "${APP_DIR}/logs"
chmod -R 755 "${APP_DIR}"

# Step 6: Build the service
echo "🔨 Step 6: Building Docker images..."
cd "${SERVICE_DIR}"
docker compose build

# Step 7: Start the service
echo "▶️  Step 7: Starting services..."
docker compose up -d

# Step 8: Wait for services to be healthy
echo "⏳ Step 8: Waiting for services to be healthy..."
sleep 10

# Step 9: Check service status
echo "✅ Step 9: Checking service status..."
docker compose ps

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📊 Service Information:"
echo "  - GraphRAG API: http://localhost:8445"
echo "  - Redis: Internal only (redis:6379)"
echo ""
echo "🔍 Useful commands:"
echo "  - View logs: docker compose -f ${SERVICE_DIR}/docker-compose.yml logs -f"
echo "  - Check status: docker compose -f ${SERVICE_DIR}/docker-compose.yml ps"
echo "  - Restart: docker compose -f ${SERVICE_DIR}/docker-compose.yml restart"
echo "  - Stop: docker compose -f ${SERVICE_DIR}/docker-compose.yml down"
echo ""
echo "🧪 Test the API:"
echo "  curl http://localhost:8445/"
echo ""
