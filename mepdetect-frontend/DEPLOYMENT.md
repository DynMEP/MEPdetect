# MEPdetect Landing Page - Server Deployment Instructions

## 📦 Your Current Server Setup

Based on your server at `/opt/mepdetect`, you have:
- Multiple Docker containers running (Bitcoin, MariaDB, Redis, Flask apps)
- Ports in use: 5000, 5001, 6000, 6001, 6379, 6380, 3307, 3308, 8333, 18333
- All using Gunicorn for Python apps

**We're deploying a static landing page on port 8080 using Nginx (much lighter than Gunicorn).**

---

## 🚀 Step-by-Step Deployment

### Step 1: Upload Files to Server

Upload these files to `/opt/mepdetect/`:
```
/opt/mepdetect/
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── mepdetect-landing-page.html
├── deploy.sh (optional - for easy management)
├── Makefile (optional - for even easier management)
├── README.md (optional - full documentation)
└── QUICKSTART.md (optional - quick reference)
```

**Using SCP:**
```bash
# From your local machine
scp Dockerfile docker-compose.yml nginx.conf mepdetect-landing-page.html \
    root@YOUR_SERVER_IP:/opt/mepdetect/

# If using deploy script and Makefile
scp deploy.sh Makefile README.md QUICKSTART.md \
    root@YOUR_SERVER_IP:/opt/mepdetect/
```

**Using SFTP:**
```bash
sftp root@YOUR_SERVER_IP
cd /opt/mepdetect
put Dockerfile docker-compose.yml nginx.conf mepdetect-landing-page.html
exit
```

---

### Step 2: SSH into Server

```bash
ssh root@YOUR_SERVER_IP
cd /opt/mepdetect
```

---

### Step 3: Deploy Container

**Option A: Using Docker Compose (Recommended)**
```bash
cd /opt/mepdetect
docker-compose up -d --build
```

**Option B: Using Deploy Script**
```bash
chmod +x deploy.sh
./deploy.sh start
```

**Option C: Using Makefile**
```bash
make deploy
```

---

### Step 4: Verify Deployment

```bash
# Check if container is running
docker ps | grep mepdetect-landing

# Should show something like:
# CONTAINER ID   IMAGE                    COMMAND                  STATUS              PORTS
# abc123def456   mepdetect-landing        "nginx -g 'daemon of…"   Up 30 seconds       0.0.0.0:8080->80/tcp

# Test locally
curl http://localhost:8080

# Check health
curl http://localhost:8080/health
# Should return: healthy

# View logs
docker logs mepdetect-landing
```

---

### Step 5: Test from Browser

Open your browser and navigate to:
```
http://YOUR_SERVER_IP:8080
```

You should see your MEPdetect landing page!

---

## 🔧 Integration with Your Existing Setup

### Port Allocation
Your new container uses:
- **External**: 8080 (you can change this)
- **Internal**: 80 (nginx default)

This won't conflict with your existing services:
```
Existing:
- 5000, 5001: Flask apps
- 6000, 6001: Testnet Flask apps  
- 6379, 6380: Redis
- 3307, 3308: MariaDB
- 8333, 18333: Bitcoin nodes

New:
- 8080: MEPdetect landing (Nginx)
```

### Resource Usage
Compared to your Gunicorn Python apps, this Nginx container is very light:
- **Size**: ~25MB (vs 200-500MB for Python apps)
- **Memory**: ~10-20MB (vs 100-300MB for Python apps)
- **CPU**: <1% (vs 2-10% for Python apps)

---

## 📋 Management Commands

### Daily Operations

**Check Status**
```bash
docker ps | grep mepdetect-landing
docker logs --tail 50 mepdetect-landing
```

**View Access Logs**
```bash
docker logs mepdetect-landing | grep GET
```

**Restart Container**
```bash
docker-compose restart
# OR
./deploy.sh restart
# OR
make restart
```

**Update HTML Content**
```bash
# 1. Edit the HTML file
nano mepdetect-landing-page.html

# 2. Quick update (no downtime)
docker cp mepdetect-landing-page.html mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload

# OR use the script
./deploy.sh update

# OR use make
make update
```

---

## 🔒 Firewall Configuration

If you have UFW enabled:
```bash
# Check current rules
sudo ufw status

# Allow port 8080
sudo ufw allow 8080/tcp

# Verify
sudo ufw status
```

---

## 🌐 Domain Setup (Optional)

### Without Reverse Proxy

Point your domain directly:
```
A Record: mepdetect.com → YOUR_SERVER_IP:8080
```

Users visit: `http://mepdetect.com:8080`

### With Reverse Proxy (Recommended)

If you're using Nginx as reverse proxy on the host:

**Create config: `/etc/nginx/sites-available/mepdetect.com`**
```nginx
server {
    listen 80;
    server_name mepdetect.com www.mepdetect.com;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Enable and restart:**
```bash
sudo ln -s /etc/nginx/sites-available/mepdetect.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Users visit: `http://mepdetect.com` (no port needed)

### SSL with Cloudflare (Easiest)

1. Point domain to your server via Cloudflare DNS
2. Enable "Full" SSL mode in Cloudflare dashboard
3. Done! Cloudflare handles certificates

Users visit: `https://mepdetect.com`

---

## 📊 Monitoring

### Check Container Health
```bash
# Quick check
docker inspect --format='{{.State.Health.Status}}' mepdetect-landing

# Full status
./deploy.sh status
# OR
make status
```

### Watch Resource Usage
```bash
# Real-time monitoring
docker stats mepdetect-landing

# Or use watch
watch -n 2 'docker stats --no-stream mepdetect-landing'

# Or with make
make monitor
```

### View Logs
```bash
# Last 100 lines
docker logs --tail 100 mepdetect-landing

# Follow mode (live)
docker logs -f mepdetect-landing

# With script
./deploy.sh logs

# With make
make logs
```

---

## 🔄 Backup and Recovery

### Create Backup
```bash
# Using script
./deploy.sh backup

# OR manually
mkdir -p backups
docker cp mepdetect-landing:/usr/share/nginx/html/index.html \
    backups/backup-$(date +%Y%m%d).html
```

### Restore from Backup
```bash
docker cp backups/backup-20250101.html \
    mepdetect-landing:/usr/share/nginx/html/index.html
docker exec mepdetect-landing nginx -s reload
```

---

## 🆘 Troubleshooting

### Container Won't Start

```bash
# Check logs for errors
docker logs mepdetect-landing

# Common issue: Port already in use
sudo lsof -i :8080
# Solution: Kill the process or change port in docker-compose.yml
```

### Page Not Loading

```bash
# Test from server
curl -I http://localhost:8080

# Check nginx config
docker exec mepdetect-landing nginx -t

# Check firewall
sudo ufw status
```

### Container Keeps Restarting

```bash
# Check what's wrong
docker logs mepdetect-landing

# Inspect container
docker inspect mepdetect-landing

# Common causes:
# 1. nginx.conf syntax error
# 2. Missing HTML file
# 3. Permission issues
```

### Health Check Failing

```bash
# Test health endpoint
curl http://localhost:8080/health

# Check nginx is running
docker exec mepdetect-landing ps aux | grep nginx

# Restart container
docker-compose restart
```

---

## 🧹 Cleanup Commands

### Remove Container (Keep Image)
```bash
docker-compose down
```

### Remove Container and Image
```bash
docker-compose down
docker rmi mepdetector-mepdetect-landing
```

### Clean Everything
```bash
make clean
```

---

## 📊 Expected Performance

With your landing page running:
- **Load Time**: <1 second (local network)
- **Container Memory**: 10-20MB
- **Container CPU**: <1%
- **Concurrent Users**: 1000+ (nginx is very efficient)
- **Requests/sec**: 500-1000+ (depends on hardware)

This is much lighter than your Python/Gunicorn apps!

---

## 🔐 Security Notes

The container includes:
- ✅ Security headers (XSS protection, clickjacking prevention)
- ✅ No unnecessary ports exposed
- ✅ Runs as non-root inside container
- ✅ Health checks for automatic recovery
- ✅ Log rotation to prevent disk fill

For production:
1. Use HTTPS (Cloudflare recommended)
2. Keep Docker updated
3. Monitor logs for suspicious activity
4. Regular backups

---

## 🎯 Production Checklist

- [ ] Container running and healthy
- [ ] Port 8080 accessible
- [ ] Domain pointed to server
- [ ] SSL/HTTPS configured
- [ ] Firewall rules set
- [ ] Monitoring in place
- [ ] Backup strategy configured
- [ ] Google Analytics added
- [ ] Contact forms tested
- [ ] Mobile responsive verified

---

## 📞 Quick Reference

**Start**: `docker-compose up -d` or `make deploy`
**Stop**: `docker-compose down` or `make stop`
**Restart**: `docker-compose restart` or `make restart`
**Logs**: `docker logs -f mepdetect-landing` or `make logs`
**Status**: `docker ps | grep mepdetect` or `make status`
**Update**: `./deploy.sh update` or `make update`
**Health**: `./deploy.sh health` or `make health`

---

## 📈 Next Steps

1. ✅ Deploy container
2. ✅ Verify it's working
3. ⬜ Point domain to server
4. ⬜ Setup SSL with Cloudflare
5. ⬜ Add Google Analytics
6. ⬜ Setup email forms
7. ⬜ Configure backup automation
8. ⬜ Add monitoring alerts

---

**🎉 Your MEPdetect landing page is ready to deploy!**

**Final command to deploy:**
```bash
cd /opt/mepdetect
docker-compose up -d --build
```

**Access your site:**
```
http://YOUR_SERVER_IP:8080
```

Good luck with your launch! 🚀
