# MEPdetect

**AI-Powered Symbol Detection for MEP Drawings**

Automates detection and counting of symbols (outlets, fixtures, ducts, pipes, etc.) in electrical, HVAC, and plumbing plans. Built for estimators, contractors, and MEP engineers to slash manual takeoff time by 80-90%.

## Key Features
- YOLO-based object detection on PDFs, images, scanned drawings
- Supports noisy, rotated, or low-quality plans
- Export results: CSV, Excel, JSON, annotated images
- Custom model training pipeline for your specific symbol sets
- Future: Revit/BIM integration, batch processing, cloud version

## Quick Start
```bash
git clone https://github.com/DynMEP/MEPdetect.git
cd MEPdetect
pip install -r requirements.txt
python detect.py --input sample_plan.pdf
