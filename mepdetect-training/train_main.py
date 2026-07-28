"""
MEPdetect Training API
Train custom YOLO11 models on your symbols
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import uvicorn
import os
import shutil
from datetime import datetime
import json
import uuid
from pathlib import Path
import yaml

# Import training modules
from training_engine import TrainingEngine
from dataset_manager import DatasetManager
from model_registry import ModelRegistry

app = FastAPI(
    title="MEPdetect Training API",
    description="Train custom YOLO11 models on your MEP symbols",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
training_engine = TrainingEngine()
dataset_manager = DatasetManager()
model_registry = ModelRegistry()

# Storage directories
DATASETS_DIR = Path("/app/datasets")
MODELS_DIR = Path("/app/models")
TRAINING_DIR = Path("/app/training")

for directory in [DATASETS_DIR, MODELS_DIR, TRAINING_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# In-memory training job tracking
training_jobs = {}
datasets = {}


# ============================================================================
# Request/Response Models
# ============================================================================

class DatasetCreate(BaseModel):
    """Dataset creation request"""
    name: str
    description: str = ""
    classes: List[str]


class TrainingConfig(BaseModel):
    """Training configuration"""
    model_config = {"protected_namespaces": ()}
    dataset_id: str
    model_size: str = Field(default="s", pattern="^(n|s|m|l|x)$")
    epochs: int = Field(default=100, ge=1, le=1000)
    batch_size: int = Field(default=16, ge=1, le=64)
    image_size: int = Field(default=640, ge=320, le=1280)
    learning_rate: float = Field(default=0.01, ge=0.0001, le=0.1)
    patience: int = Field(default=50, ge=10, le=200)
    save_period: int = Field(default=10, ge=1, le=100)
    augment: bool = True


class TrainingResponse(BaseModel):
    """Training job response"""
    model_config = {"protected_namespaces": ()}
    job_id: str
    status: str
    progress: int
    epoch: int
    total_epochs: int
    metrics: Dict[str, float]
    message: str


class ModelInfo(BaseModel):
    """Model information"""
    model_config = {"protected_namespaces": ()}
    model_id: str
    name: str
    dataset_name: str
    classes: List[str]
    metrics: Dict[str, float]
    created_at: str
    size_mb: float


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/")
async def root():
    """API root"""
    return {
        "name": "MEPdetect Training API",
        "version": "1.0.0",
        "status": "operational",
        "features": [
            "Custom model training",
            "Dataset management",
            "Model versioning",
            "Training monitoring"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_trainings": len([j for j in training_jobs.values() if j['status'] == 'training']),
        "total_datasets": len(datasets),
        "total_models": len(list(MODELS_DIR.glob("*.pt")))
    }


# ============================================================================
# Dataset Management Endpoints
# ============================================================================

@app.post("/api/datasets")
async def create_dataset(
    name: str = Form(...),
    description: str = Form(""),
    classes: str = Form(...),  # Comma-separated
):
    """
    Create a new dataset
    
    **Parameters:**
    - name: Dataset name
    - description: Optional description
    - classes: Comma-separated class names (e.g., "outlet,switch,light")
    """
    
    dataset_id = str(uuid.uuid4())
    class_list = [c.strip() for c in classes.split(',')]
    
    # Create dataset directory structure
    dataset_path = await dataset_manager.create_dataset(
        dataset_id,
        name,
        class_list,
        description
    )
    
    datasets[dataset_id] = {
        "dataset_id": dataset_id,
        "name": name,
        "description": description,
        "classes": class_list,
        "created_at": datetime.now().isoformat(),
        "path": str(dataset_path),
        "image_count": 0,
        "status": "empty"
    }
    
    return datasets[dataset_id]


@app.post("/api/datasets/{dataset_id}/upload")
async def upload_dataset_images(
    dataset_id: str,
    files: List[UploadFile] = File(...),
    split: str = Form("train")  # train, val, or test
):
    """
    Upload images to dataset
    
    **Parameters:**
    - dataset_id: Dataset identifier
    - files: Image files to upload
    - split: Dataset split (train, val, test)
    """
    
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    if split not in ['train', 'val', 'test']:
        raise HTTPException(status_code=400, detail="Split must be train, val, or test")
    
    # Upload images
    uploaded = await dataset_manager.upload_images(
        dataset_id,
        files,
        split
    )
    
    # Update dataset info
    datasets[dataset_id]['image_count'] += len(uploaded)
    datasets[dataset_id]['status'] = 'has_images'
    
    return {
        "uploaded": len(uploaded),
        "split": split,
        "total_images": datasets[dataset_id]['image_count']
    }


@app.post("/api/datasets/{dataset_id}/labels")
async def upload_labels(
    dataset_id: str,
    files: List[UploadFile] = File(...),
    split: str = Form("train")
):
    """
    Upload YOLO format labels
    
    **Format:** .txt files with same name as images
    **Content:** class_id center_x center_y width height (normalized 0-1)
    """
    
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Upload labels
    uploaded = await dataset_manager.upload_labels(
        dataset_id,
        files,
        split
    )
    
    datasets[dataset_id]['status'] = 'labeled'
    
    return {
        "uploaded": len(uploaded),
        "split": split,
        "status": "labeled"
    }


@app.get("/api/datasets")
async def list_datasets():
    """List all datasets"""
    return {"datasets": list(datasets.values())}


@app.get("/api/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """Get dataset details"""
    
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Get statistics
    stats = await dataset_manager.get_statistics(dataset_id)
    
    return {
        **datasets[dataset_id],
        "statistics": stats
    }


@app.delete("/api/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """Delete dataset"""
    
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Delete dataset directory
    dataset_path = Path(datasets[dataset_id]['path'])
    if dataset_path.exists():
        shutil.rmtree(dataset_path)
    
    del datasets[dataset_id]
    
    return {"status": "deleted", "dataset_id": dataset_id}



@app.post("/api/datasets/upload-zip")
async def upload_dataset_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    classes: str = Form(...),
    description: str = Form(""),
    auto_split: bool = Form(True),
    merge_into: Optional[str] = Form(None)
):
    """
    Upload complete dataset as ZIP file
    
    **Supports two structures:**
    1. Split structure: images/train/, images/val/, labels/train/, labels/val/
    2. Flat structure: all images and labels in root (auto-split available)
    
    **Parameters:**
    - file: ZIP file containing dataset
    - dataset_name: Name for the dataset
    - classes: Comma-separated class names
    - description: Optional description
    - auto_split: Auto-split if flat structure (70/20/10 train/val/test)
    - merge_into: Optional dataset ID to merge into
    """
    
    # Validate file type
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")
    
    # Create dataset ID
    dataset_id = str(uuid.uuid4())[:8]
    
    # Save uploaded ZIP temporarily
    temp_dir = Path("/app/temp")
    temp_dir.mkdir(exist_ok=True)
    
    zip_path = temp_dir / f"{dataset_id}.zip"
    
    try:
        # Save ZIP file
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        print(f"📦 Uploaded ZIP: {file.filename} ({len(content) / 1024 / 1024:.1f} MB)")
        
        # Create dataset directory structure
        class_list = [c.strip() for c in classes.split(',')]
        await dataset_manager.create_dataset(
            dataset_id=dataset_id,
            name=dataset_name,
            classes=class_list,
            description=description
        )
        
        # Extract and organize ZIP
        result = await dataset_manager.upload_and_extract_zip(
            dataset_id=dataset_id,
            zip_file=zip_path,
            auto_split=auto_split
        )
        
        # Get statistics
        stats = await dataset_manager.get_statistics(dataset_id)
        
        # Add to datasets dict
        dataset_path = dataset_manager.datasets_dir / dataset_id
        datasets[dataset_id] = {
            "dataset_id": dataset_id,
            "name": dataset_name,
            "description": description,
            "classes": class_list,
            "created_at": datetime.now().isoformat(),
            "path": str(dataset_path),
            "image_count": stats['total_images'],
            "status": "ready" if result['validation']['valid'] else "invalid"
        }
        
        # Merge if requested
        if merge_into and merge_into in datasets:
            merge_result = await dataset_manager.merge_datasets(
                source_id=dataset_id,
                target_id=merge_into
            )
            result['merge'] = merge_result
        
        # Cleanup ZIP
        zip_path.unlink()
        
        return {
            "status": "success",
            "dataset_id": dataset_id,
            "name": dataset_name,
            "extraction": result,
            "statistics": stats
        }
    
    except Exception as e:
        # Cleanup on error
        if zip_path.exists():
            zip_path.unlink()
        
        # Remove created dataset if exists
        dataset_path = dataset_manager.datasets_dir / dataset_id
        if dataset_path.exists():
            shutil.rmtree(dataset_path)
        
        if dataset_id in datasets:
            del datasets[dataset_id]
        
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/api/datasets/{dataset_id}/validate")
async def validate_dataset(dataset_id: str):
    """
    Validate dataset structure and labels
    
    Returns validation report with errors and warnings
    """
    
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    try:
        validation = await dataset_manager.validate_dataset(dataset_id)
        return validation
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


@app.post("/api/datasets/{source_id}/merge/{target_id}")
async def merge_datasets_endpoint(source_id: str, target_id: str):
    """
    Merge source dataset into target dataset
    
    Copies all images and labels from source to target
    """
    
    if source_id not in datasets:
        raise HTTPException(status_code=404, detail=f"Source dataset not found: {source_id}")
    
    if target_id not in datasets:
        raise HTTPException(status_code=404, detail=f"Target dataset not found: {target_id}")
    
    try:
        result = await dataset_manager.merge_datasets(
            source_id=source_id,
            target_id=target_id
        )
        
        # Update target dataset statistics
        stats = await dataset_manager.get_statistics(target_id)
        datasets[target_id]['image_count'] = stats['total_images']
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")



# ============================================================================
# Training Endpoints
# ============================================================================

@app.post("/api/train", response_model=TrainingResponse)
async def start_training(
    background_tasks: BackgroundTasks,
    config: TrainingConfig
):
    """
    Start training a custom model
    
    **Parameters:**
    - dataset_id: Dataset to train on
    - model_size: YOLO model size (n, s, m, l, x)
    - epochs: Training epochs
    - batch_size: Batch size
    - image_size: Input image size
    - learning_rate: Learning rate
    - patience: Early stopping patience
    - augment: Use data augmentation
    """
    
    # Validate dataset
    if config.dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    if datasets[config.dataset_id]['status'] != 'labeled':
        raise HTTPException(status_code=400, detail="Dataset must have labels")
    
    # Create training job
    job_id = str(uuid.uuid4())
    
    training_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "epoch": 0,
        "total_epochs": config.epochs,
        "metrics": {},
        "message": "Training queued",
        "created_at": datetime.now().isoformat(),
        "dataset_id": config.dataset_id,
        "config": config.dict()
    }
    
    # Start training in background
    background_tasks.add_task(
        run_training,
        job_id,
        config
    )
    
    return TrainingResponse(**training_jobs[job_id])


@app.get("/api/training/{job_id}", response_model=TrainingResponse)
async def get_training_status(job_id: str):
    """Get training job status"""
    
    if job_id not in training_jobs:
        raise HTTPException(status_code=404, detail="Training job not found")
    
    return TrainingResponse(**training_jobs[job_id])


@app.get("/api/training")
async def list_training_jobs():
    """List all training jobs"""
    return {"jobs": list(training_jobs.values())}


@app.post("/api/training/{job_id}/stop")
async def stop_training(job_id: str):
    """Stop training job"""
    
    if job_id not in training_jobs:
        raise HTTPException(status_code=404, detail="Training job not found")
    
    if training_jobs[job_id]['status'] != 'training':
        raise HTTPException(status_code=400, detail="Job is not currently training")
    
    # Signal training to stop
    await training_engine.stop_training(job_id)
    
    training_jobs[job_id]['status'] = 'stopped'
    training_jobs[job_id]['message'] = 'Training stopped by user'
    
    return {"status": "stopped", "job_id": job_id}


# ============================================================================
# Model Management Endpoints
# ============================================================================

@app.get("/api/models")
async def list_models():
    """List all trained models"""
    
    models = await model_registry.list_models()
    
    return {"models": models}


@app.get("/api/models/{model_id}")
async def get_model(model_id: str):
    """Get model details"""
    
    model_info = await model_registry.get_model(model_id)
    
    if not model_info:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return model_info


@app.get("/api/models/{model_id}/download")
async def download_model(model_id: str):
    """Download trained model"""
    
    model_path = await model_registry.get_model_path(model_id)
    
    if not model_path or not model_path.exists():
        raise HTTPException(status_code=404, detail="Model file not found")
    
    return FileResponse(
        path=model_path,
        filename=f"{model_id}.pt",
        media_type='application/octet-stream'
    )


@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """Delete model"""
    
    success = await model_registry.delete_model(model_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return {"status": "deleted", "model_id": model_id}


# ============================================================================
# Model Deployment Endpoints (Detection Integration)
# ============================================================================



@app.post("/api/models/upload")
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    classes: str = Form(...),
    description: str = Form(""),
    model_type: str = Form("yolo11")
):
    """
    Upload pre-trained model (.pt file)
    
    **Parameters:**
    - file: YOLO model file (.pt)
    - name: Model name
    - classes: Comma-separated class names
    - description: Optional description
    - model_type: Model type (yolo11, yolo8, etc.)
    """
    
    # Validate file type
    if not file.filename.endswith('.pt'):
        raise HTTPException(status_code=400, detail="File must be a .pt file")
    
    # Save uploaded file temporarily
    temp_dir = Path("/app/temp")
    temp_dir.mkdir(exist_ok=True)
    
    temp_path = temp_dir / file.filename
    
    try:
        # Save file
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        size_mb = len(content) / (1024 * 1024)
        print(f"📤 Uploaded model file: {file.filename} ({size_mb:.1f} MB)")
        
        # Parse classes
        class_list = [c.strip() for c in classes.split(',')]
        
        # Upload to registry
        model_id = await model_registry.upload_model(
            model_file=temp_path,
            name=name,
            classes=class_list,
            description=description,
            model_type=model_type
        )
        
        # Get model info
        model_info = await model_registry.get_model(model_id)
        
        # Cleanup temp file
        temp_path.unlink()
        
        return {
            "status": "success",
            "model_id": model_id,
            "name": name,
            "model_info": model_info
        }
    
    except Exception as e:
        # Cleanup on error
        if temp_path.exists():
            temp_path.unlink()
        
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.put("/api/models/{model_id}")
async def update_model(
    model_id: str,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    classes: Optional[str] = Form(None)
):
    """
    Update model metadata
    
    **Parameters:**
    - name: New model name (optional)
    - description: New description (optional)
    - classes: New comma-separated class names (optional)
    """
    
    if model_id not in (await model_registry.list_models()):
        raise HTTPException(status_code=404, detail="Model not found")
    
    # Parse classes if provided
    class_list = None
    if classes:
        class_list = [c.strip() for c in classes.split(',')]
    
    # Update model
    success = await model_registry.update_model_info(
        model_id=model_id,
        name=name,
        description=description,
        classes=class_list
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Update failed")
    
    # Get updated info
    model_info = await model_registry.get_model(model_id)
    
    return {
        "status": "updated",
        "model_id": model_id,
        "model_info": model_info
    }


@app.post("/api/models/{model_id}/deploy")
async def deploy_model_to_detection(model_id: str):
    """
    Deploy trained model to detection API
    
    Copies the trained model to 'best.pt' so the detection API uses it.
    Since both containers share /opt/mepdetect-shared/models/, 
    this makes the model immediately available for detection.
    
    Args:
        model_id: ID of the model to deploy
        
    Returns:
        Deployment confirmation with model details
    """
    
    # Get model from registry
    model = await model_registry.get_model(model_id)
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    try:
        # Source: trained model
        source_path = Path(model['path'])
        
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Model file not found")
        
        # Destination: best.pt (what detection API uses)
        dest_path = MODELS_DIR / "best.pt"
        
        # Copy model to best.pt
        shutil.copy(source_path, dest_path)
        
        print(f"🚀 Deployed model {model_id} to detection API")
        print(f"📁 Source: {source_path}")
        print(f"📁 Dest: {dest_path}")
        
        return {
            "message": "Model deployed successfully",
            "model_id": model_id,
            "model_name": model['name'],
            "deployment_path": str(dest_path),
            "metrics": model['metrics'],
            "classes": model['classes'],
            "num_classes": model['num_classes'],
            "note": "Detection API will use this model for all new detection requests"
        }
        
    except Exception as e:
        print(f"❌ Deployment error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Deployment failed: {str(e)}"
        )


@app.get("/api/deployment/status")
async def get_deployment_status():
    """
    Check which model is currently deployed in detection API
    
    Returns info about the active 'best.pt' model if it exists,
    and tries to identify which trained model it matches.
    
    Returns:
        Deployment status and active model information
    """
    
    best_model_path = MODELS_DIR / "best.pt"
    
    if not best_model_path.exists():
        return {
            "deployed": False,
            "message": "No model currently deployed (best.pt not found)",
            "deployment_path": str(best_model_path)
        }
    
    # Get file info
    best_model_size = best_model_path.stat().st_size
    best_model_modified = datetime.fromtimestamp(best_model_path.stat().st_mtime)
    
    # Try to find which trained model this is (by matching file size)
    deployed_model = None
    models = await model_registry.list_models()
    
    for model in models:
        model_path = Path(model['path'])
        if model_path.exists() and model_path.stat().st_size == best_model_size:
            # Likely this model (matching file size)
            deployed_model = model
            break
    
    return {
        "deployed": True,
        "deployment_path": str(best_model_path),
        "size_mb": round(best_model_size / (1024 * 1024), 2),
        "deployed_model": deployed_model,
        "last_modified": best_model_modified.isoformat(),
        "note": "This is the model currently being used by the detection API"
    }


@app.post("/api/models/{model_id}/set-as-best")
async def set_model_as_best(model_id: str):
    """
    Alternative deployment method using symlink
    
    Creates a symbolic link from best.pt to the trained model,
    instead of copying. This saves disk space but may not work
    on all filesystems.
    
    Args:
        model_id: ID of the model to set as best
        
    Returns:
        Link creation confirmation
    """
    
    model = await model_registry.get_model(model_id)
    
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    try:
        source_path = Path(model['path'])
        best_path = MODELS_DIR / "best.pt"
        
        # Remove existing best.pt if it exists
        if best_path.exists():
            best_path.unlink()
        
        # Try to create symlink (Linux/Mac) or copy (Windows)
        try:
            best_path.symlink_to(source_path)
            method = "symlink"
            print(f"🔗 Created symlink: best.pt -> {source_path.name}")
        except (OSError, NotImplementedError):
            # Fallback to copy if symlink not supported
            shutil.copy(source_path, best_path)
            method = "copy"
            print(f"📋 Copied model to best.pt (symlink not supported)")
        
        return {
            "message": f"Model set as best ({method})",
            "model_id": model_id,
            "model_name": model['name'],
            "source": str(source_path),
            "destination": str(best_path),
            "method": method
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to set as best: {str(e)}"
        )


# ============================================================================
# Annotation Helper Endpoints
# ============================================================================

@app.get("/api/annotation-tools")
async def get_annotation_tools():
    """Get information about annotation tools"""
    
    return {
        "tools": [
            {
                "name": "Roboflow",
                "url": "https://roboflow.com",
                "description": "Web-based annotation with AI assistance",
                "features": ["Smart polygon", "Auto-labeling", "Export to YOLO"],
                "pricing": "Free tier available"
            },
            {
                "name": "LabelImg",
                "url": "https://github.com/heartexlabs/labelImg",
                "description": "Desktop annotation tool",
                "features": ["YOLO format", "Bounding boxes", "Keyboard shortcuts"],
                "pricing": "Free and open-source"
            },
            {
                "name": "CVAT",
                "url": "https://cvat.ai",
                "description": "Computer Vision Annotation Tool",
                "features": ["Team collaboration", "Video support", "AI models"],
                "pricing": "Free and open-source"
            }
        ],
        "tutorial_url": "https://docs.ultralytics.com/datasets/",
        "format_info": {
            "description": "YOLO format uses .txt files with same name as images",
            "format": "class_id center_x center_y width height",
            "example": "0 0.5 0.5 0.2 0.3",
            "note": "All values normalized to 0-1"
        }
    }


# ============================================================================
# Background Processing
# ============================================================================

async def run_training(job_id: str, config: TrainingConfig):
    """Run training job in background"""
    
    try:
        training_jobs[job_id]['status'] = 'training'
        training_jobs[job_id]['message'] = 'Training started'
        
        # Get dataset info
        dataset = datasets[config.dataset_id]
        dataset_path = Path(dataset['path'])
        
        # Run training
        result = await training_engine.train(
            job_id=job_id,
            dataset_path=dataset_path,
            config=config,
            on_progress=lambda progress: update_training_progress(job_id, progress)
        )
        
        # Save model
        model_id = await model_registry.save_model(
            training_job_id=job_id,
            model_path=result['model_path'],
            dataset_name=dataset['name'],
            classes=dataset['classes'],
            metrics=result['metrics']
        )
        
        # Update job status
        training_jobs[job_id]['status'] = 'completed'
        training_jobs[job_id]['progress'] = 100
        training_jobs[job_id]['metrics'] = result['metrics']
        training_jobs[job_id]['model_id'] = model_id
        training_jobs[job_id]['message'] = 'Training completed successfully'
        
    except Exception as e:
        training_jobs[job_id]['status'] = 'failed'
        training_jobs[job_id]['message'] = f'Training failed: {str(e)}'
        raise


def update_training_progress(job_id: str, progress: Dict):
    """Update training progress"""
    
    if job_id in training_jobs:
        training_jobs[job_id]['epoch'] = progress.get('epoch', 0)
        training_jobs[job_id]['progress'] = int(progress.get('progress', 0))
        training_jobs[job_id]['metrics'] = progress.get('metrics', {})


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    print("🚀 MEPdetect Training API starting...")
    print(f"📁 Datasets directory: {DATASETS_DIR}")
    print(f"📁 Models directory: {MODELS_DIR}")
    print(f"📁 Training directory: {TRAINING_DIR}")
    
    # Load existing datasets
    await dataset_manager.load_datasets(datasets)
    
    # Load existing models
    await model_registry.load_models()
    
    print(f"✅ Loaded {len(datasets)} datasets")
    print(f"✅ Loaded {len(await model_registry.list_models())} models")
    print("✅ Training API ready!")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("👋 MEPdetect Training API shutting down...")


if __name__ == "__main__":
    uvicorn.run(
        "train_main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )