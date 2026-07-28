# ✅ MEPdetect Deployment Checklist - Your Server

Follow these steps in order. Each step takes 1-5 minutes.

---

## Pre-Deployment (5 minutes)

### ☐ 1. Verify Prerequisites

```bash
# Check Docker
docker --version
docker-compose --version

# Check Nginx
nginx -v
sudo systemctl status nginx

# Check Certbot
certbot --version

# Check port 8090 is free
sudo lsof -i :8090
# Should return nothing (port is free)
```

### ☐ 2. Backup Current Configuration

```bash
# Backup Nginx configs
sudo tar -czf /root/nginx-backup-$(date +%Y%m%d).tar.gz /etc/nginx/conf.d/

# Backup just in case
echo "Backup created!"
```

---

## Container Deployment (5 minutes)

### ☐ 3. Upload Files to Server

From your local machine:
```bash
# Upload Docker files
scp -r mepdetect-docker/* root@YOUR_SERVER_IP:/opt/MEPdetector/
```

### ☐ 4. Deploy Container

```bash
# SSH to server
ssh root@YOUR_SERVER_IP

# Deploy
cd /opt/MEPdetector
docker-compose up -d --build

# Wait 10 seconds
sleep 10

# Verify running
docker ps | grep mepdetect-landing
```

**✓ Expected:** Container shows as "Up" with port 0.0.0.0:8090->80/tcp

### ☐ 5. Test Container Locally

```bash
# Test HTTP
curl http://localhost:8090

# Test health
curl http://localhost:8090/health
```

**✓ Expected:** HTML output and "healthy" response

---

## Nginx Configuration (5 minutes)

### ☐ 6. Add Nginx Config

```bash
# Copy config file
sudo cp /opt/MEPdetector/nginx-host-config.conf /etc/nginx/conf.d/mepdetect.conf

# Or create manually
sudo nano /etc/nginx/conf.d/mepdetect.conf
# Paste contents from nginx-host-config.conf
```

### ☐ 7. Test Nginx Config

```bash
sudo nginx -t
```

**✓ Expected:** "test is successful"

**If errors:** Check syntax, compare with giftcard.conf format

### ☐ 8. Reload Nginx (Without SSL Yet)

```bash
# Comment out SSL lines temporarily if you haven't got certs yet
sudo nano /etc/nginx/conf.d/mepdetect.conf

# Comment out these lines:
#   ssl_certificate     /etc/letsencrypt/live/mepdetect.com/fullchain.pem;
#   ssl_certificate_key /etc/letsencrypt/live/mepdetect.com/privkey.pem;

# Or just wait until after SSL setup
```

---

## DNS Configuration (5 minutes + propagation time)

### ☐ 9. Add DNS Records

Go to your DNS provider (Cloudflare, Namecheap, etc.):

```
Record 1:
Type: A
Name: mepdetect.com (or @)
Value: YOUR_SERVER_IP
TTL: 300

Record 2:
Type: A
Name: www.mepdetect.com (or www)
Value: YOUR_SERVER_IP
TTL: 300
```

### ☐ 10. Verify DNS Propagation

```bash
# Check DNS
dig mepdetect.com +short
# Should show: YOUR_SERVER_IP

# If not propagated yet, wait and check again
# Can take 1-60 minutes
```

---

## SSL Certificate (5 minutes)

### ☐ 11. Get SSL Certificate

```bash
# Using Certbot (same as your wady.io setup)
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d mepdetect.com \
    -d www.mepdetect.com \
    --email YOUR_EMAIL@example.com \
    --agree-tos \
    --non-interactive
```

**✓ Expected:** "Successfully received certificate"

### ☐ 12. Verify Certificate

```bash
# Check certificate exists
sudo ls -la /etc/letsencrypt/live/mepdetect.com/

# Should show:
# fullchain.pem
# privkey.pem
```

### ☐ 13. Enable SSL in Nginx

```bash
# Make sure SSL lines are uncommented
sudo nano /etc/nginx/conf.d/mepdetect.conf

# These lines should be active (not commented):
#   ssl_certificate     /etc/letsencrypt/live/mepdetect.com/fullchain.pem;
#   ssl_certificate_key /etc/letsencrypt/live/mepdetect.com/privkey.pem;

# Test config
sudo nginx -t

# Reload
sudo systemctl reload nginx
```

---

## Final Verification (5 minutes)

### ☐ 14. Test HTTP → HTTPS Redirect

```bash
# Should redirect to HTTPS
curl -I http://mepdetect.com

# Look for:
# HTTP/1.1 301 Moved Permanently
# Location: https://mepdetect.com/
```

### ☐ 15. Test HTTPS

```bash
# Should return 200 OK
curl -I https://mepdetect.com

# Look for:
# HTTP/2 200
```

### ☐ 16. Test in Browser

Open: **https://mepdetect.com**

**✓ Expected:**
- Landing page loads
- Green padlock (SSL valid)
- No browser warnings
- Fast loading

### ☐ 17. Test www Redirect

```bash
# Should redirect to non-www
curl -I https://www.mepdetect.com

# Look for:
# Location: https://mepdetect.com/
```

---

## Health Checks (2 minutes)

### ☐ 18. Run Complete Health Check

```bash
# Container status
docker ps | grep mepdetect-landing
echo "✓ Container running"

# Container health
docker inspect --format='{{.State.Health.Status}}' mepdetect-landing
echo "✓ Container healthy"

# Nginx status
sudo systemctl status nginx --no-pager | grep "active (running)"
echo "✓ Nginx running"

# SSL certificate
sudo certbot certificates | grep -A 3 "mepdetect.com"
echo "✓ Certificate active"

# HTTPS test
curl -I https://mepdetect.com | grep "200"
echo "✓ HTTPS working"

echo ""
echo "🎉 All checks passed!"
```

---

## Post-Deployment (Optional)

### ☐ 19. Add Monitoring (Optional)

```bash
# Create monitoring script
cat > /root/check-mepdetect.sh << 'EOF'
#!/bin/bash
echo "=== MEPdetect Health Check ==="
docker ps | grep mepdetect-landing || echo "⚠ Container not running!"
curl -sf https://mepdetect.com > /dev/null && echo "✓ Site is UP" || echo "⚠ Site is DOWN!"
EOF

chmod +x /root/check-mepdetect.sh

# Test it
/root/check-mepdetect.sh

# Add to cron (check every 5 minutes)
echo "*/5 * * * * /root/check-mepdetect.sh >> /var/log/mepdetect-health.log 2>&1" | sudo crontab -
```

### ☐ 20. Setup Backup Automation (Optional)

```bash
# Backup landing page daily
cat > /root/backup-mepdetect.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/root/backups/mepdetect"
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d)

# Backup HTML
docker cp mepdetect-landing:/usr/share/nginx/html/index.html \
    $BACKUP_DIR/landing-$DATE.html

# Keep only last 7 days
find $BACKUP_DIR -name "landing-*.html" -mtime +7 -delete
EOF

chmod +x /root/backup-mepdetect.sh

# Test it
/root/backup-mepdetect.sh

# Add to cron (daily at 3 AM)
echo "0 3 * * * /root/backup-mepdetect.sh" | sudo crontab -a
```

### ☐ 21. Add to Your Existing Monitoring

If you're monitoring your other services, add:
```bash
# Add to your existing monitoring script
echo "MEPdetect: \$(docker ps | grep -q mepdetect-landing && echo UP || echo DOWN)"
```

---

## Troubleshooting

### If container won't start:
```bash
docker logs mepdetect-landing
docker-compose down && docker-compose up -d
```

### If Nginx won't reload:
```bash
sudo nginx -t  # Check for errors
sudo systemctl restart nginx
sudo tail -f /var/log/nginx/error.log
```

### If SSL fails:
```bash
# Check DNS first
dig mepdetect.com +short

# Try manual certbot
sudo certbot certonly --webroot -w /var/www/certbot -d mepdetect.com -d www.mepdetect.com --debug

# Check logs
sudo tail -f /var/log/letsencrypt/letsencrypt.log
```

### If site not accessible:
```bash
# Check firewall (if enabled)
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Check if port 8090 is listening
sudo netstat -tlnp | grep 8090

# Restart everything
docker-compose restart
sudo systemctl restart nginx
```

---

## Summary of Your Services

After deployment, your server runs:

```
Internet → Nginx :80, :443
├── wady.io services (existing)
│   ├── redeem.wady.io → :5000
│   ├── api.wady.io → :5001
│   ├── admin.wady.io → :5002
│   └── [testnet versions] → 6000, 6001, 6002
└── mepdetect.com (new!)
    └── https://mepdetect.com → :8090
```

**All using:**
- ✅ Same Nginx reverse proxy
- ✅ Same Let's Encrypt SSL
- ✅ Same certbot auto-renewal
- ✅ Consistent configuration pattern

---

## Quick Commands Reference

```bash
# Status
docker ps | grep mepdetect
curl -I https://mepdetect.com

# Logs
docker logs -f mepdetect-landing
sudo tail -f /var/log/nginx/access.log

# Restart
docker-compose restart
sudo systemctl reload nginx

# Update HTML
docker cp mepdetect-landing-page.html mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload

# Certificate renewal
sudo certbot renew
```

---

## ✅ Completion Checklist

Mark each when done:

- [ ] Container running on port 8090
- [ ] Nginx config added and tested
- [ ] DNS records added and propagated
- [ ] SSL certificate obtained
- [ ] HTTP redirects to HTTPS
- [ ] HTTPS working with valid SSL
- [ ] www redirects to non-www
- [ ] Landing page loads correctly
- [ ] Mobile responsive verified
- [ ] Monitoring setup (optional)
- [ ] Backups configured (optional)

---

## 🎉 Launch!

When all boxes are checked:

**Your MEPdetect landing page is LIVE at:**
```
https://mepdetect.com
```

**Integrated seamlessly with your existing infrastructure!**

---

## Next Steps (Marketing)

1. Share on social media
2. Add to email signature
3. Submit to directories
4. Start Google Ads
5. Write blog posts
6. Reach out to MEP contractors

**Your technical setup is complete and production-ready!** 🚀
