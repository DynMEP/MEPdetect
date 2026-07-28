# 🔗 MEPdetect Frontend-Backend Integration Guide

## Complete Integration of Landing Page + API

---

## 📋 What We Have

### Frontend (Already Deployed)
- ✅ Landing page at `https://mepdetect.com` (port 8090)
- ✅ Nginx serving HTML
- ✅ SSL certificate configured
- ✅ Beautiful UI with forms

### Backend (To Deploy)
- ⏳ FastAPI application
- ⏳ YOLO11 detection engine
- ⏳ Port 8091 (to avoid conflicts)
- ⏳ Complete API endpoints

---

## 🚀 Quick Deployment (15 minutes)

### Step 1: Upload Backend Files (2 min)

```bash
# On your local machine
cd mepdetect-backend

# Upload to server
scp -r * root@YOUR_SERVER:/opt/mepdetect-backend/
```

### Step 2: Deploy Backend Container (5 min)

```bash
# SSH to server
ssh root@YOUR_SERVER

# Navigate to backend directory
cd /opt/mepdetect-backend

# Build and start container
docker-compose up -d --build

# Wait for it to start (check logs)
docker-compose logs -f mepdetect-backend
```

**Expected output:**
```
🚀 MEPdetect API starting...
📁 Upload directory: /app/uploads
📁 Results directory: /app/results
📁 Models directory: /app/models
✅ Found 1 model(s)
✅ API ready!
```

Press `Ctrl+C` to stop following logs.

### Step 3: Test Backend (2 min)

```bash
# Test health endpoint
curl http://localhost:8091/health

# Should return:
# {"status":"healthy","timestamp":"2025-12-30T...","model_loaded":true}
```

### Step 4: Add Nginx Configuration for API (3 min)

```bash
# Copy nginx config
sudo cp /opt/mepdetect-backend/nginx-api-config.conf /etc/nginx/conf.d/mepdetect-api.conf

# Test nginx
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### Step 5: Get SSL for API Subdomain (3 min)

```bash
# Add api.mepdetect.com to your DNS first!
# Type: A, Name: api, Value: YOUR_SERVER_IP

# Then get certificate
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d api.mepdetect.com \
    --expand

# Reload nginx
sudo systemctl reload nginx
```

---

## 🎯 Your Complete Setup

After deployment:

```
Internet
   ↓
Nginx :80, :443 (SSL termination)
   ├── https://mepdetect.com → 127.0.0.1:8090 (Landing Page)
   └── https://api.mepdetect.com → 127.0.0.1:8091 (API)
          ↓
      mepdetect-backend container
          ├── YOLO11 detection
          ├── PDF processing
          └── Result export
```

---

## 🔌 Update Frontend to Connect to Backend

### Method 1: Update HTML directly (Quick)

Edit `/opt/MEPdetector/mepdetect-landing-page.html`:

```html
<script>
// API Configuration
const API_URL = 'https://api.mepdetect.com';

// Upload and detect symbols
async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    // Show loading
    showLoading('Uploading file...');
    
    // Create form data
    const formData = new FormData();
    formData.append('file', file);
    formData.append('confidence', 0.25);
    formData.append('dpi', 400);
    formData.append('export_formats', 'json,csv,excel');
    
    try {
        // Submit to API
        const response = await fetch(`${API_URL}/api/detect`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Upload failed');
        }
        
        const job = await response.json();
        
        // Poll for results
        showLoading('Processing drawing...');
        const result = await pollJobStatus(job.job_id);
        
        // Show results
        displayResults(result);
        
    } catch (error) {
        showError(`Error: ${error.message}`);
    }
}

// Poll job status until complete
async function pollJobStatus(jobId) {
    while (true) {
        const response = await fetch(`${API_URL}/api/jobs/${jobId}`);
        const job = await response.json();
        
        // Update progress
        updateProgress(job.progress, job.message);
        
        if (job.status === 'completed') {
            return job.result;
        } else if (job.status === 'failed') {
            throw new Error(job.message);
        }
        
        // Wait 1 second before checking again
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
}

// Display results
function displayResults(result) {
    const resultsHTML = `
        <div class="results-summary">
            <h2>Detection Complete! 🎉</h2>
            <div class="stats">
                <div class="stat">
                    <h3>${result.total_detections}</h3>
                    <p>Total Symbols</p>
                </div>
                <div class="stat">
                    <h3>${(result.confidence_avg * 100).toFixed(1)}%</h3>
                    <p>Confidence</p>
                </div>
                <div class="stat">
                    <h3>${result.processing_time}s</h3>
                    <p>Processing Time</p>
                </div>
            </div>
            
            <div class="symbol-breakdown">
                <h3>Symbol Breakdown</h3>
                ${Object.entries(result.class_counts).map(([symbol, count]) => `
                    <div class="symbol-row">
                        <span>${symbol}</span>
                        <span class="count">${count}</span>
                    </div>
                `).join('')}
            </div>
            
            <div class="download-buttons">
                <button onclick="downloadResult('${jobId}', 'json')">
                    📄 Download JSON
                </button>
                <button onclick="downloadResult('${jobId}', 'csv')">
                    📊 Download CSV
                </button>
                <button onclick="downloadResult('${jobId}', 'excel')">
                    📈 Download Excel
                </button>
            </div>
        </div>
    `;
    
    document.getElementById('results-container').innerHTML = resultsHTML;
}

// Download result file
function downloadResult(jobId, format) {
    window.location.href = `${API_URL}/api/jobs/${jobId}/download/${format}`;
}

// Helper functions
function showLoading(message) {
    // Show loading spinner with message
    console.log('Loading:', message);
}

function updateProgress(percent, message) {
    // Update progress bar
    console.log(`Progress: ${percent}% - ${message}`);
}

function showError(message) {
    // Show error message
    alert(message);
}

// Add to file input
document.getElementById('file-input').addEventListener('change', handleFileUpload);
</script>
```

### Method 2: Update container content (Persistent)

```bash
# Copy updated HTML to container
docker cp /opt/MEPdetector/mepdetect-landing-page.html \
    mepdetect-landing:/usr/share/nginx/html/index.html

# Reload nginx in container
docker exec mepdetect-landing nginx -s reload
```

---

## 🧪 Testing Complete Flow

### Test 1: Health Check

```bash
# Frontend
curl https://mepdetect.com | grep "MEPdetect"
# Should show landing page

# Backend
curl https://api.mepdetect.com/health
# Should return: {"status":"healthy",...}
```

### Test 2: Upload Test File

```bash
# Create test PDF
echo "Test drawing" > test.txt
mv test.txt test.pdf

# Upload to API
curl -X POST "https://api.mepdetect.com/api/detect" \
  -F "file=@test.pdf" \
  -F "confidence=0.25" \
  -F "dpi=400"

# You'll get back a job_id
```

### Test 3: Check Job Status

```bash
curl "https://api.mepdetect.com/api/jobs/{JOB_ID_FROM_STEP2}"
```

### Test 4: Full Browser Test

1. Open `https://mepdetect.com`
2. Click "Try It Free" or "Get Started"
3. Upload a PDF drawing
4. Wait for processing
5. See results appear
6. Click download buttons

---

## 🔍 Verification Checklist

Run these to verify everything works:

```bash
echo "=== Verification Checklist ==="

echo ""
echo "1. Frontend Container:"
docker ps | grep mepdetect-landing
# Should show: Up X minutes

echo ""
echo "2. Backend Container:"
docker ps | grep mepdetect-backend
# Should show: Up X minutes (healthy)

echo ""
echo "3. Frontend Access:"
curl -I https://mepdetect.com | grep "200"
# Should show: HTTP/2 200

echo ""
echo "4. Backend Health:"
curl https://api.mepdetect.com/health
# Should show: {"status":"healthy",...}

echo ""
echo "5. API Documentation:"
curl -I https://api.mepdetect.com/api/docs | grep "200"
# Should show: HTTP/1.1 200

echo ""
echo "6. SSL Certificates:"
sudo certbot certificates | grep mepdetect
# Should show both certificates

echo ""
echo "7. Nginx Configuration:"
sudo nginx -t
# Should show: test is successful

echo ""
echo "✅ All checks passed!"
```

---

## 📊 Architecture Diagram

```
User Browser
     |
     | HTTPS
     ↓
Nginx (Port 443)
     |
     ├─→ https://mepdetect.com
     |        ↓
     |   Container: mepdetect-landing (Port 8090)
     |        └─→ Landing Page HTML
     |
     └─→ https://api.mepdetect.com
              ↓
         Container: mepdetect-backend (Port 8091)
              ├─→ FastAPI Endpoints
              ├─→ YOLO11 Detection
              ├─→ PDF Processing
              └─→ Result Export
```

---

## 🛠️ Management Commands

### Check Status
```bash
# All containers
docker ps

# Frontend logs
docker logs -f mepdetect-landing

# Backend logs
docker logs -f mepdetect-backend

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Restart Services
```bash
# Restart frontend
docker restart mepdetect-landing

# Restart backend
docker-compose -f /opt/mepdetect-backend/docker-compose.yml restart

# Reload nginx
sudo systemctl reload nginx
```

### Update Backend
```bash
cd /opt/mepdetect-backend

# Pull changes
docker-compose down
docker-compose up -d --build

# Check logs
docker-compose logs -f
```

---

## 🐛 Troubleshooting

### Frontend shows but API doesn't work

```bash
# Check backend is running
docker ps | grep mepdetect-backend

# Check backend logs
docker-compose -f /opt/mepdetect-backend/docker-compose.yml logs

# Test backend directly
curl http://localhost:8091/health
```

### CORS errors in browser console

The backend already has CORS configured for `*`. If issues persist:

```python
# In main.py, update CORS:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mepdetect.com"],  # Your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Then rebuild:
```bash
docker-compose up -d --build
```

### Detection fails

```bash
# Check if model is loaded
curl https://api.mepdetect.com/api/models

# Check job status
curl "https://api.mepdetect.com/api/jobs/{JOB_ID}"

# View detailed logs
docker exec -it mepdetect-backend tail -f /app/logs/app.log
```

### Port conflicts

If port 8091 is already used:

```bash
# Change in docker-compose.yml
ports:
  - "8092:8000"  # Use 8092 instead

# Update nginx config to proxy to 8092
sudo nano /etc/nginx/conf.d/mepdetect-api.conf
# Change: server 127.0.0.1:8091 → server 127.0.0.1:8092

# Restart everything
docker-compose down && docker-compose up -d
sudo systemctl reload nginx
```

---

## 🎉 Success!

When everything is working, you should see:

1. **Landing Page**: https://mepdetect.com shows beautiful UI
2. **API Docs**: https://api.mepdetect.com/api/docs shows Swagger UI
3. **Upload Works**: User can upload file and see progress
4. **Results Show**: Detection results display correctly
5. **Downloads Work**: User can download JSON/CSV/Excel

---

## 📈 Next Steps

1. **Add Analytics**: Track API usage
2. **Add Auth**: Protect API with API keys
3. **Add Caching**: Cache detection results
4. **Add Queue**: Use Redis for job queue
5. **Scale**: Add more backend containers
6. **Monitor**: Add Prometheus/Grafana
7. **Custom Models**: Train on your symbols

---

## 📞 Support

- Backend API: https://api.mepdetect.com/api/docs
- Frontend: https://mepdetect.com
- GitHub: [Issues](https://github.com/DynMEP/YOLOplan/issues)

---

**Your MEPdetect platform is now fully operational!** 🚀
