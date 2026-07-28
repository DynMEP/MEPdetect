# MEPdetect User Management System

Complete user authentication, subscription, and admin management for MEPdetect platform.

## 🏗️ Architecture

### Services

1. **User Management API** (Port 8093)
   - User registration & authentication
   - Subscription management
   - Order processing
   - Admin panel APIs
   - Stripe integration

2. **Detection API** (Port 8091)
   - Symbol detection service
   - File processing
   - Usage tracking

3. **Training API** (Port 8092)
   - Model training
   - Dataset management
   - Custom model deployment

4. **Landing Page** (Port 8090)
   - Marketing site
   - API integration demos

5. **PostgreSQL Database** (Port 5432)
   - User data
   - Subscriptions
   - Orders
   - Usage logs

6. **Redis Cache** (Port 6379)
   - Session management
   - API rate limiting

## 📦 Components

### Database Models (`db_models.py`)

- **User**: Email, auth, API keys, limits
- **Subscription**: Plans, Stripe integration, billing
- **Order**: Payment records, invoices
- **UsageLog**: API call tracking
- **CustomModel**: User-trained models
- **ContactMessage**: Contact form submissions

### Authentication (`auth.py`)

- JWT token generation
- Password hashing (bcrypt)
- API key management
- Role-based access control
- Rate limiting

### API Endpoints (`user_api.py`)

#### Public Endpoints
- `POST /auth/register` - Create account
- `POST /auth/login` - Login
- `POST /contact` - Contact form

#### User Endpoints
- `GET /user/profile` - Get profile
- `GET /user/usage` - Usage statistics
- `GET /user/api-key` - Get API key
- `POST /user/regenerate-api-key` - New API key

#### Subscription Endpoints
- `GET /subscriptions/plans` - Available plans
- `POST /subscriptions/create-checkout-session` - Start Stripe checkout
- `GET /subscriptions/current` - Current subscription
- `POST /webhooks/stripe` - Stripe webhooks

#### Admin Endpoints
- `GET /admin/users` - List all users
- `GET /admin/stats` - Platform statistics
- `POST /admin/users/{id}/toggle-active` - Toggle user status

### Dashboards

**User Dashboard** (`user_dashboard.html`)
- API usage stats
- Billing & subscriptions
- API key management
- Recent activity

**Admin Dashboard** (`admin_dashboard.html`)
- Platform overview
- User management
- Revenue analytics
- Subscription monitoring

**Login Page** (`login.html`)
- User registration
- Login form
- Modern UI

## 🚀 Deployment

### Quick Start

```bash
# Make deployment script executable
chmod +x deploy.sh

# Run deployment
sudo ./deploy.sh
```

### Manual Deployment

1. **Install Dependencies**
```bash
apt-get update
apt-get install -y docker.io docker-compose postgresql nginx
```

2. **Setup Database**
```bash
sudo -u postgres psql
CREATE DATABASE mepdetect;
CREATE USER mepdetect WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE mepdetect TO mepdetect;
```

3. **Configure Environment**
```bash
# Create .env file
cat > .env << EOF
DATABASE_URL=postgresql://mepdetect:CHANGE_ME@localhost/mepdetect
SECRET_KEY=$(openssl rand -hex 32)
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
EOF
```

4. **Start Services**
```bash
docker-compose -f docker-compose-full.yml up -d
```

5. **Verify Services**
```bash
curl http://localhost:8090  # Landing page
curl http://localhost:8093/health  # User API
curl http://localhost:8091/health  # Detection API
curl http://localhost:8092/health  # Training API
```

## 💳 Stripe Integration

### Setup

1. **Create Stripe Account**
   - Go to https://dashboard.stripe.com
   - Get API keys

2. **Create Products**
   - Pro Plan: $49/month
   - Enterprise Plan: $299/month

3. **Configure Webhooks**
   - URL: `https://yourdomain.com/webhooks/stripe`
   - Events: `checkout.session.completed`, `customer.subscription.updated`

4. **Update Environment**
```bash
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## 🔑 Subscription Plans

| Feature | Free | Pro | Enterprise |
|---------|------|-----|------------|
| API Calls/month | 100 | 10,000 | Unlimited |
| Storage | 1 GB | 50 GB | 500 GB |
| Custom Models | 0 | 5 | Unlimited |
| Support | Community | Email | Priority + Phone |
| Price | $0 | $49 | $299 |

## 📊 Usage Tracking

Every API call logs:
- User ID
- Endpoint
- Detections count
- Processing time
- Model used
- Credits consumed

## 🛡️ Security

### Authentication
- JWT tokens (30min expiry)
- Refresh tokens (7 days)
- Bcrypt password hashing

### reCAPTCHA Protection
- Google reCAPTCHA v3 on registration and login
- Score-based bot detection (0.0-1.0 scale)
- Configurable threshold (default: 0.5)
- Can be disabled for testing with `RECAPTCHA_ENABLED=false`

See `RECAPTCHA_SETUP.md` for configuration guide.

### API Keys
- Format: `mep_<32-char-random>`
- Can be regenerated
- Rate limited

### Role-Based Access
- FREE: Basic access
- PRO: Enhanced limits
- ENTERPRISE: Full access
- ADMIN: Platform management

## 📈 Admin Features

### Dashboard
- Total users
- Active subscriptions
- Revenue tracking
- New signups (7d)

### User Management
- View all users
- Toggle active/inactive
- Search users
- View usage stats

### Analytics
- API call trends
- Popular endpoints
- Revenue by plan
- User growth

## 🔧 Development

### Run Locally

```bash
# User API
cd user-api
pip install -r requirements.txt
uvicorn main:app --reload --port 8093

# Database migrations
alembic init alembic
alembic revision --autogenerate -m "Initial"
alembic upgrade head
```

### Testing

```bash
# Register user
curl -X POST http://localhost:8093/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123",
    "full_name": "Test User"
  }'

# Login
curl -X POST http://localhost:8093/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123"
  }'

# Get profile (with token)
curl http://localhost:8093/user/profile \
  -H "Authorization: Bearer <token>"
```

## 🌐 Production Setup

### Nginx Configuration

```nginx
server {
    listen 80;
    server_name mepdetect.com;

    location / {
        proxy_pass http://localhost:8090;
    }
    
    location /api/ {
        proxy_pass http://localhost:8091/;
    }
    
    location /auth/ {
        proxy_pass http://localhost:8093/;
    }
}
```

### SSL with Let's Encrypt

```bash
certbot --nginx -d mepdetect.com -d www.mepdetect.com
```

### Environment Variables

**Production .env:**
```bash
DATABASE_URL=postgresql://user:pass@localhost/mepdetect
SECRET_KEY=<64-char-random>
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
ENVIRONMENT=production
ALLOWED_ORIGINS=https://mepdetect.com
```

## 📝 API Documentation

Once deployed, visit:
- User API docs: http://localhost:8093/docs
- Detection API docs: http://localhost:8091/docs
- Training API docs: http://localhost:8092/docs

## 🐛 Troubleshooting

### Database Connection Failed
```bash
# Check PostgreSQL is running
systemctl status postgresql

# Test connection
psql -h localhost -U mepdetect -d mepdetect
```

### Stripe Webhooks Not Working
```bash
# Test with Stripe CLI
stripe listen --forward-to localhost:8093/webhooks/stripe

# Check webhook signature
# Ensure STRIPE_WEBHOOK_SECRET is correct
```

### Service Won't Start
```bash
# Check logs
docker-compose logs -f user-api

# Restart service
docker-compose restart user-api
```

## 📞 Support

For issues or questions:
- Email: support@mepdetect.com
- GitHub: https://github.com/DynMEP/MEPdetect
- Documentation: https://docs.mepdetect.com

## 📄 License

Proprietary - All rights reserved
