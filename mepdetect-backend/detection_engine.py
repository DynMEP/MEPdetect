"""
Detection Engine
Wrapper for YOLO11 object detection
"""

from ultralytics import YOLO
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import torch
from datetime import datetime


class DetectionEngine:
    """YOLO11-based symbol detection engine"""
    
    def __init__(
        self,
        model_path: Path,
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        device: str = None
    ):
        """
        Initialize detection engine
        
        Args:
            model_path: Path to YOLO model weights (.pt file)
            confidence_threshold: Minimum confidence for detections
            iou_threshold: IoU threshold for NMS
            device: 'cuda' or 'cpu' (auto-detect if None)
        """
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        
        # Auto-detect device
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
        
        print(f"🔧 Loading model: {model_path}")
        print(f"🖥️  Using device: {self.device}")
        
        # Load model
        if model_path.exists():
            self.model = YOLO(str(model_path))
        else:
            # Try to find yolo11s.pt in models directory
            fallback_path = Path("/app/models/yolo11s.pt")
            if fallback_path.exists():
                print(f"⚠️  Model not found at {model_path}, using {fallback_path}")
                self.model = YOLO(str(fallback_path))
            else:
                print(f"⚠️  No models found, downloading YOLO11s pretrained")
                self.model = YOLO('yolo11s.pt')  # Will auto-download
        
        # Move model to device
        self.model.to(self.device)
        
        print("✅ Model loaded successfully")
    
    
    async def detect(
        self,
        image_path: Path,
        save_annotated: bool = True
    ) -> Dict:
        """
        Detect symbols in image
        
        Args:
            image_path: Path to input image
            save_annotated: Whether to save annotated image
            
        Returns:
            Detection results dictionary
        """
        
        start_time = datetime.now()
        
        # Run detection
        results = self.model.predict(
            source=str(image_path),
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False
        )
        
        # Parse results
        detections = self._parse_results(results[0])
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Prepare output
        output = {
            "image_name": image_path.name,
            "image_path": str(image_path),
            "total_detections": len(detections),
            "detections": detections,
            "class_counts": self._count_classes(detections),
            "confidences": [d['confidence'] for d in detections],
            "processing_time": processing_time
        }
        
        # Save annotated image
        if save_annotated:
            annotated_path = self._save_annotated(results[0], image_path)
            output['annotated_path'] = str(annotated_path)
        
        return output
    
    
    def _parse_results(self, result) -> List[Dict]:
        """Parse YOLO results into structured format"""
        
        detections = []
        
        if result.boxes is None:
            return detections
        
        boxes = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        class_ids = result.boxes.cls.cpu().numpy().astype(int)
        
        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes[i]
            
            detection = {
                "class_id": int(class_ids[i]),
                "class_name": result.names[class_ids[i]],
                "confidence": float(confidences[i]),
                "bbox": {
                    "x1": float(x1),
                    "y1": float(y1),
                    "x2": float(x2),
                    "y2": float(y2),
                    "width": float(x2 - x1),
                    "height": float(y2 - y1),
                    "center_x": float((x1 + x2) / 2),
                    "center_y": float((y1 + y2) / 2)
                }
            }
            
            detections.append(detection)
        
        return detections
    
    
    def _count_classes(self, detections: List[Dict]) -> Dict[str, int]:
        """Count detections per class"""
        
        counts = {}
        for det in detections:
            class_name = det['class_name']
            counts[class_name] = counts.get(class_name, 0) + 1
        
        return counts
    
    
    def _save_annotated(self, result, original_path: Path) -> Path:
        """Save annotated image"""
        
        # Create annotated directory
        annotated_dir = original_path.parent / "annotated"
        annotated_dir.mkdir(exist_ok=True)
        
        # Generate output path
        annotated_path = annotated_dir / f"annotated_{original_path.name}"
        
        # Get annotated image from result
        annotated_img = result.plot()
        
        # Save image
        cv2.imwrite(str(annotated_path), annotated_img)
        
        return annotated_path
    
    
    def batch_detect(
        self,
        image_paths: List[Path],
        save_annotated: bool = True
    ) -> List[Dict]:
        """
        Batch detection for multiple images
        
        Args:
            image_paths: List of image paths
            save_annotated: Whether to save annotated images
            
        Returns:
            List of detection results
        """
        
        results = []
        
        # Batch inference
        batch_results = self.model.predict(
            source=[str(p) for p in image_paths],
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
            stream=True  # Memory efficient
        )
        
        for result, image_path in zip(batch_results, image_paths):
            detections = self._parse_results(result)
            
            output = {
                "image_name": image_path.name,
                "image_path": str(image_path),
                "total_detections": len(detections),
                "detections": detections,
                "class_counts": self._count_classes(detections),
                "confidences": [d['confidence'] for d in detections]
            }
            
            if save_annotated:
                annotated_path = self._save_annotated(result, image_path)
                output['annotated_path'] = str(annotated_path)
            
            results.append(output)
        
        return results
    
    
    def get_model_info(self) -> Dict:
        """Get model information"""
        
        return {
            "model_type": self.model.task,
            "device": self.device,
            "confidence_threshold": self.confidence_threshold,
            "iou_threshold": self.iou_threshold,
            "classes": self.model.names if hasattr(self.model, 'names') else {}
        }
