"""
Dataset Manager
Handles dataset creation, upload, and management
"""

from pathlib import Path
from typing import List, Dict
import shutil
from fastapi import UploadFile
from PIL import Image
import json
from datetime import datetime


class DatasetManager:
    """Manage training datasets"""
    
    def __init__(self):
        """Initialize dataset manager"""
        self.datasets_dir = Path("/app/datasets")
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
    
    
    async def create_dataset(
        self,
        dataset_id: str,
        name: str,
        classes: List[str],
        description: str = ""
    ) -> Path:
        """
        Create dataset directory structure
        
        Args:
            dataset_id: Dataset identifier
            name: Dataset name
            classes: List of class names
            description: Dataset description
            
        Returns:
            Path to dataset directory
        """
        
        dataset_path = self.datasets_dir / dataset_id
        
        # Create directory structure
        for split in ['train', 'val', 'test']:
            (dataset_path / 'images' / split).mkdir(parents=True, exist_ok=True)
            (dataset_path / 'labels' / split).mkdir(parents=True, exist_ok=True)
        
        # Save classes
        with open(dataset_path / "classes.txt", 'w') as f:
            f.write('\n'.join(classes))
        
        # Save metadata
        metadata = {
            "dataset_id": dataset_id,
            "name": name,
            "description": description,
            "classes": classes,
            "created_at": datetime.now().isoformat()
        }
        
        with open(dataset_path / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"📁 Created dataset: {name} ({dataset_id})")
        print(f"📂 Classes: {', '.join(classes)}")
        
        return dataset_path
    
    
    async def upload_images(
        self,
        dataset_id: str,
        files: List[UploadFile],
        split: str
    ) -> List[str]:
        """
        Upload images to dataset
        
        Args:
            dataset_id: Dataset identifier
            files: Image files to upload
            split: Dataset split (train, val, test)
            
        Returns:
            List of uploaded filenames
        """
        
        dataset_path = self.datasets_dir / dataset_id
        images_dir = dataset_path / 'images' / split
        
        uploaded = []
        
        for file in files:
            # Validate image
            try:
                image = Image.open(file.file)
                image.verify()
            except Exception as e:
                print(f"⚠️  Invalid image: {file.filename} - {e}")
                continue
            
            # Save image
            file_path = images_dir / file.filename
            
            with open(file_path, 'wb') as f:
                file.file.seek(0)  # Reset file pointer after verify
                shutil.copyfileobj(file.file, f)
            
            uploaded.append(file.filename)
        
        print(f"📸 Uploaded {len(uploaded)} images to {split} split")
        
        return uploaded
    
    
    async def upload_labels(
        self,
        dataset_id: str,
        files: List[UploadFile],
        split: str
    ) -> List[str]:
        """
        Upload YOLO format labels
        
        Args:
            dataset_id: Dataset identifier
            files: Label files to upload
            split: Dataset split (train, val, test)
            
        Returns:
            List of uploaded filenames
        """
        
        dataset_path = self.datasets_dir / dataset_id
        labels_dir = dataset_path / 'labels' / split
        
        uploaded = []
        
        for file in files:
            # Validate .txt extension
            if not file.filename.endswith('.txt'):
                print(f"⚠️  Not a .txt file: {file.filename}")
                continue
            
            # Save label
            file_path = labels_dir / file.filename
            
            with open(file_path, 'wb') as f:
                shutil.copyfileobj(file.file, f)
            
            uploaded.append(file.filename)
        
        print(f"🏷️  Uploaded {len(uploaded)} labels to {split} split")
        
        return uploaded
    
    
    async def get_statistics(self, dataset_id: str) -> Dict:
        """
        Get dataset statistics
        
        Args:
            dataset_id: Dataset identifier
            
        Returns:
            Dataset statistics
        """
        
        dataset_path = self.datasets_dir / dataset_id
        
        stats = {
            "splits": {}
        }
        
        for split in ['train', 'val', 'test']:
            images_dir = dataset_path / 'images' / split
            labels_dir = dataset_path / 'labels' / split
            
            image_count = len(list(images_dir.glob('*'))) if images_dir.exists() else 0
            label_count = len(list(labels_dir.glob('*.txt'))) if labels_dir.exists() else 0
            
            stats['splits'][split] = {
                "images": image_count,
                "labels": label_count,
                "labeled_ratio": label_count / image_count if image_count > 0 else 0
            }
        
        # Total counts
        stats['total_images'] = sum(s['images'] for s in stats['splits'].values())
        stats['total_labels'] = sum(s['labels'] for s in stats['splits'].values())
        
        # Check if ready for training
        train_images = stats['splits']['train']['images']
        train_labels = stats['splits']['train']['labels']
        val_images = stats['splits']['val']['images']
        
        stats['ready_for_training'] = (
            train_images > 0 and
            train_labels > 0 and
            val_images > 0 and
            train_labels >= train_images * 0.8  # At least 80% labeled
        )
        
        return stats
    
    
    async def load_datasets(self, datasets_dict: Dict):
        """
        Load existing datasets from disk
        
        Args:
            datasets_dict: Dictionary to populate with datasets
        """
        
        for dataset_dir in self.datasets_dir.iterdir():
            if not dataset_dir.is_dir():
                continue
            
            metadata_file = dataset_dir / "metadata.json"
            
            if not metadata_file.exists():
                continue
            
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                dataset_id = metadata['dataset_id']
                
                # Get image count
                image_count = 0
                for split in ['train', 'val', 'test']:
                    images_dir = dataset_dir / 'images' / split
                    if images_dir.exists():
                        image_count += len(list(images_dir.glob('*')))
                
                # Determine status
                stats = await self.get_statistics(dataset_id)
                
                if stats['total_images'] == 0:
                    status = 'empty'
                elif stats['total_labels'] == 0:
                    status = 'has_images'
                else:
                    status = 'labeled'
                
                datasets_dict[dataset_id] = {
                    "dataset_id": dataset_id,
                    "name": metadata['name'],
                    "description": metadata.get('description', ''),
                    "classes": metadata['classes'],
                    "created_at": metadata['created_at'],
                    "path": str(dataset_dir),
                    "image_count": image_count,
                    "status": status
                }
                
            except Exception as e:
                print(f"⚠️  Error loading dataset {dataset_dir.name}: {e}")
    
    
    async def auto_split_dataset(self, dataset_id: str, train_ratio: float = 0.7, val_ratio: float = 0.2):
        """
        Automatically split dataset into train/val/test
        
        Args:
            dataset_id: Dataset identifier
            train_ratio: Ratio for training set (default 0.7)
            val_ratio: Ratio for validation set (default 0.2)
        """
        
        import random
        
        dataset_path = self.datasets_dir / dataset_id
        
        # Get all images from train split
        train_images = list((dataset_path / 'images' / 'train').glob('*'))
        
        if len(train_images) == 0:
            print("⚠️  No images to split")
            return
        
        # Shuffle
        random.shuffle(train_images)
        
        # Calculate split points
        total = len(train_images)
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)
        
        # Move files
        for i, img_path in enumerate(train_images):
            label_path = dataset_path / 'labels' / 'train' / f"{img_path.stem}.txt"
            
            if i < train_end:
                # Keep in train
                continue
            elif i < val_end:
                # Move to val
                dest_split = 'val'
            else:
                # Move to test
                dest_split = 'test'
            
            # Move image
            dest_img = dataset_path / 'images' / dest_split / img_path.name
            shutil.move(img_path, dest_img)
            
            # Move label if exists
            if label_path.exists():
                dest_label = dataset_path / 'labels' / dest_split / label_path.name
                shutil.move(label_path, dest_label)
        
        print(f"✂️  Split dataset: {train_end} train, {val_end - train_end} val, {total - val_end} test")
    
    
    async def upload_and_extract_zip(
        self,
        dataset_id: str,
        zip_file: Path,
        auto_split: bool = False
    ) -> Dict:
        """
        Upload and extract ZIP dataset
        
        Args:
            dataset_id: Dataset identifier
            zip_file: Path to ZIP file
            auto_split: Auto-split if flat structure
            
        Returns:
            Extraction results with validation info
        """
        
        import zipfile
        
        dataset_path = self.datasets_dir / dataset_id
        temp_extract = dataset_path / "temp_extract"
        temp_extract.mkdir(parents=True, exist_ok=True)
        
        print(f"📦 Extracting ZIP: {zip_file.name}")
        
        try:
            # Extract ZIP
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(temp_extract)
            
            # Detect structure
            structure = await self._detect_dataset_structure(temp_extract)
            
            if structure['type'] == 'split':
                # Already has train/val/test structure (images/train, labels/train)
                print(f"✅ Processing standard split structure")
                await self._organize_split_dataset(temp_extract, dataset_path, structure)
            
            elif structure['type'] == 'roboflow_split':
                # Roboflow structure (train/images, train/labels, valid/images, valid/labels)
                print(f"✅ Processing Roboflow split structure")
                await self._organize_roboflow_dataset(temp_extract, dataset_path, structure)
            
            elif structure['type'] == 'flat':
                # Flat structure - needs splitting
                print(f"✅ Processing flat structure")
                
                if auto_split:
                    await self._organize_flat_dataset(temp_extract, dataset_path, structure)
                    await self.auto_split_dataset(dataset_id)
                else:
                    # Put all in train, user can split later
                    await self._organize_flat_dataset(temp_extract, dataset_path, structure, split=False)
            
            else:
                raise ValueError(f"Unknown dataset structure: {structure['type']}")
            
            # Cleanup temp
            shutil.rmtree(temp_extract)
            
            # Validate
            validation = await self.validate_dataset(dataset_id)
            
            return {
                "status": "success",
                "structure": structure['type'],
                "validation": validation
            }
        
        except Exception as e:
            # Cleanup on error
            if temp_extract.exists():
                shutil.rmtree(temp_extract)
            raise Exception(f"Failed to extract ZIP: {str(e)}")
    
    
    async def _detect_dataset_structure(self, extract_path: Path) -> Dict:
        """Detect if dataset has split structure or flat structure"""
        
        print(f"🔍 Detecting structure in: {extract_path}")
        
        # List contents for debugging
        contents = list(extract_path.iterdir())
        print(f"📂 Found {len(contents)} items: {[x.name for x in contents[:10]]}")
        
        # Check if there's a single nested directory (common in Roboflow exports)
        if len(contents) == 1 and contents[0].is_dir():
            print(f"📁 Found nested directory: {contents[0].name}")
            extract_path = contents[0]
            contents = list(extract_path.iterdir())
            print(f"📂 Inside nested dir: {[x.name for x in contents[:10]]}")
        
        # STRUCTURE 1: Standard split (images/train, labels/train)
        has_images_dir = (extract_path / "images").exists()
        has_labels_dir = (extract_path / "labels").exists()
        
        if has_images_dir and has_labels_dir:
            print("✅ Found images/ and labels/ directories")
            # Check for train/val subdirs
            has_train = (extract_path / "images" / "train").exists()
            has_val = (extract_path / "images" / "val").exists()
            
            if has_train or has_val:
                print("✅ Detected standard split structure (images/train)")
                return {
                    "type": "split",
                    "images_dir": extract_path / "images",
                    "labels_dir": extract_path / "labels",
                    "format": "standard"
                }
        
        # STRUCTURE 2: Roboflow split (train/images, train/labels, valid/images, valid/labels)
        has_train_dir = (extract_path / "train").exists()
        has_valid_dir = (extract_path / "valid").exists() or (extract_path / "val").exists()
        
        if has_train_dir:
            train_images = (extract_path / "train" / "images").exists()
            train_labels = (extract_path / "train" / "labels").exists()
            
            if train_images and train_labels:
                print("✅ Detected Roboflow split structure (train/images)")
                return {
                    "type": "roboflow_split",
                    "root": extract_path,
                    "has_valid": has_valid_dir,
                    "format": "roboflow"
                }
        
        # STRUCTURE 3: Flat structure (images and labels in same dir or root)
        image_files = list(extract_path.glob("*.jpg")) + list(extract_path.glob("*.png"))
        label_files = list(extract_path.glob("*.txt"))
        
        if len(image_files) > 0:
            print(f"✅ Detected flat structure ({len(image_files)} images in root)")
            return {
                "type": "flat",
                "root": extract_path,
                "image_count": len(image_files),
                "label_count": len([f for f in label_files if f.stem != "classes"]),
                "format": "flat"
            }
        
        # STRUCTURE 4: Check subdirectories for flat structure
        for subdir in extract_path.iterdir():
            if subdir.is_dir():
                images = list(subdir.glob("*.jpg")) + list(subdir.glob("*.png"))
                if len(images) > 0:
                    print(f"✅ Detected flat structure in subdirectory: {subdir.name}")
                    return {
                        "type": "flat",
                        "root": subdir,
                        "image_count": len(images),
                        "format": "flat_subdir"
                    }
        
        # If we get here, structure not recognized
        print(f"❌ Could not detect structure. Contents: {[x.name for x in contents]}")
        raise ValueError("Could not detect dataset structure")
    
    
    async def _organize_split_dataset(
        self,
        source: Path,
        dest: Path,
        structure: Dict
    ):
        """Organize dataset that already has train/val/test splits"""
        
        images_src = structure['images_dir']
        labels_src = structure['labels_dir']
        
        for split in ['train', 'val', 'test']:
            # Copy images
            src_images = images_src / split
            if src_images.exists():
                dest_images = dest / 'images' / split
                dest_images.mkdir(parents=True, exist_ok=True)
                
                for img in src_images.glob('*'):
                    if img.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                        shutil.copy2(img, dest_images / img.name)
            
            # Copy labels
            src_labels = labels_src / split
            if src_labels.exists():
                dest_labels = dest / 'labels' / split
                dest_labels.mkdir(parents=True, exist_ok=True)
                
                for label in src_labels.glob('*.txt'):
                    shutil.copy2(label, dest_labels / label.name)
        
        # Copy classes.txt if exists
        for loc in [source, source / "images", source / "labels"]:
            classes_file = loc / "classes.txt"
            if classes_file.exists():
                shutil.copy2(classes_file, dest / "classes.txt")
                break
        
        print(f"✅ Organized split dataset")
    

    
    async def _organize_roboflow_dataset(
        self,
        source: Path,
        dest: Path,
        structure: Dict
    ):
        """Organize Roboflow-style dataset (train/images, train/labels format)"""
        
        root = structure['root']
        
        # Roboflow structure: train/images, train/labels, valid/images, valid/labels
        # Convert to: images/train, labels/train, images/val, labels/val
        
        # Map Roboflow splits to standard splits
        split_mapping = {
            'train': 'train',
            'valid': 'val',
            'val': 'val',
            'test': 'test'
        }
        
        for robo_split in ['train', 'valid', 'val', 'test']:
            src_dir = root / robo_split
            
            if not src_dir.exists():
                continue
            
            std_split = split_mapping.get(robo_split, robo_split)
            
            # Copy images
            src_images = src_dir / "images"
            if src_images.exists():
                dest_images = dest / 'images' / std_split
                dest_images.mkdir(parents=True, exist_ok=True)
                
                for img in src_images.glob('*'):
                    if img.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                        shutil.copy2(img, dest_images / img.name)
                        print(f"📸 Copied {img.name} to images/{std_split}/")
            
            # Copy labels
            src_labels = src_dir / "labels"
            if src_labels.exists():
                dest_labels = dest / 'labels' / std_split
                dest_labels.mkdir(parents=True, exist_ok=True)
                
                for label in src_labels.glob('*.txt'):
                    shutil.copy2(label, dest_labels / label.name)
        
        # Copy data.yaml if exists (common in Roboflow exports)
        data_yaml = root / "data.yaml"
        if data_yaml.exists():
            shutil.copy2(data_yaml, dest / "data.yaml")
            print(f"📄 Copied data.yaml")
        
        # Try to extract classes from data.yaml or README
        classes_extracted = False
        
        # Check data.yaml for classes
        if data_yaml.exists():
            try:
                import yaml
                with open(data_yaml, 'r') as f:
                    data = yaml.safe_load(f)
                    if 'names' in data:
                        classes = data['names']
                        # Write classes.txt
                        with open(dest / "classes.txt", 'w') as cf:
                            if isinstance(classes, list):
                                cf.write('\n'.join(classes))
                            elif isinstance(classes, dict):
                                # Sometimes classes are dict: {0: 'class1', 1: 'class2'}
                                cf.write('\n'.join([classes[i] for i in sorted(classes.keys())]))
                        classes_extracted = True
                        print(f"✅ Extracted {len(classes)} classes from data.yaml")
            except Exception as e:
                print(f"⚠️  Could not extract classes from data.yaml: {e}")
        
        # Copy README if exists
        readme = root / "README.roboflow.txt"
        if readme.exists():
            shutil.copy2(readme, dest / "README.roboflow.txt")
        
        print(f"✅ Organized Roboflow dataset")

    
    async def _organize_flat_dataset(
        self,
        source: Path,
        dest: Path,
        structure: Dict,
        split: bool = True
    ):
        """Organize flat dataset (all files in one directory)"""
        
        root = structure['root']
        target_split = 'train' if not split else 'train'
        
        # Create directories
        dest_images = dest / 'images' / target_split
        dest_labels = dest / 'labels' / target_split
        dest_images.mkdir(parents=True, exist_ok=True)
        dest_labels.mkdir(parents=True, exist_ok=True)
        
        # Copy images and labels
        image_exts = ['.jpg', '.jpeg', '.png']
        
        for img in root.iterdir():
            if img.suffix.lower() in image_exts:
                # Copy image
                shutil.copy2(img, dest_images / img.name)
                
                # Copy corresponding label if exists
                label_file = root / f"{img.stem}.txt"
                if label_file.exists():
                    shutil.copy2(label_file, dest_labels / label_file.name)
        
        # Copy classes.txt
        classes_file = root / "classes.txt"
        if classes_file.exists():
            shutil.copy2(classes_file, dest / "classes.txt")
        
        print(f"✅ Organized flat dataset to {target_split}")
    
    
    async def validate_dataset(self, dataset_id: str) -> Dict:
        """
        Validate dataset structure and content
        
        Returns validation report with errors and warnings
        """
        
        dataset_path = self.datasets_dir / dataset_id
        
        validation = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "stats": {}
        }
        
        # Check classes.txt exists
        classes_file = dataset_path / "classes.txt"
        if not classes_file.exists():
            validation['errors'].append("Missing classes.txt file")
            validation['valid'] = False
        else:
            with open(classes_file, 'r') as f:
                classes = [line.strip() for line in f.readlines()]
                num_classes = len(classes)
                validation['stats']['num_classes'] = num_classes
                validation['stats']['classes'] = classes
        
        # Validate each split
        for split in ['train', 'val', 'test']:
            images_dir = dataset_path / 'images' / split
            labels_dir = dataset_path / 'labels' / split
            
            if not images_dir.exists():
                if split == 'train':
                    validation['errors'].append(f"Missing images/train directory")
                    validation['valid'] = False
                continue
            
            images = list(images_dir.glob('*.jpg')) + list(images_dir.glob('*.png'))
            
            if split == 'train' and len(images) < 10:
                validation['errors'].append(f"Training set too small: {len(images)} images (minimum 10)")
                validation['valid'] = False
            
            if split == 'val' and len(images) == 0:
                validation['warnings'].append("No validation images - recommended for training")
            
            # Check labels
            invalid_labels = []
            missing_labels = []
            
            for img in images:
                label_file = labels_dir / f"{img.stem}.txt"
                
                if not label_file.exists():
                    missing_labels.append(img.name)
                else:
                    # Validate YOLO format
                    try:
                        is_valid = await self._validate_yolo_label(
                            label_file,
                            num_classes if classes_file.exists() else 999
                        )
                        if not is_valid:
                            invalid_labels.append(img.name)
                    except Exception as e:
                        invalid_labels.append(f"{img.name}: {str(e)}")
            
            if len(missing_labels) > 0:
                validation['warnings'].append(
                    f"{split}: {len(missing_labels)} images without labels"
                )
            
            if len(invalid_labels) > 0:
                validation['errors'].append(
                    f"{split}: {len(invalid_labels)} invalid label files"
                )
                validation['valid'] = False
            
            validation['stats'][f'{split}_images'] = len(images)
            validation['stats'][f'{split}_labels'] = len(images) - len(missing_labels)
        
        # Overall check
        total_images = sum([
            validation['stats'].get(f'{split}_images', 0)
            for split in ['train', 'val', 'test']
        ])
        
        if total_images == 0:
            validation['errors'].append("Dataset contains no images")
            validation['valid'] = False
        
        return validation
    
    
    async def _validate_yolo_label(self, label_file: Path, num_classes: int) -> bool:
        """Validate single YOLO format label file"""
        
        with open(label_file, 'r') as f:
            lines = f.readlines()
        
        if len(lines) == 0:
            return True  # Empty label is valid (no objects)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            
            if len(parts) != 5:
                return False  # Must be: class x y w h
            
            try:
                class_id = int(parts[0])
                x, y, w, h = map(float, parts[1:5])
                
                # Validate class ID
                if class_id < 0 or class_id >= num_classes:
                    return False
                
                # Validate coordinates (should be 0-1)
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 <= w <= 1 and 0 <= h <= 1):
                    return False
                
            except ValueError:
                return False
        
        return True
    
    
    async def merge_datasets(
        self,
        source_id: str,
        target_id: str
    ) -> Dict:
        """
        Merge source dataset into target dataset
        
        Args:
            source_id: Source dataset ID
            target_id: Target dataset ID
            
        Returns:
            Merge results
        """
        
        source_path = self.datasets_dir / source_id
        target_path = self.datasets_dir / target_id
        
        if not source_path.exists():
            raise ValueError(f"Source dataset not found: {source_id}")
        
        if not target_path.exists():
            raise ValueError(f"Target dataset not found: {target_id}")
        
        merged_count = 0
        
        # Merge each split
        for split in ['train', 'val', 'test']:
            source_images = source_path / 'images' / split
            source_labels = source_path / 'labels' / split
            target_images = target_path / 'images' / split
            target_labels = target_path / 'labels' / split
            
            if not source_images.exists():
                continue
            
            target_images.mkdir(parents=True, exist_ok=True)
            target_labels.mkdir(parents=True, exist_ok=True)
            
            # Copy images
            for img in source_images.glob('*'):
                if img.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                    dest = target_images / img.name
                    
                    # Rename if exists
                    counter = 1
                    while dest.exists():
                        dest = target_images / f"{img.stem}_{counter}{img.suffix}"
                        counter += 1
                    
                    shutil.copy2(img, dest)
                    
                    # Copy corresponding label
                    label_file = source_labels / f"{img.stem}.txt"
                    if label_file.exists():
                        label_dest = target_labels / f"{dest.stem}.txt"
                        shutil.copy2(label_file, label_dest)
                    
                    merged_count += 1
        
        print(f"✅ Merged {merged_count} images from {source_id} to {target_id}")
        
        return {
            "status": "success",
            "merged_images": merged_count,
            "source": source_id,
            "target": target_id
        }