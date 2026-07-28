# MEPdetect Integration with Existing Infrastructure

Your server is already running several services. Here's how to add MEPdetect user management without conflicts.

## 🏗️ Current Infrastructure

```
Port 5000:  Bitcoin Gift Card Frontend (mainnet)
Port 5001:  Bitcoin Gift Card Backend (mainnet)
Port 5002:  Bitcoin Gift Card Admin (localhost only)
Port 6000:  Bitcoin Gift Card Frontend (testnet)
Port 6001:  Bitcoin Gift Card Backend (testnet)
Port 6002:  Bitcoin Gift Card Admin (testnet, localhost only)
Port 3307:  MariaDB (wady-db)
Port 3308:  MariaDB (testnet-db)
Port 6379:  Redis (wady-redis) ✅ REUSE THIS
Port 6380:  Redis (testnet-redis)
Port 8090:  MEPdetect Landing Page ✅ RUNNING
Port 8091:  MEPdetect Detection API ✅ RUNNING
Port 8092:  MEPdetect Training API ✅ RUNNING
Port 8333:  Bitcoin Mainnet Node
Port 18333: Bitcoin Testnet Node
```

## ✅ Available Resources to Reuse

### 1. Redis (Port 6379)
**Already running!** Update .env to use existing Redis:
```bash
REDIS_URL=redis://wady-redis:6379
# Or if different network:
REDIS_URL=redis://localhost:6379
```

### 2. reCAPTCHA Keys
**Already configured!** Your existing keys work perfectly:
```bash
RECAPTCHA_SITE_KEY=YOUR_RECAPTCHA_SITE_KEY
RECAPTCHA_SECRET_KEY=YOUR_RECAPTCHA_SECRET_KEY
```

**✅ Already updated in login.html and .env**

### 3. Secrets
**Reusing existing secure keys** where appropriate.

## 🚀 Quick Deployment (Using Available Port 8093)

### Step 1: Install PostgreSQL (Only New Service Needed)

```bash
# Install PostgreSQL
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Start service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database
sudo -u postgres psql << EOF
CREATE DATABASE mepdetect;
CREATE USER mepdetect WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE mepdetect TO mepdetect;
\q
EOF
```

### Step 2: Deploy User API

```bash
# Create directory
sudo mkdir -p /opt/mepdetect-user-api
cd /opt/mepdetect-user-api

# Copy files from upload
# (Files are in /mnt/user-data/outputs/mepdetect-user-management/)

# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

COPY requirements-user-api.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "user_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
EOF

# Build image
docker build -t mepdetect-user-api .

# Run container (Port 8093 - FREE!)
docker run -d \
  --name mepdetect-user-api \
  --network mepdetect-frontend-mepdetect-network \
  -p 8093:8000 \
  -e DATABASE_URL=postgresql://mepdetect:CHANGE_ME@host.docker.internal:5432/mepdetect \
  -e REDIS_URL=redis://wady-redis:6379 \
  -e RECAPTCHA_SECRET_KEY=YOUR_RECAPTCHA_SECRET_KEY \
  -e RECAPTCHA_SITE_KEY=YOUR_RECAPTCHA_SITE_KEY \
  -e SECRET_KEY=YOUR_SECRET_KEY \
  --restart unless-stopped \
  mepdetect-user-api
```

### Step 3: Connect to Existing Network

```bash
# Option A: Connect to MEPdetect network
docker network connect mepdetect-frontend-mepdetect-network mepdetect-user-api

# Option B: Use host networking
docker stop mepdetect-user-api
docker rm mepdetect-user-api
docker run -d \
  --name mepdetect-user-api \
  --network host \
  -e DATABASE_URL=postgresql://mepdetect:CHANGE_ME@localhost:5432/mepdetect \
  -e REDIS_URL=redis://localhost:6379 \
  --env-file .env \
  --restart unless-stopped \
  mepdetect-user-api
```

### Step 4: Create Admin User

```bash
# Copy admin tools
docker cp admin_tools.py mepdetect-user-api:/app/
docker cp db_models.py mepdetect-user-api:/app/
docker cp auth.py mepdetect-user-api:/app/

# Create admin
docker exec -it mepdetect-user-api python admin_tools.py create-admin

# Or manually:
docker exec -it mepdetect-user-api python << EOF
from user_api import *
db = SessionLocal()
admin = User(
    email="admin@mepdetect.com",
    hashed_password=hash_password("CHANGE_ME"),
    full_name="Admin User",
    role=UserRole.ADMIN,
    is_active=True,
    api_key=generate_api_key(),
    api_calls_limit=999999
)
db.add(admin)
db.commit()
print(f"✅ Admin created: {admin.email}")
EOF
```

### Step 5: Update Nginx (If Using)

```bash
# Add to your existing nginx config
sudo nano /etc/nginx/sites-available/mepdetect

# Add this location block:
location /auth/ {
    proxy_pass http://localhost:8093/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

location /api/user/ {
    proxy_pass http://localhost:8093/user/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

# Reload nginx
sudo nginx -t && sudo systemctl reload nginx
```

## 📋 Port Allocation Summary

```
✅ 8093: MEPdetect User API (NEW - Available)
✅ 8092: MEPdetect Training API (Running)
✅ 8091: MEPdetect Detection API (Running)
✅ 8090: MEPdetect Landing Page (Running)
✅ 6379: Redis (REUSED from wady-redis)
✅ 5432: PostgreSQL (NEW - Standard port)
```

## 🔗 Service Integration

### Connect Detection API to User Auth

Update your detection API (`main.py` on port 8091):

```python
import httpx

async def verify_token(authorization: str):
    """Verify JWT with user API"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'http://localhost:8093/user/profile',
            headers={'Authorization': authorization}
        )
        return response.json() if response.status_code == 200 else None

@app.post("/detect")
async def detect(
    file: UploadFile,
    authorization: str = Header(None)
):
    # Verify user
    user = await verify_token(authorization)
    if not user:
        raise HTTPException(401, "Not authenticated")
    
    # Check limits
    if user['api_calls_count'] >= user['api_calls_limit']:
        raise HTTPException(429, "API limit exceeded")
    
    # Your existing detection code...
    # After detection, log usage:
    await log_usage(user['id'], detections_count)
```

## 🧪 Testing

```bash
# 1. Check all services
docker ps | grep mepdetect

# Should show:
# - mepdetect-user-api (port 8093)
# - mepdetect-backend (port 8091)
# - mepdetect-training (port 8092)
# - mepdetect-landing (port 8090)

# 2. Test user API
curl http://localhost:8093/docs  # API documentation

# 3. Register user
curl -X POST http://localhost:8093/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@mepdetect.com",
    "password": "testpass123",
    "full_name": "Test User",
    "recaptcha_token": "test_token"
  }'

# Note: For testing, you can disable reCAPTCHA:
docker exec mepdetect-user-api bash -c "export RECAPTCHA_ENABLED=false"
```

## 🔐 Security Checklist

- [x] reCAPTCHA configured with existing keys
- [x] Redis reusing existing secure instance
- [x] Separate database (PostgreSQL) for isolation
- [x] JWT secret key from existing secure config
- [x] API on different port (8093) - no conflicts
- [ ] Update Stripe keys for production
- [ ] Configure SSL/TLS for 8093
- [ ] Set up database backups
- [ ] Configure firewall rules

## 📊 Resource Usage

**New Services:**
- PostgreSQL: ~50MB RAM
- User API: ~100-200MB RAM

**Reused Services:**
- Redis (existing)
- Nginx (existing, just add proxy rules)

**Total Additional Load:** ~150-250MB RAM

## 🔄 Docker Compose Option

If you prefer docker-compose, add to existing compose file:

```yaml
services:
  mepdetect-postgres:
    image: postgres:15-alpine
    container_name: mepdetect-postgres
    environment:
      POSTGRES_DB: mepdetect
      POSTGRES_USER: mepdetect
      POSTGRES_PASSWORD: CHANGE_ME
    ports:
      - "5432:5432"
    volumes:
      - mepdetect-postgres-data:/var/lib/postgresql/data
    networks:
      - mepdetect-network

  mepdetect-user-api:
    build: /opt/mepdetect-user-api
    container_name: mepdetect-user-api
    depends_on:
      - mepdetect-postgres
    ports:
      - "8093:8000"
    environment:
      - DATABASE_URL=postgresql://mepdetect:CHANGE_ME@mepdetect-postgres:5432/mepdetect
      - REDIS_URL=redis://wady-redis:6379
    env_file:
      - /opt/mepdetect-user-api/.env
    networks:
      - mepdetect-network
    restart: unless-stopped

volumes:
  mepdetect-postgres-data:

networks:
  mepdetect-network:
    external: true
```

## ✅ Complete!

Your MEPdetect platform now has:
- ✅ User authentication (JWT)
- ✅ Subscription management (Stripe)
- ✅ API key system
- ✅ Admin dashboard
- ✅ reCAPTCHA protection
- ✅ Usage tracking
- ✅ No port conflicts
- ✅ Shared Redis cache
- ✅ Isolated database

Access at:
- User API: http://localhost:8093
- Login: http://localhost:8090/login.html
- Dashboard: http://localhost:8090/dashboard.html
- Admin: http://localhost:8090/admin.html
