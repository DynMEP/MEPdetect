# 🔗 MEPdetect Integration with Your Existing Setup

## Overview

You already have a **professional production setup** with:
- ✅ Nginx reverse proxy on host
- ✅ Let's Encrypt SSL certificates  
- ✅ Multiple Docker containers (wady.io giftcard system)
- ✅ Certbot configured for automatic renewals

**We'll integrate MEPdetect following your existing pattern!**

---

## 📊 Current Setup Analysis

Your existing infrastructure:
```
Internet
   ↓
Nginx (Host) :80, :443
   ├── wady.io           → /var/www/html/wady-frontend
   ├── redeem.wady.io    → 127.0.0.1:5000 (giftcard-frontend)
   ├── api.wady.io       → 127.0.0.1:5001 (giftcard-backend)
   ├── admin.wady.io     → 127.0.0.1:5002 (giftcard-admin)
   ├── [testnet versions] → 6000, 6001, 6002
   └── [databases/redis]  → 3307, 3308, 6379, 6380
```

**Adding MEPdetect:**
```
Internet
   ↓
Nginx (Host) :80, :443
   ├── [existing services...]
   └── mepdetect.com     → 127.0.0.1:8090 (mepdetect-landing) ← NEW!
```

---

## 🚀 Complete Deployment Steps

### Step 1: Deploy MEPdetect Container

```bash
# Upload Docker files to server
cd /opt/MEPdetector
docker-compose up -d --build

# Verify container is running
docker ps | grep mepdetect-landing

# Test container locally
curl http://localhost:8090
```

**Expected output:**
```
CONTAINER ID   IMAGE               PORTS                    NAMES
abc123xyz      mepdetect-landing   0.0.0.0:8090->80/tcp    mepdetect-landing
```

---

### Step 2: Add Nginx Configuration

**Upload the config file to your server:**

```bash
# Copy nginx-host-config.conf to server
sudo cp nginx-host-config.conf /etc/nginx/conf.d/mepdetect.conf

# Or create it manually
sudo nano /etc/nginx/conf.d/mepdetect.conf
# [paste contents of nginx-host-config.conf]
```

**Test Nginx configuration:**
```bash
sudo nginx -t
```

**If test passes, reload Nginx:**
```bash
sudo systemctl reload nginx
```

---

### Step 3: Point Domain to Server

Add DNS A records for your domain (at your registrar or Cloudflare):

```
Type: A
Name: mepdetect.com
Value: YOUR_SERVER_IP
TTL: 300 (or Auto)

Type: A  
Name: www.mepdetect.com
Value: YOUR_SERVER_IP
TTL: 300 (or Auto)
```

**Wait for DNS propagation** (test with):
```bash
dig mepdetect.com +short
# Should return: YOUR_SERVER_IP
```

---

### Step 4: Get SSL Certificate

Using the **same Certbot method** you used for wady.io:

```bash
# Get certificate for mepdetect.com
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d mepdetect.com \
    -d www.mepdetect.com \
    --email your-email@example.com \
    --agree-tos \
    --non-interactive

# Certbot will create:
# /etc/letsencrypt/live/mepdetect.com/fullchain.pem
# /etc/letsencrypt/live/mepdetect.com/privkey.pem
```

**Alternative: If you want to add to existing certificate:**
```bash
# Expand your existing wady.io certificate
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    --expand \
    -d wady.io -d www.wady.io \
    -d redeem.wady.io -d api.wady.io -d admin.wady.io \
    -d giftcard-test.wady.io -d api-test.wady.io -d admin-test.wady.io \
    -d mepdetect.com -d www.mepdetect.com

# Then update nginx config to use: /etc/letsencrypt/live/wady.io/...
```

---

### Step 5: Reload Nginx with SSL

```bash
# Test config again
sudo nginx -t

# Reload
sudo systemctl reload nginx

# Check status
sudo systemctl status nginx
```

---

### Step 6: Verify Everything Works

```bash
# Test HTTP (should redirect to HTTPS)
curl -I http://mepdetect.com

# Test HTTPS
curl -I https://mepdetect.com

# Test in browser
open https://mepdetect.com
```

**Expected:**
- HTTP redirects to HTTPS
- HTTPS shows your landing page
- SSL certificate is valid
- No browser warnings

---

## 📁 File Structure

```
Your Server:
├── /opt/MEPdetector/
│   ├── docker-compose.yml              ← MEPdetect container config
│   ├── Dockerfile
│   ├── nginx.conf                      ← Container's nginx config
│   └── mepdetect-landing-page.html
│
├── /etc/nginx/
│   ├── conf.d/
│   │   ├── giftcard.conf               ← Your existing config
│   │   └── mepdetect.conf              ← NEW! Add this
│   └── nginx.conf                      ← Main config (no changes)
│
├── /etc/letsencrypt/
│   └── live/
│       ├── wady.io/                    ← Your existing certs
│       └── mepdetect.com/              ← NEW! Created by certbot
│
└── /var/www/certbot/                   ← ACME challenge dir (existing)
```

---

## 🔧 Configuration Details

### Port Mapping

```
Your Setup:
- Host Nginx: :80, :443 (public)
- MEPdetect container: 8090 → 80 (internal only)
- Host Nginx proxies HTTPS to 127.0.0.1:8090

Traffic Flow:
Internet → Nginx :443 (SSL) → localhost:8090 → MEPdetect container
```

**Benefits:**
- ✅ SSL termination at Nginx (like your other services)
- ✅ No port 8090 exposed to internet
- ✅ Consistent with your existing setup
- ✅ Easy certificate management

---

## 🔍 Verification Checklist

Run these tests after deployment:

```bash
# 1. Container running?
docker ps | grep mepdetect-landing

# 2. Container accessible internally?
curl http://localhost:8090

# 3. Nginx config valid?
sudo nginx -t

# 4. Nginx running?
sudo systemctl status nginx

# 5. SSL certificate exists?
sudo ls -la /etc/letsencrypt/live/mepdetect.com/

# 6. HTTP redirects to HTTPS?
curl -I http://mepdetect.com | grep -i location

# 7. HTTPS works?
curl -I https://mepdetect.com

# 8. SSL valid?
openssl s_client -connect mepdetect.com:443 -servername mepdetect.com < /dev/null 2>/dev/null | grep -A 5 "Certificate chain"
```

---

## 🛠️ Management Commands

### Container Management
```bash
# View logs
docker logs -f mepdetect-landing

# Restart container
docker-compose -f /opt/MEPdetector/docker-compose.yml restart

# Stop container
docker-compose -f /opt/MEPdetector/docker-compose.yml down

# Update HTML (no rebuild)
docker cp /opt/MEPdetector/mepdetect-landing-page.html \
    mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload
```

### Nginx Management
```bash
# Test config
sudo nginx -t

# Reload (no downtime)
sudo systemctl reload nginx

# Restart (brief downtime)
sudo systemctl restart nginx

# View error log
sudo tail -f /var/log/nginx/error.log

# View access log
sudo tail -f /var/log/nginx/access.log
```

### SSL Management
```bash
# Check certificate expiry
sudo certbot certificates

# Renew certificates (all domains)
sudo certbot renew

# Test renewal without actually renewing
sudo certbot renew --dry-run
```

---

## 🔄 Certificate Auto-Renewal

Your certificates renew automatically! Certbot's timer handles this.

**Check auto-renewal status:**
```bash
# Check if timer is active
sudo systemctl status certbot.timer

# View timer details
sudo systemctl list-timers certbot.timer
```

**After renewal, Nginx automatically reloads** (Certbot's post-renewal hook).

---

## 🚨 Troubleshooting

### Issue: "502 Bad Gateway"

```bash
# Check if container is running
docker ps | grep mepdetect-landing

# Check container logs
docker logs mepdetect-landing

# Test container directly
curl http://localhost:8090

# Restart container
docker-compose restart
```

### Issue: "Certificate not found"

```bash
# Check if certificate exists
sudo ls -la /etc/letsencrypt/live/mepdetect.com/

# If not, run certbot again
sudo certbot certonly --webroot -w /var/www/certbot \
    -d mepdetect.com -d www.mepdetect.com
```

### Issue: "Redirect loop"

```bash
# Check nginx config
sudo nginx -t

# Look for duplicate proxy_set_header X-Forwarded-Proto
grep -r "X-Forwarded-Proto" /etc/nginx/conf.d/
```

### Issue: "Port 8090 already in use"

```bash
# Check what's using port 8090
sudo lsof -i :8090

# Change port in docker-compose.yml
# Then restart container
docker-compose down && docker-compose up -d
```

### Issue: DNS not propagating

```bash
# Check DNS
dig mepdetect.com +short

# Check from different DNS server
dig @8.8.8.8 mepdetect.com +short

# Wait up to 24 hours for full propagation
```

---

## 📊 Monitoring

### Check All Services

```bash
#!/bin/bash
# Save as check-all.sh

echo "=== Docker Containers ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Nginx Status ==="
sudo systemctl status nginx --no-pager

echo ""
echo "=== SSL Certificates ==="
sudo certbot certificates | grep -A 3 "Certificate Name"

echo ""
echo "=== Disk Usage ==="
df -h | grep -E "(Filesystem|/$)"

echo ""
echo "=== Memory Usage ==="
free -h
```

Make executable and run:
```bash
chmod +x check-all.sh
./check-all.sh
```

---

## 🔐 Security Best Practices

Your existing setup is already secure! MEPdetect follows the same pattern:

✅ **SSL/TLS encryption** (Let's Encrypt)  
✅ **Security headers** (X-Frame-Options, etc.)  
✅ **No unnecessary ports exposed**  
✅ **Containers isolated in Docker network**  
✅ **Auto-renewal for certificates**  

**Additional recommendations:**

1. **Keep software updated:**
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Update Docker images
cd /opt/MEPdetector
docker-compose pull
docker-compose up -d
```

2. **Monitor logs regularly:**
```bash
# Check for errors
sudo grep -i error /var/log/nginx/error.log | tail -20
```

3. **Backup configuration:**
```bash
# Backup nginx configs
sudo tar -czf nginx-backup-$(date +%Y%m%d).tar.gz /etc/nginx/conf.d/

# Backup SSL certificates (optional - can regenerate)
sudo tar -czf letsencrypt-backup-$(date +%Y%m%d).tar.gz /etc/letsencrypt/
```

---

## 📈 Performance Tuning

Your MEPdetect container is already optimized! But if you want even better performance:

### Enable HTTP/2 (Already Enabled)
```nginx
listen 443 ssl http2;  # ✓ Already in config
```

### Add Brotli Compression (Optional)
```bash
# Install Brotli module
sudo apt install nginx-module-brotli

# Add to nginx.conf http block
brotli on;
brotli_comp_level 6;
brotli_types text/plain text/css application/json application/javascript text/xml application/xml;
```

### Add Caching (Optional)
```nginx
# In /etc/nginx/conf.d/mepdetect.conf
# Add before location / block:

# Cache for static assets
proxy_cache_path /var/cache/nginx/mepdetect levels=1:2 keys_zone=mepdetect_cache:10m max_size=100m inactive=60m;

location / {
    proxy_cache mepdetect_cache;
    proxy_cache_valid 200 10m;
    proxy_cache_use_stale error timeout updating;
    # ... rest of proxy config
}
```

---

## 🎯 Quick Reference

**Deploy MEPdetect:**
```bash
cd /opt/MEPdetector
docker-compose up -d --build
sudo cp nginx-host-config.conf /etc/nginx/conf.d/mepdetect.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d mepdetect.com -d www.mepdetect.com
```

**Check Status:**
```bash
docker ps | grep mepdetect
sudo nginx -t
curl -I https://mepdetect.com
```

**Update Landing Page:**
```bash
docker cp mepdetect-landing-page.html mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload
```

**View Logs:**
```bash
docker logs -f mepdetect-landing
sudo tail -f /var/log/nginx/access.log
```

---

## 🎉 You're All Set!

Your MEPdetect landing page will be:
- ✅ Accessible at `https://mepdetect.com`
- ✅ SSL secured with Let's Encrypt
- ✅ Integrated with your existing infrastructure
- ✅ Auto-renewing certificates
- ✅ Production-ready and monitored

**Access your site:**
```
https://mepdetect.com
```

**Total deployment time: 15-20 minutes** (including DNS propagation)
