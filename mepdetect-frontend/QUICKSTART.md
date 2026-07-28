# 🚀 MEPdetect Landing Page - Quick Start

## Deploy in 3 Commands

```bash
# 1. Navigate to directory
cd /opt/MEPdetector

# 2. Deploy (one command!)
docker-compose up -d --build

# 3. Check status
docker ps | grep mepdetect-landing
```

**That's it!** Your landing page is now live at:
- **http://YOUR_SERVER_IP:8080**

---

## 📋 Prerequisites Checklist

- [x] Docker installed (`docker --version`)
- [x] Docker Compose installed (`docker-compose --version`)
- [x] Port 8080 available
- [x] Files uploaded to `/opt/MEPdetector/`:
  - Dockerfile
  - docker-compose.yml
  - nginx.conf
  - mepdetect-landing-page.html

---

## ⚡ Common Commands

### Using Docker Compose (Recommended)
```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Restart
docker-compose restart

# View logs
docker logs -f mepdetect-landing

# Check status
docker ps | grep mepdetect
```

### Using Deployment Script
```bash
# Make script executable (first time only)
chmod +x deploy.sh

# Then use:
./deploy.sh start
./deploy.sh stop
./deploy.sh restart
./deploy.sh logs
./deploy.sh status
./deploy.sh health
```

### Using Makefile (Easiest)
```bash
make deploy     # Build and start
make stop       # Stop container
make restart    # Restart
make logs       # View logs
make status     # Check status
make health     # Run health check
```

---

## 🔧 Configuration

### Change Port
Edit `docker-compose.yml`, line 11:
```yaml
ports:
  - "8080:80"  # Change 8080 to your desired port
```

Then restart:
```bash
docker-compose down && docker-compose up -d
```

### Update Content
After editing `mepdetect-landing-page.html`:
```bash
# Quick update (no rebuild)
./deploy.sh update

# Or with make
make update

# Or manual
docker cp mepdetect-landing-page.html mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload
```

---

## ✅ Verify Installation

### Test Locally on Server
```bash
curl http://localhost:8080
curl http://localhost:8080/health
```

### Test from Browser
Open: `http://YOUR_SERVER_IP:8080`

You should see the MEPdetect landing page!

---

## 🔍 Troubleshooting

### Container won't start?
```bash
# Check what's using port 8080
sudo lsof -i :8080

# View error logs
docker logs mepdetect-landing
```

### Page not loading?
```bash
# Test nginx config
docker exec mepdetect-landing nginx -t

# Restart container
docker-compose restart
```

### Still having issues?
```bash
# Full health check
./deploy.sh health

# Or check logs
docker logs --tail 100 mepdetect-landing
```

---

## 🔒 Next Steps (Optional)

### 1. Setup Domain
Point your domain DNS to your server IP:
```
A Record: mepdetect.com → YOUR_SERVER_IP
```

### 2. Add SSL/HTTPS
**Option A: Cloudflare (Easiest)**
- Point domain through Cloudflare
- Enable "Full" SSL mode
- Done! Cloudflare handles certificates

**Option B: Let's Encrypt**
```bash
# See README.md for detailed instructions
```

### 3. Setup Firewall
```bash
# Allow HTTP traffic
sudo ufw allow 8080/tcp

# Check status
sudo ufw status
```

### 4. Enable Monitoring
```bash
# Watch container stats
docker stats mepdetect-landing

# Or use the monitoring command
make monitor
```

---

## 📊 Health Check

Run this anytime:
```bash
# Comprehensive check
./deploy.sh health

# Quick check
curl http://localhost:8080/health
```

Expected output: `healthy`

---

## 🆘 Need Help?

1. **View logs**: `docker logs mepdetect-landing`
2. **Check status**: `./deploy.sh status`
3. **Run health check**: `./deploy.sh health`
4. **Read full docs**: See `README.md`

---

## 📈 What's Running?

Your setup includes:
- **Nginx** (lightweight web server)
- **Alpine Linux** (minimal OS, ~5MB)
- **Health checks** (automatic monitoring)
- **Logging** (access & error logs)
- **Compression** (gzip for faster loading)
- **Security headers** (XSS, clickjacking protection)

Total container size: ~25MB
Memory usage: ~10-20MB
CPU usage: <1%

---

## 🎯 Production Checklist

Before going live:
- [ ] Domain pointed to server
- [ ] SSL/HTTPS configured (Cloudflare recommended)
- [ ] Firewall rules configured
- [ ] Google Analytics added
- [ ] Backup strategy in place
- [ ] Monitoring setup
- [ ] Contact forms working
- [ ] Links tested

---

## 🔄 Update Landing Page

When you make changes to the HTML:
```bash
# 1. Edit mepdetect-landing-page.html
nano mepdetect-landing-page.html

# 2. Update container (instant, no downtime)
make update

# OR
./deploy.sh update
```

Changes appear immediately!

---

## 💾 Backup

Create backups before major changes:
```bash
# Create backup
make backup

# OR
./deploy.sh backup
```

Backups saved in `backups/` directory

---

**🎉 You're all set! Your MEPdetect landing page is live!**

Visit: **http://YOUR_SERVER_IP:8080**
