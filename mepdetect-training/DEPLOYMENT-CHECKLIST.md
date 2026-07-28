# ✅ Training Platform Deployment Checklist

## Complete Step-by-Step Guide for train.mepdetect.com

---

## 📋 Pre-Deployment

### ☐ Prerequisites Check

```bash
# Frontend working?
curl -I https://mepdetect.com

# Detection API working?
curl https://api.mepdetect.com/health

# SSH access?
ssh root@YOUR_SERVER

# Docker installed?
docker --version

# Port 8092 free?
sudo lsof -i :8092
# Should return nothing
```

---

## 🚀 Deployment Steps (15 minutes)

### ☐ Step 1: Upload Files (2 min)

```bash
# From local machine
cd mepdetect-training

# Upload to server
scp -r * root@YOUR_SERVER_IP:/opt/mepdetect-training/

# Verify upload
ssh root@YOUR_SERVER_IP "ls -la /opt/mepdetect-training/"
```

**✓ Verify:** All files including `train_main.py`, `Dockerfile`, `docker-compose.yml`

---

### ☐ Step 2: Build Container (5 min)

```bash
# SSH to server
ssh root@YOUR_SERVER_IP

# Navigate to directory
cd /opt/mepdetect-training

# Build and start
docker-compose up -d --build

# Watch build progress
docker-compose logs -f mepdetect-training
```

**Expected output:**
```
🚀 MEPdetect Training API starting...
📁 Datasets directory: /app/datasets
📁 Models directory: /app/models
✅ Loaded 0 datasets
✅ Training API ready!
```

Press `Ctrl+C` to exit logs.

**✓ Verify:** Container is running

```bash
docker ps | grep mepdetect-training
# Should show: Up X minutes (healthy)
```

---

### ☐ Step 3: Test Locally (1 min)

```bash
# Test health endpoint
curl http://localhost:8092/health
```

**Expected:**
```json
{
  "status": "healthy",
  "timestamp": "...",
  "active_trainings": 0,
  "total_datasets": 0,
  "total_models": 0
}
```

---

### ☐ Step 4: Configure DNS (2 min)

Add DNS A record at your domain registrar:

```
Type: A
Name: train
Host: train.mepdetect.com
Value: YOUR_SERVER_IP
TTL: 300
```

**✓ Verify DNS:**
```bash
dig train.mepdetect.com +short
# Should return: YOUR_SERVER_IP
```

Wait 1-5 minutes for propagation.

---

### ☐ Step 5: Add Nginx Configuration (2 min)

```bash
# Copy nginx config
sudo cp /opt/mepdetect-training/nginx-training-config.conf \
    /etc/nginx/conf.d/mepdetect-training.conf

# Test nginx config
sudo nginx -t
```

**Expected:** `test is successful`

**If errors:** Check config syntax

```bash
# Reload nginx
sudo systemctl reload nginx
```

---

### ☐ Step 6: Get SSL Certificate (2 min)

```bash
# Get certificate for train subdomain
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d train.mepdetect.com \
    --expand
```

**Expected:** `Successfully received certificate`

**✓ Verify certificate:**
```bash
sudo ls -la /etc/letsencrypt/live/mepdetect.com/
# Should show fullchain.pem and privkey.pem
```

---

### ☐ Step 7: Reload Nginx with SSL (1 min)

```bash
# Test config again
sudo nginx -t

# Reload
sudo systemctl reload nginx
```

---

### ☐ Step 8: Test Publicly (1 min)

```bash
# Test HTTPS health endpoint
curl https://train.mepdetect.com/health
```

**Expected:**
```json
{
  "status": "healthy",
  ...
}
```

**Test in browser:**
Open: https://train.mepdetect.com/api/docs

You should see the Swagger API documentation.

---

## 🧪 Complete System Test

### ☐ Test 1: All Services Running

```bash
echo "=== Services Check ==="
echo "1. Frontend:"
curl -I https://mepdetect.com | grep "200"

echo "2. Detection API:"
curl https://api.mepdetect.com/health | grep "healthy"

echo "3. Training API:"
curl https://train.mepdetect.com/health | grep "healthy"

echo "4. Containers:"
docker ps | grep mepdetect
```

**Expected:** All return positive results

---

### ☐ Test 2: Create Test Dataset

```bash
curl -X POST "https://train.mepdetect.com/api/datasets" \
  -F "name=Test Dataset" \
  -F "description=Testing dataset creation" \
  -F "classes=test1,test2,test3"
```

**Expected:** Dataset created with ID

---

### ☐ Test 3: API Documentation

Open in browser:
- https://train.mepdetect.com/api/docs (Swagger UI)

Should load successfully with all endpoints.

---

## 🎯 Your Complete Platform

After successful deployment:

```
Internet
   ↓
Nginx :80, :443 (SSL Termination)
   ├─→ mepdetect.com → :8090 → Landing Page
   ├─→ api.mepdetect.com → :8091 → Detection API
   └─→ train.mepdetect.com → :8092 → Training API
```

---

## 📊 Verification Script

Run this complete check:

```bash
#!/bin/bash

echo "======================================="
echo "MEPdetect Platform Verification"
echo "======================================="
echo ""

echo "1. Containers:"
docker ps | grep -E "mepdetect-(landing|backend|training)"
echo ""

echo "2. Frontend:"
curl -I https://mepdetect.com 2>/dev/null | grep "200"
echo ""

echo "3. Detection API:"
curl -s https://api.mepdetect.com/health | jq '.status'
echo ""

echo "4. Training API:"
curl -s https://train.mepdetect.com/health | jq '.status'
echo ""

echo "5. SSL Certificates:"
sudo certbot certificates 2>/dev/null | grep -A 3 "mepdetect.com"
echo ""

echo "6. Nginx Status:"
sudo systemctl status nginx --no-pager | grep "active"
echo ""

echo "7. Port Allocation:"
echo "  - Landing: 8090"
echo "  - Detection: 8091"
echo "  - Training: 8092"
sudo lsof -i :8090 | grep LISTEN
sudo lsof -i :8091 | grep LISTEN
sudo lsof -i :8092 | grep LISTEN
echo ""

echo "======================================="
echo "✅ Platform Check Complete!"
echo "======================================="
```

Save as `check-platform.sh` and run:
```bash
chmod +x check-platform.sh
./check-platform.sh
```

---

## 🛠️ Post-Deployment

### ☐ Create Sample Dataset

Create a test workflow:

```bash
# 1. Create dataset
curl -X POST "https://train.mepdetect.com/api/datasets" \
  -F "name=Electrical Symbols" \
  -F "classes=outlet,switch,light"

# 2. Note dataset ID from response
# 3. Upload images (prepare some test images first)
# 4. Label them (use Roboflow or LabelImg)
# 5. Upload labels
# 6. Start training
```

---

### ☐ Set Up Monitoring (Optional)

```bash
# Create monitoring script
cat > /root/monitor-training.sh << 'EOF'
#!/bin/bash
echo "=== Training Platform Health ==="
docker stats --no-stream mepdetect-training
curl -s https://train.mepdetect.com/health | jq '.'
echo "=== Active Trainings ==="
curl -s https://train.mepdetect.com/api/training | jq '.jobs[] | {job_id, status, progress}'
EOF

chmod +x /root/monitor-training.sh

# Run it
/root/monitor-training.sh
```

---

## 🐛 Common Issues & Fixes

### Issue: Port 8092 already in use

```bash
# Check what's using it
sudo lsof -i :8092

# Change port in docker-compose.yml
ports:
  - "8093:8000"

# Update nginx config too
sudo nano /etc/nginx/conf.d/mepdetect-training.conf
# Change: server 127.0.0.1:8092 → 8093
```

---

### Issue: Container won't start

```bash
# Check logs
docker-compose logs mepdetect-training

# Common causes:
# - Out of memory → Increase limits
# - Port conflict → Change port
# - Build failed → Check internet
```

---

### Issue: Training fails immediately

```bash
# Check dataset format
curl "https://train.mepdetect.com/api/datasets/DATASET_ID"

# Verify:
# - Has images in train and val
# - Has labels for images
# - Classes match dataset definition
```

---

### Issue: Can't upload large datasets

```bash
# Increase nginx limits
sudo nano /etc/nginx/conf.d/mepdetect-training.conf

# Change:
client_max_body_size 1000m;  # 1GB

# Reload
sudo systemctl reload nginx
```

---

## ✅ Success Criteria

Your deployment is successful when:

- [x] Container running and healthy
- [x] Health endpoint returns healthy
- [x] API docs accessible
- [x] Can create dataset
- [x] Can upload images
- [x] SSL certificate valid
- [x] No errors in logs

---

## 📞 Next Steps

### Today
1. ✅ Deploy training platform
2. ✅ Test API endpoints
3. ✅ Create test dataset

### This Week
4. ✅ Label real images
5. ✅ Train first model
6. ✅ Deploy to detection API
7. ✅ Test end-to-end

### This Month
8. ✅ Build production datasets
9. ✅ Train multiple models
10. ✅ Optimize performance
11. ✅ Scale infrastructure

---

## 🎯 Quick Reference

```bash
# Check all services
docker ps | grep mepdetect

# View training logs
docker-compose -f /opt/mepdetect-training/docker-compose.yml logs -f

# Restart training
docker-compose -f /opt/mepdetect-training/docker-compose.yml restart

# Update training
cd /opt/mepdetect-training
docker-compose down && docker-compose up -d --build

# Check resources
docker stats mepdetect-training
```

---

## 🎉 Congratulations!

Your MEPdetect platform is now **complete** with:

✅ Landing Page (mepdetect.com)  
✅ Detection API (api.mepdetect.com)  
✅ Training Platform (train.mepdetect.com)  

**Full AI-powered symbol detection with custom model training!** 🚀

---

**Total Platform Deployment Time: 45 minutes**
**First Custom Model: 1-2 hours**
**Production-Ready: Immediately**
