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
        device: str = None,
        tile_size: int = 1024,
        tile_overlap: float = 0.25,
        tile_above: int = 1600
    ):
        """
        Initialize detection engine

        Args:
            model_path: Path to YOLO model weights (.pt file)
            confidence_threshold: Minimum confidence for detections
            iou_threshold: IoU threshold for NMS
            device: 'cuda' or 'cpu' (auto-detect if None)
            tile_size: Side of the tiles a large sheet is cut into before
                inference, in pixels of the original image.
            tile_overlap: Fraction of tile side shared between neighbours, so a
                symbol falling on a seam is whole in at least one tile.
            tile_above: Sheets whose long side exceeds this are tiled. Below it
                a single pass is both enough and cheaper.
        """
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.tile_size = tile_size
        self.tile_overlap = tile_overlap
        self.tile_above = tile_above
        
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

        # A plotted sheet is thousands of pixels across and its symbols are a
        # few dozen. Handed whole to the model it is scaled down to 640 and the
        # symbols land on a handful of pixels each, below what the detector can
        # see: measured on a 4096 px sheet, 10 of 191 symbols found. Cut into
        # tiles they stay near the size they had in training.
        image = cv2.imread(str(image_path))
        if image is not None and max(image.shape[:2]) > self.tile_above:
            detections = self._detect_tiled(image)
            results = None
        else:
            results = self.model.predict(
                source=str(image_path),
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                device=self.device,
                verbose=False
            )
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
            if results is not None:
                annotated_path = self._save_annotated(results[0], image_path)
            else:
                annotated_path = self._save_annotated_boxes(image, detections, image_path)
            output['annotated_path'] = str(annotated_path)

        return output


    def _detect_tiled(self, image: np.ndarray) -> List[Dict]:
        """
        Detect over a large sheet by tiling it, then merge the tiles' results.

        Boxes are shifted back to sheet coordinates and de-duplicated with NMS,
        which is what removes the double hits on the overlap between tiles.

        Args:
            image: Sheet as read by cv2 (BGR)

        Returns:
            Detections in sheet coordinates, same shape as _parse_results
        """

        height, width = image.shape[:2]
        step = max(1, int(self.tile_size * (1 - self.tile_overlap)))

        def offsets(length: int) -> List[int]:
            if length <= self.tile_size:
                return [0]
            # Last tile is pulled back to the edge so the far margin is covered.
            pos = list(range(0, length - self.tile_size, step))
            pos.append(length - self.tile_size)
            return sorted(set(pos))

        crops, origins = [], []
        for oy in offsets(height):
            for ox in offsets(width):
                crops.append(image[oy:oy + self.tile_size, ox:ox + self.tile_size])
                origins.append((ox, oy))

        detections: List[Dict] = []
        # Batched so a big sheet does not issue one call per tile.
        BATCH = 8
        for start in range(0, len(crops), BATCH):
            batch = crops[start:start + BATCH]
            results = self.model.predict(
                source=batch,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                device=self.device,
                verbose=False
            )
            for result, (ox, oy) in zip(results, origins[start:start + BATCH]):
                for det in self._parse_results(result):
                    box = det['bbox']
                    for key_x, key_y in (('x1', 'y1'), ('x2', 'y2'),
                                         ('center_x', 'center_y')):
                        box[key_x] += ox
                        box[key_y] += oy
                    detections.append(det)

        return self._merge_overlapping(detections)


    def _merge_overlapping(self, detections: List[Dict]) -> List[Dict]:
        """
        Drop duplicates coming from the overlap between neighbouring tiles.

        Plain NMS per class: keep the most confident box, discard anything of
        the same class overlapping it above the IoU threshold.

        Args:
            detections: Detections in sheet coordinates

        Returns:
            The subset that survives suppression
        """

        kept: List[Dict] = []
        for det in sorted(detections, key=lambda d: -d['confidence']):
            box = det['bbox']
            duplicate = False
            for other in kept:
                if other['class_id'] != det['class_id']:
                    continue
                ob = other['bbox']
                ix = max(0.0, min(box['x2'], ob['x2']) - max(box['x1'], ob['x1']))
                iy = max(0.0, min(box['y2'], ob['y2']) - max(box['y1'], ob['y1']))
                inter = ix * iy
                union = (box['width'] * box['height']
                         + ob['width'] * ob['height'] - inter)
                if union > 0 and inter / union > self.iou_threshold:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(det)
        return kept


    def _save_annotated_boxes(
        self,
        image: np.ndarray,
        detections: List[Dict],
        original_path: Path
    ) -> Path:
        """Draw merged detections on the sheet (result.plot() only knows one tile)"""

        annotated_dir = original_path.parent / "annotated"
        annotated_dir.mkdir(exist_ok=True)
        annotated_path = annotated_dir / f"annotated_{original_path.name}"

        canvas = image.copy()
        # Thickness scaled to the sheet: a 1 px box is invisible on a plot.
        thickness = max(1, int(round(max(canvas.shape[:2]) / 1000)))
        for det in detections:
            box = det['bbox']
            cv2.rectangle(
                canvas,
                (int(box['x1']), int(box['y1'])),
                (int(box['x2']), int(box['y2'])),
                (0, 0, 255), thickness
            )

        cv2.imwrite(str(annotated_path), canvas)
        return annotated_path
    
    
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
