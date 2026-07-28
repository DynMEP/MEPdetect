"""
Training Engine
Handles YOLO11 model training
"""

from ultralytics import YOLO
import torch
from pathlib import Path
from typing import Dict, Callable, Optional
import yaml
from datetime import datetime


class TrainingEngine:
    """YOLO11 training engine"""
    
    def __init__(self):
        """Initialize training engine"""
        self.active_trainings = {}
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"🖥️  Training device: {self.device}")
    
    
    async def train(
        self,
        job_id: str,
        dataset_path: Path,
        config,
        on_progress: Optional[Callable] = None
    ) -> Dict:
        """
        Train YOLO11 model
        
        Args:
            job_id: Training job identifier
            dataset_path: Path to dataset directory
            config: Training configuration
            on_progress: Progress callback function
            
        Returns:
            Training results dictionary
        """
        
        print(f"🏋️  Starting training job: {job_id}")
        print(f"📊 Dataset: {dataset_path}")
        print(f"⚙️  Config: {config.dict()}")
        
        # Create data.yaml
        data_yaml = await self._create_data_yaml(dataset_path, config.dataset_id)
        
        # Initialize model
        model_name = f"yolo11{config.model_size}.pt"
        model = YOLO(model_name)
        
        # Store active training
        self.active_trainings[job_id] = {
            "model": model,
            "stop_requested": False
        }
        
        # Training parameters
        train_params = {
            "data": str(data_yaml),
            "epochs": config.epochs,
            "batch": config.batch_size,
            "imgsz": config.image_size,
            "lr0": config.learning_rate,
            "patience": config.patience,
            "save_period": config.save_period,
            "device": self.device,
            "project": f"/app/training/{job_id}",
            "name": "train",
            "exist_ok": True,
            "augment": config.augment,
            "verbose": True
        }
        
        # Progress callback
        def progress_callback(trainer):
            if self.active_trainings.get(job_id, {}).get('stop_requested'):
                trainer.stop()
                return
            
            if on_progress and hasattr(trainer, 'epoch'):
                progress_data = {
                    "epoch": trainer.epoch + 1,
                    "progress": int((trainer.epoch + 1) / config.epochs * 100),
                    "metrics": {
                        "precision": float(trainer.metrics.results_dict.get('metrics/precision(B)', 0)),
                        "recall": float(trainer.metrics.results_dict.get('metrics/recall(B)', 0)),
                        "mAP50": float(trainer.metrics.results_dict.get('metrics/mAP50(B)', 0)),
                        "mAP50-95": float(trainer.metrics.results_dict.get('metrics/mAP50-95(B)', 0)),
                    }
                }
                on_progress(progress_data)
        
        # Add callback
        model.add_callback("on_train_epoch_end", progress_callback)
        
        # Train model
        results = model.train(**train_params)
        
        # Get best model path
        best_model_path = Path(f"/app/training/{job_id}/train/weights/best.pt")
        
        # Extract final metrics
        final_metrics = {
            "precision": float(results.results_dict.get('metrics/precision(B)', 0)),
            "recall": float(results.results_dict.get('metrics/recall(B)', 0)),
            "mAP50": float(results.results_dict.get('metrics/mAP50(B)', 0)),
            "mAP50-95": float(results.results_dict.get('metrics/mAP50-95(B)', 0)),
            "training_time": results.t_training if hasattr(results, 't_training') else 0
        }
        
        # Cleanup
        if job_id in self.active_trainings:
            del self.active_trainings[job_id]
        
        print(f"✅ Training completed: {job_id}")
        print(f"📊 Final mAP50: {final_metrics['mAP50']:.3f}")
        
        return {
            "model_path": best_model_path,
            "metrics": final_metrics,
            "results": results
        }
    
    
    async def _create_data_yaml(self, dataset_path: Path, dataset_id: str) -> Path:
        """Create data.yaml for training"""
        
        # Read classes from dataset
        with open(dataset_path / "classes.txt", 'r') as f:
            classes = [line.strip() for line in f.readlines()]
        
        # Create data.yaml
        data_config = {
            "path": str(dataset_path),
            "train": "images/train",
            "val": "images/val",
            "test": "images/test",
            "nc": len(classes),
            "names": classes
        }
        
        yaml_path = dataset_path / "data.yaml"
        
        with open(yaml_path, 'w') as f:
            yaml.dump(data_config, f, default_flow_style=False)
        
        print(f"📝 Created data.yaml: {yaml_path}")
        
        return yaml_path
    
    
    async def stop_training(self, job_id: str):
        """Stop training job"""
        
        if job_id in self.active_trainings:
            print(f"🛑 Stopping training: {job_id}")
            self.active_trainings[job_id]['stop_requested'] = True
    
    
    def get_device_info(self) -> Dict:
        """Get device information"""
        
        info = {
            "device": self.device,
            "cuda_available": torch.cuda.is_available()
        }
        
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
            info["cuda_memory_total"] = torch.cuda.get_device_properties(0).total_memory / 1e9
        
        return info
