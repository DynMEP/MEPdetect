# MEPdetect User Management - Quick Start Guide

Get the complete user management system running in 10 minutes.

## ⚡ Fast Track Deployment

### 1. Prerequisites Check

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y docker.io docker-compose postgresql python3-pip
```

### 2. One-Command Deploy

```bash
chmod +x deploy.sh
sudo ./deploy.sh
```

This installs everything:
- ✅ PostgreSQL database
- ✅ Redis cache
- ✅ User Management API
- ✅ Detection API
- ✅ Training API
- ✅ Landing Page

### 3. Create First Admin User

```bash
cd /opt/mepdetect-user-api
python3 admin_tools.py create-admin
```

### 4. Access Services

- **User Dashboard**: http://localhost:8090/dashboard.html
- **Admin Panel**: http://localhost:8090/admin.html
- **Login**: http://localhost:8090/login.html
- **API Docs**: http://localhost:8093/docs

## 🎯 First Steps After Deployment

### Create Test User via API

```bash
curl -X POST http://localhost:8093/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "testpass123",
    "full_name": "Test User"
  }'
```

### Login and Get Token

```bash
curl -X POST http://localhost:8093/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "testpass123"
  }'
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1Q...",
  "refresh_token": "eyJ0eXAiOiJKV1Q...",
  "token_type": "bearer"
}
```

### Use Detection API with Authentication

```bash
TOKEN="your_jwt_token_here"

curl -X POST http://localhost:8091/detect \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@your_drawing.pdf" \
  -F "confidence=0.25"
```

## 🔧 Configuration

### reCAPTCHA Protection

1. **Get reCAPTCHA Keys**: https://www.google.com/recaptcha/admin/create

2. **Update Frontend** (`login.html`):
```html
<script src="https://www.google.com/recaptcha/api.js?render=YOUR_SITE_KEY"></script>
```

And in JavaScript (2 places):
```javascript
await grecaptcha.execute('YOUR_SITE_KEY', {action: 'login'});
```

3. **Update Backend** (`.env`):
```bash
RECAPTCHA_SECRET_KEY=YOUR_SECRET_KEY
```

See `RECAPTCHA_SETUP.md` for complete guide.

### Stripe Integration

1. **Get Stripe Keys**: https://dashboard.stripe.com/apikeys

2. **Update Environment**:
```bash
# Edit /opt/mepdetect-user-api/.env
STRIPE_API_KEY=sk_live_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
```

3. **Create Products in Stripe**:
   - Pro Plan: $49/month
   - Enterprise: $299/month

4. **Setup Webhook**:
   - URL: `https://yourdomain.com/webhooks/stripe`
   - Events: `checkout.session.completed`

### Domain Setup

```bash
# Update nginx config
sudo nano /etc/nginx/sites-available/mepdetect

# Replace localhost with your domain
# Then restart
sudo systemctl restart nginx

# Get SSL certificate
sudo certbot --nginx -d mepdetect.com
```

## 📊 Monitoring

### Check All Services

```bash
docker-compose ps
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f user-api
docker-compose logs -f detection-api
```

### Database Access

```bash
psql -h localhost -U mepdetect -d mepdetect
```

## 🚨 Common Issues

### Port Already in Use

```bash
# Find what's using the port
sudo lsof -i :8093

# Kill the process
sudo kill -9 <PID>
```

### Database Connection Failed

```bash
# Restart PostgreSQL
sudo systemctl restart postgresql

# Check status
sudo systemctl status postgresql
```

### Docker Permission Denied

```bash
sudo usermod -aG docker $USER
newgrp docker
```

## 📈 Usage Examples

### User Registration Flow

1. User visits: `http://mepdetect.com/login.html`
2. Clicks "Register"
3. Fills form
4. Gets redirected to dashboard
5. Receives API key automatically

### Subscription Flow

1. User logs in
2. Clicks "Billing"
3. Selects plan (Pro/Enterprise)
4. Redirected to Stripe checkout
5. After payment, role upgraded automatically
6. API limits increased

### Admin Management

1. Admin logs in at `/admin.html`
2. Views all users
3. Can activate/deactivate users
4. Sees platform statistics
5. Monitors revenue

## 🔐 Security Checklist

- [ ] Change default PostgreSQL password
- [ ] Update SECRET_KEY in .env
- [ ] Configure Stripe keys
- [ ] Enable SSL with Let's Encrypt
- [ ] Set up firewall rules
- [ ] Configure backup strategy
- [ ] Enable rate limiting
- [ ] Set up monitoring/alerts

## 📚 Next Steps

1. **Customize Branding**: Update logos and colors
2. **Email Integration**: Add SendGrid/Mailgun for emails
3. **Analytics**: Integrate Google Analytics
4. **Documentation**: Create user guides
5. **Support**: Setup helpdesk system
6. **Marketing**: SEO and content

## 💡 Tips

- Use environment-specific .env files
- Regular database backups
- Monitor API usage patterns
- Track conversion rates
- A/B test pricing
- Collect user feedback
- Iterate quickly

## 🆘 Getting Help

- Documentation: `USER_MANAGEMENT_README.md`
- Issues: GitHub Issues
- Email: support@mepdetect.com

---

**Ready to scale?** Your platform is production-ready! 🚀
