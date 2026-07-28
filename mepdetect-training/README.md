# 🎓 MEPdetect Training Platform

## Train Custom YOLO11 Models on Your Symbols

Complete training platform for creating custom AI models tailored to your specific MEP symbols.

---

## 🎯 What It Does

### Train Custom Models
- ✅ Upload your own images
- ✅ Label with annotation tools
- ✅ Train YOLO11 models
- ✅ Download trained models
- ✅ Deploy to detection API

### Full Workflow
```
1. Create Dataset
   ↓
2. Upload Images
   ↓
3. Label Symbols (with annotation tools)
   ↓
4. Upload Labels
   ↓
5. Start Training
   ↓
6. Monitor Progress
   ↓
7. Download Model
   ↓
8. Deploy to Detection API
```

---

## 📦 What's Included

### Core Application
- `train_main.py` - FastAPI training application
- `training_engine.py` - YOLO11 training wrapper
- `dataset_manager.py` - Dataset management
- `model_registry.py` - Model versioning

### Docker Setup
- `Dockerfile` - Production container
- `docker-compose.yml` - One-command deployment (port 8092)
- `requirements.txt` - All dependencies
- `nginx-training-config.conf` - Reverse proxy config

---

## ⚡ Quick Deploy (15 minutes)

### Step 1: Upload Files (2 min)
```bash
scp -r mepdetect-training/* root@YOUR_SERVER:/opt/mepdetect-training/
```

### Step 2: Deploy Container (5 min)
```bash
ssh root@YOUR_SERVER
cd /opt/mepdetect-training
docker-compose up -d --build
```

### Step 3: Add DNS (2 min)
Add DNS A record:
```
Type: A
Name: train
Host: train.mepdetect.com
Value: YOUR_SERVER_IP
```

### Step 4: Configure Nginx (3 min)
```bash
sudo cp nginx-training-config.conf /etc/nginx/conf.d/mepdetect-training.conf
sudo nginx -t
sudo systemctl reload nginx
```

### Step 5: Get SSL (2 min)
```bash
sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d train.mepdetect.com \
    --expand

sudo systemctl reload nginx
```

### Step 6: Test (1 min)
```bash
curl https://train.mepdetect.com/health
```

**Done! Training platform is live!** 🎉

---

## 🎯 API Endpoints

### Dataset Management
```
POST   /api/datasets                    # Create dataset
POST   /api/datasets/{id}/upload        # Upload images
POST   /api/datasets/{id}/labels        # Upload labels
GET    /api/datasets                    # List datasets
GET    /api/datasets/{id}               # Get dataset info
DELETE /api/datasets/{id}               # Delete dataset
```

### Training
```
POST   /api/train                       # Start training
GET    /api/training/{id}               # Get training status
GET    /api/training                    # List all training jobs
POST   /api/training/{id}/stop          # Stop training
```

### Models
```
GET    /api/models                      # List trained models
GET    /api/models/{id}                 # Get model info
GET    /api/models/{id}/download        # Download model
DELETE /api/models/{id}                 # Delete model
```

### Utilities
```
GET    /                                # API info
GET    /health                          # Health check
GET    /api/docs                        # Swagger UI
GET    /api/annotation-tools            # Annotation tool info
```

---

## 📚 Complete Training Workflow

### Step 1: Create Dataset

```bash
curl -X POST "https://train.mepdetect.com/api/datasets" \
  -F "name=My Electrical Symbols" \
  -F "description=Outlets, switches, and lights" \
  -F "classes=outlet,switch,light,panel"
```

**Response:**
```json
{
  "dataset_id": "abc123...",
  "name": "My Electrical Symbols",
  "classes": ["outlet", "switch", "light", "panel"],
  "status": "empty"
}
```

---

### Step 2: Upload Images

Prepare your images (JPG, PNG):
- Minimum: 50 images per class
- Recommended: 100-200 images per class
- Good variety: different angles, lighting, backgrounds

```bash
# Upload training images
curl -X POST "https://train.mepdetect.com/api/datasets/abc123.../upload" \
  -F "split=train" \
  -F "files=@image1.jpg" \
  -F "files=@image2.jpg" \
  -F "files=@image3.jpg"
  # ... add all images

# Upload validation images (20% of total)
curl -X POST "https://train.mepdetect.com/api/datasets/abc123.../upload" \
  -F "split=val" \
  -F "files=@val1.jpg" \
  -F "files=@val2.jpg"
```

---

### Step 3: Label Images

Use annotation tools to create labels:

**Option A: Roboflow (Recommended)**
1. Go to https://roboflow.com
2. Create free account
3. Upload images
4. Use smart labeling tools
5. Export in YOLO format
6. Download labels

**Option B: LabelImg (Desktop)**
```bash
pip install labelImg
labelImg
```

**Option C: CVAT (Team Collaboration)**
1. Go to https://cvat.ai
2. Create project
3. Upload images
4. Annotate
5. Export YOLO format

**Label Format (YOLO):**
```
# Each .txt file corresponds to an image
# Format: class_id center_x center_y width height
# All values normalized 0-1

# Example: outlet.txt
0 0.5 0.5 0.2 0.3
0 0.7 0.2 0.15 0.25
```

---

### Step 4: Upload Labels

```bash
# Upload training labels
curl -X POST "https://train.mepdetect.com/api/datasets/abc123.../labels" \
  -F "split=train" \
  -F "files=@image1.txt" \
  -F "files=@image2.txt" \
  -F "files=@image3.txt"

# Upload validation labels
curl -X POST "https://train.mepdetect.com/api/datasets/abc123.../labels" \
  -F "split=val" \
  -F "files=@val1.txt" \
  -F "files=@val2.txt"
```

---

### Step 5: Start Training

```bash
curl -X POST "https://train.mepdetect.com/api/train" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "abc123...",
    "model_size": "s",
    "epochs": 100,
    "batch_size": 16,
    "image_size": 640,
    "learning_rate": 0.01,
    "patience": 50,
    "augment": true
  }'
```

**Response:**
```json
{
  "job_id": "xyz789...",
  "status": "training",
  "progress": 0,
  "epoch": 0,
  "total_epochs": 100
}
```

---

### Step 6: Monitor Progress

```bash
# Poll for status
while true; do
  curl "https://train.mepdetect.com/api/training/xyz789..."
  sleep 10
done
```

**Progress Response:**
```json
{
  "job_id": "xyz789...",
  "status": "training",
  "progress": 45,
  "epoch": 45,
  "total_epochs": 100,
  "metrics": {
    "precision": 0.89,
    "recall": 0.85,
    "mAP50": 0.87,
    "mAP50-95": 0.72
  },
  "message": "Training in progress"
}
```

**Training takes:**
- Small dataset (100 images): 10-30 minutes
- Medium dataset (500 images): 1-2 hours
- Large dataset (1000+ images): 3-5 hours

---

### Step 7: Download Model

Once training completes:

```bash
curl "https://train.mepdetect.com/api/models/xyz789.../download" \
  -o my_model.pt
```

---

### Step 8: Deploy Model

Copy model to detection API:

```bash
# Upload to detection server
scp my_model.pt root@YOUR_SERVER:/opt/mepdetect-backend/data/models/best.pt

# Restart detection API
ssh root@YOUR_SERVER
cd /opt/mepdetect-backend
docker-compose restart
```

**Test your custom model:**
```bash
curl -X POST "https://api.mepdetect.com/api/detect" \
  -F "file=@my_drawing.pdf"
```

---

## 🎓 Training Parameters Guide

### Model Size
- **n (nano)**: Fastest, least accurate - Quick testing
- **s (small)**: Balanced - **Recommended**
- **m (medium)**: More accurate - Production
- **l (large)**: Best accuracy - High-end
- **x (extra)**: Maximum accuracy - Research

### Epochs
- **50-100**: Small datasets
- **100-200**: Medium datasets
- **200-300**: Large datasets
- **Auto-stop**: Use `patience` parameter

### Batch Size
- **8**: Low memory GPU/CPU
- **16**: Standard GPU - **Recommended**
- **32**: High-end GPU
- **64**: Multi-GPU

### Image Size
- **320**: Fast, lower accuracy
- **640**: Balanced - **Recommended**
- **1280**: High accuracy, slow

### Learning Rate
- **0.001**: Very conservative
- **0.01**: Standard - **Recommended**
- **0.1**: Aggressive

---

## 📊 Dataset Guidelines

### Minimum Requirements
- **Images per class**: 50 minimum, 100+ recommended
- **Total images**: 200 minimum, 500+ recommended
- **Train/val/test split**: 70/20/10
- **Label quality**: 95%+ accuracy

### Image Quality
- **Resolution**: 640x640 or higher
- **Format**: JPG or PNG
- **File size**: <5MB per image
- **Variety**: Different angles, lighting, backgrounds

### Labeling Best Practices
- **Tight bounding boxes**: Minimal empty space
- **Consistent**: Same symbol = same class
- **Complete**: Label all instances
- **Verified**: Double-check annotations

---

## 🧪 Testing Your Model

### Quick Test
```bash
# After training, test on validation set
curl "https://train.mepdetect.com/api/models/xyz789..."
```

**Check metrics:**
- **mAP50 > 0.7**: Good model
- **mAP50 > 0.8**: Great model
- **mAP50 > 0.9**: Excellent model

### Visual Inspection
Download model and test locally:
```python
from ultralytics import YOLO

model = YOLO('my_model.pt')
results = model.predict('test_image.jpg', save=True)
```

---

## 🔧 Management Commands

### View Logs
```bash
docker-compose logs -f mepdetect-training
```

### Restart
```bash
docker-compose restart
```

### Update
```bash
docker-compose down
docker-compose up -d --build
```

### Check Status
```bash
curl https://train.mepdetect.com/health
```

### View Training Jobs
```bash
curl https://train.mepdetect.com/api/training
```

### View Trained Models
```bash
curl https://train.mepdetect.com/api/models
```

---

## 📈 Resource Requirements

### Minimum (CPU Training)
- **CPU**: 4 cores
- **RAM**: 8GB
- **Disk**: 20GB
- **Training time**: 1-3 hours (100 epochs)

### Recommended (GPU Training)
- **CPU**: 8 cores
- **RAM**: 16GB
- **GPU**: NVIDIA (4GB+ VRAM)
- **Disk**: 50GB
- **Training time**: 10-30 minutes (100 epochs)

### GPU Setup (Optional)
```yaml
# In docker-compose.yml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

---

## 🎯 Complete Architecture

```
User
  ↓
train.mepdetect.com (HTTPS)
  ↓
Nginx :443 (SSL)
  ↓
Training Container :8092
  ├── Dataset Management
  ├── YOLO11 Training
  ├── Model Registry
  └── Progress Monitoring
```

---

## 🐛 Troubleshooting

### Training fails
```bash
# Check logs
docker-compose logs mepdetect-training

# Common issues:
# - Not enough labeled images
# - Invalid label format
# - Out of memory
```

### Dataset upload fails
```bash
# Check file sizes
# Max: 500MB total per upload
# Split into smaller batches
```

### Can't access API
```bash
# Check container
docker ps | grep mepdetect-training

# Check nginx
sudo nginx -t
sudo systemctl status nginx

# Check SSL
sudo certbot certificates
```

---

## 🎉 You're Ready to Train!

Your training platform is now:
- ✅ Running at `https://train.mepdetect.com`
- ✅ Ready to accept datasets
- ✅ Ready to train custom models
- ✅ Ready to deploy to detection API

---

**Total Setup Time: 15 minutes**
**First Model Training: 30-120 minutes**
**Your Custom AI: Ready to deploy!** 🚀
