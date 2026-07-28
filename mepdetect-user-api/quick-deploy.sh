#!/bin/bash

# Quick Deploy MEPdetect User Management
# For existing server with MEPdetect services running

set -e

echo "🚀 MEPdetect User API - Quick Deploy"
echo "====================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run with sudo${NC}"
    exit 1
fi

# Configuration
DEPLOY_DIR="/opt/mepdetect-user-api"
SOURCE_DIR="/mnt/user-data/outputs/mepdetect-user-management"

echo -e "${BLUE}📁 Creating deployment directory...${NC}"
mkdir -p $DEPLOY_DIR
cd $DEPLOY_DIR

echo -e "${BLUE}📋 Copying files...${NC}"
if [ -d "$SOURCE_DIR" ]; then
    cp $SOURCE_DIR/*.py .
    cp $SOURCE_DIR/*.txt .
    cp $SOURCE_DIR/.env .
    cp $SOURCE_DIR/*.html .
    echo -e "${GREEN}✓ Files copied${NC}"
else
    echo -e "${RED}✗ Source directory not found. Please ensure files are in $SOURCE_DIR${NC}"
    exit 1
fi

# Create Dockerfile
echo -e "${BLUE}🐳 Creating Dockerfile...${NC}"
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

COPY requirements-user-api.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

CMD ["uvicorn", "user_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
EOF

echo -e "${GREEN}✓ Dockerfile created${NC}"

# Install PostgreSQL if not installed
echo -e "${BLUE}🗄️  Checking PostgreSQL...${NC}"
if ! command -v psql &> /dev/null; then
    echo "Installing PostgreSQL..."
    apt update
    apt install -y postgresql postgresql-contrib
    systemctl start postgresql
    systemctl enable postgresql
    echo -e "${GREEN}✓ PostgreSQL installed${NC}"
else
    echo -e "${GREEN}✓ PostgreSQL already installed${NC}"
fi

# Create database
echo -e "${BLUE}💾 Setting up database...${NC}"
sudo -u postgres psql << EOF 2>/dev/null || echo "Database might already exist"
CREATE DATABASE mepdetect;
CREATE USER mepdetect WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE mepdetect TO mepdetect;
ALTER DATABASE mepdetect OWNER TO mepdetect;
EOF

echo -e "${GREEN}✓ Database configured${NC}"

# Build Docker image
echo -e "${BLUE}🔨 Building Docker image...${NC}"
docker build -t mepdetect-user-api .
echo -e "${GREEN}✓ Image built${NC}"

# Stop existing container if running
echo -e "${BLUE}🔄 Stopping existing container...${NC}"
docker stop mepdetect-user-api 2>/dev/null || true
docker rm mepdetect-user-api 2>/dev/null || true

# Run container
echo -e "${BLUE}🚀 Starting User API container...${NC}"
docker run -d \
  --name mepdetect-user-api \
  --network host \
  -p 8093:8000 \
  -v $DEPLOY_DIR/.env:/app/.env:ro \
  -e DATABASE_URL=postgresql://mepdetect:CHANGE_ME@localhost:5432/mepdetect \
  -e REDIS_URL=redis://localhost:6379 \
  -e RECAPTCHA_SECRET_KEY=YOUR_RECAPTCHA_SECRET_KEY \
  -e RECAPTCHA_SITE_KEY=YOUR_RECAPTCHA_SITE_KEY \
  -e SECRET_KEY=YOUR_SECRET_KEY \
  --restart unless-stopped \
  mepdetect-user-api

echo -e "${GREEN}✓ Container started${NC}"

# Wait for service to be ready
echo -e "${BLUE}⏳ Waiting for service to be ready...${NC}"
sleep 5

# Check if running
if curl -s http://localhost:8093/docs > /dev/null; then
    echo -e "${GREEN}✓ User API is running!${NC}"
else
    echo -e "${RED}✗ Service failed to start. Check logs:${NC}"
    echo "docker logs mepdetect-user-api"
    exit 1
fi

# Create admin user
echo ""
echo -e "${BLUE}👤 Creating admin user...${NC}"
read -p "Create admin user now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker exec -it mepdetect-user-api python admin_tools.py create-admin
fi

echo ""
echo "========================================="
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo "========================================="
echo ""
echo "Services running:"
echo "  User API:    http://localhost:8093"
echo "  API Docs:    http://localhost:8093/docs"
echo "  Detection:   http://localhost:8091"
echo "  Training:    http://localhost:8092"
echo "  Landing:     http://localhost:8090"
echo ""
echo "Database:"
echo "  PostgreSQL:  localhost:5432/mepdetect"
echo "  Redis:       localhost:6379 (shared)"
echo ""
echo "Next steps:"
echo "  1. Update Stripe keys in .env"
echo "  2. Visit http://localhost:8090/login.html"
echo "  3. Test registration with reCAPTCHA"
echo "  4. Create admin user if not done above"
echo ""
echo "Logs:"
echo "  docker logs -f mepdetect-user-api"
echo ""
echo -e "${GREEN}All done! 🚀${NC}"
