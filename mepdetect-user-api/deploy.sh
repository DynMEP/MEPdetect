#!/bin/bash

# MEPdetect Complete Platform Deployment Script
# Deploys: User Management API, Detection API, Training API, Landing Page, Database

set -e  # Exit on error

echo "🚀 MEPdetect Platform Deployment"
echo "================================"

# Configuration
USER_API_DIR="/opt/mepdetect-user-api"
DETECTION_API_DIR="/opt/mepdetect-api"
TRAINING_API_DIR="/opt/mepdetect-training"
LANDING_DIR="/opt/mepdetect-landing"
SHARED_MODELS="/opt/mepdetect-shared/models"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run with sudo"
    exit 1
fi

# Step 1: Create directories
print_step "Creating directory structure..."
mkdir -p $USER_API_DIR
mkdir -p $DETECTION_API_DIR
mkdir -p $TRAINING_API_DIR
mkdir -p $LANDING_DIR
mkdir -p $SHARED_MODELS
mkdir -p /opt/mepdetect-data/{uploads,results,datasets}
print_success "Directories created"

# Step 2: Install system dependencies
print_step "Installing system dependencies..."
apt-get update
apt-get install -y \
    docker.io \
    docker-compose \
    postgresql-client \
    nginx \
    certbot \
    python3-certbot-nginx
print_success "System dependencies installed"

# Step 3: Copy files to user API directory
print_step "Setting up User Management API..."
cp db_models.py $USER_API_DIR/
cp auth.py $USER_API_DIR/
cp user_api.py $USER_API_DIR/main.py
cp requirements-user-api.txt $USER_API_DIR/requirements.txt

# Create Dockerfile for User API
cat > $USER_API_DIR/Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# Run application
CMD ["uvicorn", "user_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
EOF

print_success "User API configured"

# Step 4: Create environment file
print_step "Creating environment configuration..."
cat > $USER_API_DIR/.env << EOF
DATABASE_URL=postgresql://mepdetect:CHANGE_ME@localhost/mepdetect
REDIS_URL=redis://localhost:6379
SECRET_KEY=$(openssl rand -hex 32)
STRIPE_API_KEY=YOUR_STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET=whsec_your_secret_here
RECAPTCHA_SECRET_KEY=6Lexample_recaptcha_secret_key_here
ENVIRONMENT=production
EOF
print_success "Environment configured"

# Step 5: Initialize PostgreSQL
print_step "Setting up PostgreSQL database..."
sudo -u postgres psql -c "CREATE DATABASE mepdetect;" 2>/dev/null || echo "Database already exists"
sudo -u postgres psql -c "CREATE USER mepdetect WITH PASSWORD 'CHANGE_ME';" 2>/dev/null || echo "User already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE mepdetect TO mepdetect;"
print_success "Database configured"

# Step 6: Create docker-compose file
print_step "Creating docker-compose configuration..."
cp docker-compose-full.yml /opt/mepdetect/docker-compose.yml
cd /opt/mepdetect
print_success "Docker compose configured"

# Step 7: Build and start services
print_step "Building Docker containers..."
docker-compose build
print_success "Containers built"

print_step "Starting services..."
docker-compose up -d
print_success "Services started"

# Step 8: Wait for services to be healthy
print_step "Waiting for services to be ready..."
sleep 10

# Check service health
services=(
    "localhost:8090:Landing Page"
    "localhost:8091:Detection API"
    "localhost:8092:Training API"
    "localhost:8093:User API"
)

for service in "${services[@]}"; do
    IFS=':' read -r host port name <<< "$service"
    if curl -s "http://${host}:${port}/health" > /dev/null 2>&1 || \
       curl -s "http://${host}:${port}/" > /dev/null 2>&1; then
        print_success "${name} is running on port ${port}"
    else
        print_error "${name} failed to start on port ${port}"
    fi
done

# Step 9: Setup Nginx reverse proxy (optional)
read -p "Setup Nginx reverse proxy? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_step "Configuring Nginx..."
    
    cat > /etc/nginx/sites-available/mepdetect << 'EOF'
server {
    listen 80;
    server_name mepdetect.com www.mepdetect.com;

    location / {
        proxy_pass http://localhost:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /api/ {
        proxy_pass http://localhost:8091/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /auth/ {
        proxy_pass http://localhost:8093/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/mepdetect /etc/nginx/sites-enabled/
    nginx -t && systemctl restart nginx
    print_success "Nginx configured"
fi

# Step 10: Display summary
echo ""
echo "================================"
echo "🎉 Deployment Complete!"
echo "================================"
echo ""
echo "Services running on:"
echo "  Landing Page:    http://localhost:8090"
echo "  User API:        http://localhost:8093"
echo "  Detection API:   http://localhost:8091"
echo "  Training API:    http://localhost:8092"
echo "  PostgreSQL:      localhost:5432"
echo "  Redis:           localhost:6379"
echo ""
echo "Next steps:"
echo "  1. Update Stripe keys in $USER_API_DIR/.env"
echo "  2. Setup reCAPTCHA at https://www.google.com/recaptcha/admin"
echo "  3. Update reCAPTCHA keys in .env and login.html"
echo "  4. Configure domain in Nginx"
echo "  5. Setup SSL with: certbot --nginx -d mepdetect.com"
echo "  6. Create admin user via API"
echo ""
echo "See RECAPTCHA_SETUP.md for detailed reCAPTCHA configuration"
echo ""
echo "Logs:"
echo "  docker-compose logs -f user-api"
echo "  docker-compose logs -f detection-api"
echo ""
print_success "All done! 🚀"
