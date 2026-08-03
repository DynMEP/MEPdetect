"""
Model Registry
Manages trained models and versioning
"""

from pathlib import Path
from typing import List, Dict, Optional
import os
import shutil
import json
from datetime import datetime


class ModelRegistry:
    """Registry for trained models"""
    
    def __init__(self):
        """Initialize model registry"""
        self.models_dir = Path("/app/models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.models_dir / "registry.json"
        self.models = {}
        
        # Load existing registry
        if self.registry_file.exists():
            with open(self.registry_file, 'r') as f:
                self.models = json.load(f)
    
    
    async def save_model(
        self,
        training_job_id: str,
        model_path: Path,
        dataset_name: str,
        classes: List[str],
        metrics: Dict[str, float]
    ) -> str:
        """
        Save trained model to registry
        
        Args:
            training_job_id: Training job ID
            model_path: Path to trained model
            dataset_name: Name of dataset used
            classes: List of classes
            metrics: Training metrics
            
        Returns:
            Model ID
        """
        
        model_id = training_job_id  # Use job ID as model ID
        
        # Copy model to registry
        dest_path = self.models_dir / f"{model_id}.pt"
        shutil.copy(model_path, dest_path)
        
        # Save metadata
        model_info = {
            "model_id": model_id,
            "name": f"{dataset_name}_model",
            "dataset_name": dataset_name,
            "classes": classes,
            "num_classes": len(classes),
            "metrics": metrics,
            "created_at": datetime.now().isoformat(),
            "size_mb": dest_path.stat().st_size / (1024 * 1024),
            "path": str(dest_path)
        }
        
        self.models[model_id] = model_info
        
        # Save registry
        self._save_registry()
        
        self._register_in_db(model_info)
        
        print(f"💾 Saved model: {model_id}")
        print(f"📊 mAP50: {metrics.get('mAP50', 0):.3f}")
        
        return model_id
    
    
    async def list_models(self) -> List[Dict]:
        """List all models in registry"""
        
        return list(self.models.values())
    
    
    async def get_model(self, model_id: str) -> Optional[Dict]:
        """Get model information"""
        
        return self.models.get(model_id)
    
    
    async def get_model_path(self, model_id: str) -> Optional[Path]:
        """Get path to model file"""
        
        if model_id not in self.models:
            return None
        
        model_path = Path(self.models[model_id]['path'])
        
        if not model_path.exists():
            return None
        
        return model_path
    
    
    async def delete_model(self, model_id: str) -> bool:
        """Delete model from registry"""
        
        if model_id not in self.models:
            return False
        
        # Delete model file
        model_path = Path(self.models[model_id]['path'])
        if model_path.exists():
            model_path.unlink()
        
        # Remove from registry
        del self.models[model_id]
        
        # Save registry
        self._save_registry()
        
        print(f"🗑️  Deleted model: {model_id}")
        
        return True
    
    
    async def load_models(self):
        """Load models from registry file"""
        
        if not self.registry_file.exists():
            return
        
        try:
            with open(self.registry_file, 'r') as f:
                self.models = json.load(f)
            
            # Verify model files exist
            missing = []
            for model_id, model_info in self.models.items():
                model_path = Path(model_info['path'])
                if not model_path.exists():
                    missing.append(model_id)
            
            # Remove missing models
            for model_id in missing:
                print(f"⚠️  Model file missing: {model_id}")
                del self.models[model_id]
            
            if missing:
                self._save_registry()
            
            print(f"📚 Loaded {len(self.models)} models from registry")
            
        except Exception as e:
            print(f"⚠️  Error loading registry: {e}")
            self.models = {}
    
    
    def _save_registry(self):
        """Save registry to disk"""

        with open(self.registry_file, 'w') as f:
            json.dump(self.models, f, indent=2)


    def _register_in_db(self, model_info: Dict):
        """
        Mirror the model into the `models` table of the database.

        registry.json is this service's own bookkeeping; the detection backend
        reads the database instead, both to list models and to resolve the
        default. Without this every upload needed a hand-written INSERT before
        the model showed up anywhere, and a forgotten one left the picker
        claiming the model had no classes.

        A failure here does not fail the upload: the weights and registry.json
        are already written, and the row can be added later.
        """

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            print("ℹ️  DATABASE_URL not set: model saved to registry.json only")
            return

        try:
            import psycopg2

            with psycopg2.connect(database_url) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO models (name, display_name, description, file_path,
                                            file_size, model_type, is_active, is_public,
                                            accuracy_metrics, supported_classes)
                        VALUES (%s, %s, %s, %s, %s, %s, true, false, %s::jsonb, %s::jsonb)
                        ON CONFLICT (name) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            description = EXCLUDED.description,
                            file_path = EXCLUDED.file_path,
                            file_size = EXCLUDED.file_size,
                            accuracy_metrics = EXCLUDED.accuracy_metrics,
                            supported_classes = EXCLUDED.supported_classes,
                            is_active = true,
                            updated_at = now()
                    """, (
                        model_info['model_id'],
                        model_info.get('name') or model_info['model_id'],
                        model_info.get('description', ''),
                        model_info['path'],
                        int(Path(model_info['path']).stat().st_size),
                        model_info.get('model_type', 'yolo11'),
                        json.dumps(model_info.get('metrics', {})),
                        json.dumps(model_info.get('classes', [])),
                    ))
            print(f"🗄️  Registered in database: {model_info['model_id']}")
        except Exception as e:
            print(f"⚠️  Could not register in database ({e}); "
                  f"the model is usable but will not appear in the picker")
    
    
    async def get_best_model(self, metric: str = 'mAP50') -> Optional[Dict]:
        """Get best model by metric"""
        
        if not self.models:
            return None
        
        best_model = max(
            self.models.values(),
            key=lambda m: m['metrics'].get(metric, 0)
        )
        
        return best_model
    
    
    async def export_model_info(self, model_id: str) -> Dict:
        """Export model information for deployment"""
        
        if model_id not in self.models:
            return {}
        
        model_info = self.models[model_id]
        
        return {
            "model_id": model_id,
            "classes": model_info['classes'],
            "num_classes": model_info['num_classes'],
            "metrics": model_info['metrics'],
            "download_url": f"/api/models/{model_id}/download",
            "deployment_command": f"curl -O https://train.mepdetect.com/api/models/{model_id}/download"
        }
    
    
    async def upload_model(
        self,
        model_file: Path,
        name: str,
        classes: List[str],
        description: str = "",
        model_type: str = "yolo11"
    ) -> str:
        """
        Upload pre-trained model to registry
        
        Args:
            model_file: Path to uploaded .pt file
            name: Model name
            classes: List of class names
            description: Optional description
            model_type: Type of model (yolo11, yolo8, etc.)
            
        Returns:
            Model ID
        """
        
        import uuid
        
        # Validate model file
        validation = await self.validate_model_file(model_file)
        if not validation['valid']:
            raise ValueError(f"Invalid model file: {validation['error']}")
        
        # Generate model ID
        model_id = str(uuid.uuid4())[:8]
        
        # Copy model to registry
        dest_path = self.models_dir / f"{model_id}.pt"
        shutil.copy(model_file, dest_path)
        
        # Extract metrics from validation if available
        metrics = {
            "mAP50": 0.0,  # Unknown for uploaded models
            "mAP50-95": 0.0,
            "precision": 0.0,
            "recall": 0.0
        }
        
        # Add model info from validation
        if 'model_info' in validation:
            model_type = validation['model_info'].get('model_type', model_type)
        
        # Save metadata
        model_info = {
            "model_id": model_id,
            "name": name,
            "description": description,
            "dataset_name": "uploaded",
            "classes": classes,
            "num_classes": len(classes),
            "metrics": metrics,
            "created_at": datetime.now().isoformat(),
            "size_mb": dest_path.stat().st_size / (1024 * 1024),
            "path": str(dest_path),
            "source": "upload",
            "model_type": model_type
        }
        
        self.models[model_id] = model_info
        
        # Save registry
        self._save_registry()
        
        self._register_in_db(model_info)
        
        print(f"📤 Uploaded model: {name} ({model_id})")
        print(f"📦 Size: {model_info['size_mb']:.1f} MB")
        print(f"📋 Classes: {len(classes)}")
        
        return model_id
    
    
    async def validate_model_file(self, model_path: Path) -> Dict:
        """
        Validate that file is a valid YOLO model
        
        Args:
            model_path: Path to model file
            
        Returns:
            Validation result dict
        """
        
        result = {
            "valid": False,
            "error": None,
            "model_info": {}
        }
        
        # Check file exists
        if not model_path.exists():
            result['error'] = "File not found"
            return result
        
        # Check file extension
        if model_path.suffix.lower() != '.pt':
            result['error'] = "File must be a .pt file"
            return result
        
        # Check file size (not empty, not too large)
        size_mb = model_path.stat().st_size / (1024 * 1024)
        
        if size_mb == 0:
            result['error'] = "File is empty"
            return result
        
        if size_mb > 500:  # 500MB limit
            result['error'] = f"File too large: {size_mb:.1f} MB (max 500 MB)"
            return result
        
        # Try to load model with PyTorch
        try:
            import torch
            
            # Load model
            model = torch.load(model_path, map_location='cpu')
            
            # Check if it's a YOLO model (has expected structure)
            if isinstance(model, dict):
                # Standard YOLO checkpoint format
                if 'model' in model:
                    result['model_info']['has_model'] = True
                if 'epoch' in model:
                    result['model_info']['epoch'] = model['epoch']
                if model.get('best_fitness') is not None:
                    # ultralytics 8.4 deja best_fitness a None en best.pt tras
                    # el strip del optimizador; float(None) rompía la subida
                    result['model_info']['best_fitness'] = float(model['best_fitness'])
                
                result['valid'] = True
                result['model_info']['format'] = 'checkpoint'
                result['model_info']['size_mb'] = size_mb
                
            else:
                # Direct model object (also valid)
                result['valid'] = True
                result['model_info']['format'] = 'model'
                result['model_info']['size_mb'] = size_mb
            
            # Try to detect model type
            result['model_info']['model_type'] = 'yolo11'  # Default assumption
            
        except Exception as e:
            result['error'] = f"Failed to load model: {str(e)}"
            return result
        
        return result
    
    
    async def update_model_info(
        self,
        model_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        classes: Optional[List[str]] = None
    ) -> bool:
        """
        Update model metadata
        
        Args:
            model_id: Model ID
            name: New name (optional)
            description: New description (optional)
            classes: New classes list (optional)
            
        Returns:
            Success boolean
        """
        
        if model_id not in self.models:
            return False
        
        # Update fields
        if name:
            self.models[model_id]['name'] = name
        
        if description:
            self.models[model_id]['description'] = description
        
        if classes:
            self.models[model_id]['classes'] = classes
            self.models[model_id]['num_classes'] = len(classes)
        
        # Save registry
        self._save_registry()
        
        print(f"✏️  Updated model: {model_id}")
        
        return True