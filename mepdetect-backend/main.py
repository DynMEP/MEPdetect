"""
MEPdetect Backend API - STANDALONE VERSION
Works independently, optional database logging
"""

from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException,
    Query, UploadFile,
)
from dataclasses import dataclass
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any, Tuple
import uvicorn
import asyncio
import os
import tempfile
import shutil
from datetime import datetime
import json
import uuid
import zipfile
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
import os

# Import our detection modules
from detection_engine import DetectionEngine
from file_processor import FileProcessor
from result_exporter import ResultExporter
from circuit_tracer import (
    PANEL_KEYWORDS, CircuitTracer, merge_cross_sheet_circuits,
    summarize_circuits,
)
from pdf_geometry import extract_sheet_geometry
from calibration import Calibration, parse_reference
from reconcile import reconcile_takeoff
import plan_tokens

# Optional database imports - gracefully handle if not available
try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    DATABASE_AVAILABLE = True
    
    # Try to import db_models
    try:
        from db_models import Base, User, UsageLog
        DB_MODELS_AVAILABLE = True
    except ImportError:
        print("⚠️  db_models not available - database logging disabled")
        DB_MODELS_AVAILABLE = False
        
except ImportError:
    print("⚠️  SQLAlchemy not available - database logging disabled")
    DATABASE_AVAILABLE = False
    DB_MODELS_AVAILABLE = False

app = FastAPI(
    title="MEPdetect API",
    description="AI-Powered Symbol Detection for MEP Drawings",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS middleware - ALLOW ALL ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
detection_engine = None
file_processor = FileProcessor()
result_exporter = ResultExporter()
circuit_tracer = CircuitTracer()

# Storage directories
UPLOAD_DIR = Path("/app/uploads")
RESULTS_DIR = Path("/app/results")
MODELS_DIR = Path("/app/models")

for directory in [UPLOAD_DIR, RESULTS_DIR, MODELS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# In-memory job tracking
jobs = {}

# Database session maker (if available)
SessionLocal = None
if DATABASE_AVAILABLE and DB_MODELS_AVAILABLE:
    try:
        # No credential fallback: without DATABASE_URL the except below
        # disables database logging, which is the intended standalone mode.
        DATABASE_URL = os.environ["DATABASE_URL"]
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        print("✅ Database connection configured")
    except Exception as e:
        print(f"⚠️  Database connection failed: {e}")
        DATABASE_AVAILABLE = False


# ============================================================================
# Request/Response Models
# ============================================================================

class DetectionRequest(BaseModel):
    """Detection job configuration"""
    confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    dpi: int = Field(default=400, ge=72, le=600)
    save_annotated: bool = True
    trace_circuits: bool = False
    export_formats: List[str] = ["json", "csv", "excel"]
    
    
class DetectionResponse(BaseModel):
    """Detection results"""
    job_id: str
    status: str
    total_detections: int
    class_counts: Dict[str, int]
    confidence_avg: float
    processing_time: float
    files: Dict[str, str]
    circuit_summary: Optional[Dict[str, int]] = None
    

class JobStatus(BaseModel):
    """Job status information"""
    job_id: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    result: Optional[DetectionResponse] = None


# ============================================================================
# Helper Functions
# ============================================================================

def get_user_id_from_token(authorization: Optional[str] = None) -> Optional[int]:
    """Extract user ID from authorization header"""
    if not authorization or not DATABASE_AVAILABLE:
        return None
    
    try:
        # Extract token from "Bearer <token>"
        if not authorization.startswith("Bearer "):
            return None
        
        token = authorization.replace("Bearer ", "")

        # Import JWT library
        import jwt

        # No fallback signing key. A default here would validate any token
        # forged with that publicly known string, which is an authentication
        # bypass for every account. Without a configured key, nobody is
        # authenticated and the job runs anonymously.
        SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
        if not SECRET_KEY:
            print("⚠️  JWT_SECRET_KEY is not set - treating request as anonymous")
            return None

        # Decode token
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        
        # Get user email from token
        email = payload.get("sub")
        if not email:
            return None
        
        # Look up user in database
        if SessionLocal:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    print(f"✅ Authenticated user: {email} (ID: {user.id})")
                    return user.id
            finally:
                db.close()
        
        return None
        
    except Exception as e:
        print(f"⚠️  Token validation failed: {str(e)}")
        return None


def log_detection_to_db(
    user_id: Optional[int],
    job_id: str,
    filename: str,
    detections_count: int,
    processing_time: float,
    model_name: str,
    class_counts: Dict[str, int]
):
    """Save detection to database - OPTIONAL"""
    if not DATABASE_AVAILABLE or not DB_MODELS_AVAILABLE or not SessionLocal:
        print(f"ℹ️  Database logging skipped (not available)")
        return
    
    db = SessionLocal()
    try:
        usage_log = UsageLog(
            user_id=user_id,
            endpoint="/api/detect",
            file_count=1,
            detections_count=detections_count,
            processing_time=processing_time,
            model_name=model_name,
            credits_used=1
        )
        db.add(usage_log)
        db.commit()
        
        print(f"✅ Logged detection to database: {detections_count} symbols found")
    except Exception as e:
        print(f"⚠️  Failed to log detection: {str(e)}")
        db.rollback()
    finally:
        db.close()

# Database connection for getting default model.
#
# Prefer DATABASE_URL: it is what compose actually injects, and the piecewise
# DB_* variables are not set anywhere. Their defaults pointed at a host that
# does not exist on the compose network ("mepdetect-postgres" instead of
# "postgres"), so every lookup failed with "could not translate host name" and
# the default model silently fell back to yolo11s (COCO) — detections on real
# drawings came back empty.
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "mepdetect"),
        user=os.getenv("DB_USER", "mepdetect"),
        password=os.getenv("DB_PASSWORD", ""),
    )

def get_default_model_path():
    """Get the default model path from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT file_path, name, display_name 
            FROM models 
            WHERE is_default = true AND is_active = true 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            model_path = result['file_path']
            if os.path.exists(model_path):
                return model_path, result['name'], result['display_name']
            else:
                print(f"Warning: Default model file not found: {model_path}")
                return None, None, None
        else:
            print("Warning: No default model configured in database")
            return None, None, None
            
    except Exception as e:
        print(f"Error getting default model: {e}")
        return None, None, None

# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "MEPdetect API",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/api/docs",
        "database_logging": DATABASE_AVAILABLE and DB_MODELS_AVAILABLE
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "model_loaded": detection_engine is not None,
        "database_available": DATABASE_AVAILABLE and DB_MODELS_AVAILABLE
    }


@app.get("/api/models")
async def list_models():
    """
    List the models a detection job can be pointed at.

    Served from the registry table, which is the same source used to resolve
    the default, so the picker and the engine cannot disagree. Falls back to
    listing the weights directory when the table is unavailable — that listing
    has no display names or metrics, but it is better than an empty picker.
    """

    models = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT name, display_name, description, file_path,
                   is_default, accuracy_metrics, supported_classes
            FROM models
            WHERE is_active = true
            ORDER BY is_default DESC, display_name
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        for row in rows:
            if not os.path.exists(row['file_path']):
                continue  # registered but the weights are gone
            classes = row['supported_classes'] or []
            models.append({
                "model_id": row['name'],
                "name": row['display_name'] or row['name'],
                "description": row['description'],
                "is_default": bool(row['is_default']),
                "num_classes": len(classes),
                "classes": classes,
                "metrics": row['accuracy_metrics'] or {},
                "size_mb": os.path.getsize(row['file_path']) / (1024 * 1024),
            })
    except Exception as e:
        print(f"Could not read the model registry, falling back to disk: {e}")

    if not models and MODELS_DIR.exists():
        for model_file in sorted(MODELS_DIR.glob("*.pt")):
            models.append({
                "model_id": model_file.stem,
                "name": model_file.stem,
                "is_default": False,
                "num_classes": 0,
                "classes": [],
                "metrics": {},
                "size_mb": model_file.stat().st_size / (1024 * 1024),
            })

    return {"models": models}


# ============================================================================
# Detection Endpoints
# ============================================================================

@dataclass
class DetectionSettings:
    """Everything about a detection job except the drawing itself."""

    confidence: float = 0.25
    dpi: int = 400
    save_annotated: bool = True
    trace_circuits: bool = False
    export_formats: str = "json,csv,excel"
    model_id: Optional[str] = None
    ref_points: Optional[str] = None
    real_distance: Optional[float] = None
    units: str = "feet"


# Each setting is declared twice, once against the multipart body and once
# against the query string under the same public name, so both ways of calling
# the endpoint are parsed and validated by FastAPI and both show up in the
# generated OpenAPI document. The descriptions live here to be stated once.
_SETTING_HELP = {
    "confidence": "Minimum detection confidence, between 0 and 1.",
    "dpi": "Resolution PDF pages are rendered at before detection.",
    "save_annotated": "Write an annotated copy of each sheet.",
    "trace_circuits": "Trace the conductors and build the netlist.",
    "export_formats": "Comma separated: json, csv, excel, netlist, dxf, pdf.",
    "model_id": "Detection model to run; omit for the configured default.",
    "ref_points": "Scale calibration: 'x1,y1,x2,y2' in rendered pixels.",
    "real_distance": "Real distance between the two ref_points.",
    "units": "Unit real_distance is stated in, e.g. feet or meters.",
}


async def detection_settings(
    confidence: Optional[float] = Form(None, description=_SETTING_HELP["confidence"]),
    dpi: Optional[int] = Form(None, description=_SETTING_HELP["dpi"]),
    save_annotated: Optional[bool] = Form(None, description=_SETTING_HELP["save_annotated"]),
    trace_circuits: Optional[bool] = Form(None, description=_SETTING_HELP["trace_circuits"]),
    export_formats: Optional[str] = Form(None, description=_SETTING_HELP["export_formats"]),
    model_id: Optional[str] = Form(None, description=_SETTING_HELP["model_id"]),
    ref_points: Optional[str] = Form(None, description=_SETTING_HELP["ref_points"]),
    real_distance: Optional[float] = Form(None, description=_SETTING_HELP["real_distance"]),
    units: Optional[str] = Form(None, description=_SETTING_HELP["units"]),
    q_confidence: Optional[float] = Query(None, alias="confidence", description=_SETTING_HELP["confidence"]),
    q_dpi: Optional[int] = Query(None, alias="dpi", description=_SETTING_HELP["dpi"]),
    q_save_annotated: Optional[bool] = Query(None, alias="save_annotated", description=_SETTING_HELP["save_annotated"]),
    q_trace_circuits: Optional[bool] = Query(None, alias="trace_circuits", description=_SETTING_HELP["trace_circuits"]),
    q_export_formats: Optional[str] = Query(None, alias="export_formats", description=_SETTING_HELP["export_formats"]),
    q_model_id: Optional[str] = Query(None, alias="model_id", description=_SETTING_HELP["model_id"]),
    q_ref_points: Optional[str] = Query(None, alias="ref_points", description=_SETTING_HELP["ref_points"]),
    q_real_distance: Optional[float] = Query(None, alias="real_distance", description=_SETTING_HELP["real_distance"]),
    q_units: Optional[str] = Query(None, alias="units", description=_SETTING_HELP["units"]),
) -> DetectionSettings:
    """
    Job settings, taken from the multipart body or from the query string.

    The upload is multipart, so sending the settings as form fields is the
    natural thing to reach for; they used to bind as query parameters only,
    which meant a form field was dropped without a word and the job quietly
    ran with the defaults. Both are read now, the form first, so neither way
    of calling the endpoint can silently do nothing.
    """

    defaults = DetectionSettings()

    def pick(form_value, query_value, name):
        for value in (form_value, query_value):
            if value is not None:
                return value
        return getattr(defaults, name)

    return DetectionSettings(
        confidence=pick(confidence, q_confidence, "confidence"),
        dpi=pick(dpi, q_dpi, "dpi"),
        save_annotated=pick(save_annotated, q_save_annotated, "save_annotated"),
        trace_circuits=pick(trace_circuits, q_trace_circuits, "trace_circuits"),
        export_formats=pick(export_formats, q_export_formats, "export_formats"),
        model_id=pick(model_id, q_model_id, "model_id"),
        ref_points=pick(ref_points, q_ref_points, "ref_points"),
        real_distance=pick(real_distance, q_real_distance, "real_distance"),
        units=pick(units, q_units, "units"),
    )


@app.post("/api/detect", response_model=JobStatus)
async def detect_symbols(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: DetectionSettings = Depends(detection_settings),
    authorization: Optional[str] = Header(None)
):
    """Upload drawing and detect symbols"""

    confidence = settings.confidence
    dpi = settings.dpi
    save_annotated = settings.save_annotated
    trace_circuits = settings.trace_circuits
    export_formats = settings.export_formats
    model_id = settings.model_id
    ref_points = settings.ref_points
    real_distance = settings.real_distance
    units = settings.units

    # Get user ID (optional)
    user_id = get_user_id_from_token(authorization)

    # Validate file type
    allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.dwg', '.dxf'}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}"
        )

    # Scale calibration: two reference pixels and their real distance
    try:
        calibration = parse_reference(ref_points, real_distance, units)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create job
    job_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": "Job queued",
        "created_at": timestamp,
        "updated_at": timestamp,
        "filename": file.filename,
        "result": None,
        "user_id": user_id
    }
    
    # Save uploaded file
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    
    file_path = job_dir / file.filename
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Process in background
    background_tasks.add_task(
        process_detection_job,
        job_id,
        file_path,
        confidence,
        dpi,
        save_annotated,
        export_formats.split(','),
        model_id,
        trace_circuits,
        calibration
    )

    return JobStatus(**jobs[job_id])


@app.post("/api/detect/batch", response_model=JobStatus)
async def detect_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    settings: DetectionSettings = Depends(detection_settings),
    authorization: Optional[str] = Header(None)
):
    """Batch detection - upload multiple files"""

    confidence = settings.confidence
    dpi = settings.dpi
    save_annotated = settings.save_annotated
    trace_circuits = settings.trace_circuits
    export_formats = settings.export_formats
    model_id = settings.model_id
    ref_points = settings.ref_points
    real_distance = settings.real_distance
    units = settings.units

    user_id = get_user_id_from_token(authorization)

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 files per batch")

    try:
        calibration = parse_reference(ref_points, real_distance, units)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create batch job
    job_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": f"Batch job with {len(files)} files queued",
        "created_at": timestamp,
        "updated_at": timestamp,
        "filename": f"batch_{len(files)}_files",
        "result": None,
        "user_id": user_id
    }
    
    # Save all files
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    
    file_paths = []
    for file in files:
        file_path = job_dir / file.filename
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        file_paths.append(file_path)
    
    # Process in background
    background_tasks.add_task(
        process_batch_job,
        job_id,
        file_paths,
        confidence,
        dpi,
        save_annotated,
        export_formats.split(','),
        model_id,
        trace_circuits,
        calibration
    )

    return JobStatus(**jobs[job_id])


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get detection job status"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**jobs[job_id])


@app.get("/api/jobs/{job_id}/download/{file_type}")
async def download_result(job_id: str, file_type: str):
    """Download detection results"""
    
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Job not completed")
    
    if 'result' not in job or not job['result']:
        raise HTTPException(status_code=404, detail="Results not found")
    
    files = job['result'].get('files', {})
    
    if file_type not in files:
        raise HTTPException(status_code=404, detail=f"File type '{file_type}' not found")
    
    file_path = Path(files[file_type])
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type='application/octet-stream'
    )


# ============================================================================
# Background Processing
# ============================================================================

def page_sources(file_path: Path, page_count: int) -> List[Optional[Tuple[Path, int]]]:
    """
    Map each processed image back to the PDF page it was rendered from.

    file_processor renders PDF pages in order, so the nth image is the nth
    page. Anything that is not a PDF has no vector geometry to offer.
    """

    if file_path.suffix.lower() != '.pdf':
        return [None] * page_count

    return [(file_path, page + 1) for page in range(page_count)]


def sheet_geometry_for(source: Optional[Tuple[Path, int]], dpi: int):
    """Vector geometry of a source page, or None for a scan or a plain image."""

    if source is None:
        return None

    pdf_path, page_number = source
    try:
        # One parse: reading the page and deciding whether it is worth reading
        # both cost a full pass over its drawing items.
        geometry = extract_sheet_geometry(pdf_path, page_number, dpi)
        return geometry if geometry.has_line_work else None
    except Exception as e:
        print(f"⚠️  Could not read vector geometry from {pdf_path.name} "
              f"page {page_number}: {str(e)}")
        return None


def mine_job_tokens(
    results: List[Dict],
    sources: List[Optional[Tuple[Path, int]]],
    dpi: int,
) -> None:
    """
    Read ratings and equipment names off each PDF sheet's text.

    Attaches the tokens to each sheet's result and the nearby ratings to its
    panel-like detections. A sheet without a text layer simply yields none.
    """

    for result, source in zip(results, sources):
        if source is None:
            continue

        pdf_path, page_number = source
        try:
            tokens = plan_tokens.extract_page_tokens(pdf_path, page_number, dpi)
        except Exception as e:
            print(f"⚠️  Token mining failed for {pdf_path.name} "
                  f"page {page_number}: {str(e)}")
            continue

        if not tokens:
            continue

        result['tokens'] = tokens
        annotated = plan_tokens.attach_ratings(
            result.get('detections', []), tokens, PANEL_KEYWORDS
        )
        print(f"🏷️  {pdf_path.name} p{page_number}: {len(tokens)} tokens, "
              f"{annotated} detections annotated")


def trace_job_circuits(
    results: List[Dict],
    output_dir: Path,
    sources: Optional[List[Optional[Tuple[Path, int]]]] = None,
    dpi: int = 400,
) -> List[str]:
    """
    Trace conductors on every processed image and attach the netlist.

    When the sheet came from a vector PDF its own line work is used, which is
    exact; a scan falls back to tracing the pixels.

    Returns the overlay images produced, one per sheet. A sheet that cannot be
    traced is skipped rather than failing the whole job.
    """

    netlist_dir = output_dir / "netlist"
    overlays = []
    sources = sources or [None] * len(results)

    for result, source in zip(results, sources):
        image_path = Path(result['image_path'])
        try:
            traced = circuit_tracer.trace(
                image_path,
                result.get('detections', []),
                output_dir=netlist_dir,
                geometry=sheet_geometry_for(source, dpi),
            )
            result['circuits'] = traced
            if traced.get('overlay_path'):
                overlays.append(traced['overlay_path'])
            print(f"🔌 Traced {image_path.name} ({traced['source']}): {traced['stats']}")
        except Exception as e:
            print(f"⚠️  Circuit tracing failed for {image_path.name}: {str(e)}")

    return overlays


def collect_overlay_files(overlays: List[str], output_dir: Path, job_id: str) -> Optional[str]:
    """Single overlay stays a PNG, several are zipped."""

    if not overlays:
        return None

    if len(overlays) == 1:
        return overlays[0]

    zip_path = output_dir / f"netlist_overlays_{job_id}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for overlay in overlays:
            zipf.write(overlay, Path(overlay).name)

    return str(zip_path)


async def process_detection_job(
    job_id: str,
    file_path: Path,
    confidence: float,
    dpi: int,
    save_annotated: bool,
    export_formats: List[str],
    model_id: Optional[str] = None,
    trace_circuits: bool = False,
    calibration: Optional[Calibration] = None
):
    """Process detection job"""
    
    try:
        # Determine model
        if model_id and model_id != 'default':
            model_path = MODELS_DIR / f"{model_id}.pt"
            if not model_path.exists():
                raise ValueError(f"Model not found: {model_id}")
            model_name = model_id
        else:
            # Get default model from database
            default_path, default_name, default_display = get_default_model_path()
            
            if default_path and os.path.exists(default_path):
                model_path = Path(default_path)
                model_name = default_name
                print(f"Using default model from database: {default_display} ({default_name})")
            else:
                # Fallback to file system search
                model_path = MODELS_DIR / "best.pt"
                if not model_path.exists():
                    model_path = MODELS_DIR / "yolo11s.pt"
                if not model_path.exists():
                    model_path = MODELS_DIR / "yolo11n.pt"
                model_name = "default_fallback"
                print(f"Using fallback model: {model_path}")
        
        # Initialize detection engine
        detection_engine = DetectionEngine(
            model_path=model_path,
            confidence_threshold=confidence
        )
        
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 10
        jobs[job_id]['message'] = 'Processing file...'
        
        # Process file
        images = await file_processor.process_file(file_path, dpi)
        
        jobs[job_id]['progress'] = 30
        jobs[job_id]['message'] = f'Detecting symbols in {len(images)} image(s)...'
        
        # Run detection
        start_time = datetime.now()
        results = []
        
        for idx, image_path in enumerate(images):
            result = await detection_engine.detect(image_path, save_annotated)
            results.append(result)
            progress = 40 + int((idx + 1) / len(images) * 40)
            jobs[job_id]['progress'] = progress
        
        processing_time = (datetime.now() - start_time).total_seconds()

        sources = page_sources(file_path, len(results))

        # Ratings and equipment names printed next to the symbols
        mine_job_tokens(results, sources, dpi)

        # Combine results
        combined_result = combine_results(results)
        combined_result['processing_time'] = processing_time

        tokens_summary = plan_tokens.summarize_tokens(
            [r.get('tokens', []) for r in results]
        )
        if tokens_summary:
            combined_result['tokens'] = tokens_summary
        if calibration:
            combined_result['calibration'] = calibration.to_dict()

        # Create output directory
        output_dir = RESULTS_DIR / job_id
        output_dir.mkdir(exist_ok=True)

        # Trace electrical connections and build the netlist
        overlays = []
        if trace_circuits:
            jobs[job_id]['progress'] = 80
            jobs[job_id]['message'] = 'Tracing circuits...'

            overlays = trace_job_circuits(results, output_dir, sources, dpi)
            combined_result['circuits'] = [
                r['circuits'] for r in results if 'circuits' in r
            ]
            combined_result['cross_sheet_circuits'] = merge_cross_sheet_circuits(
                combined_result['circuits']
            )
            combined_result['circuit_summary'] = summarize_circuits(combined_result['circuits'])
            combined_result['reconciliation'] = reconcile_takeoff(combined_result)
            if 'netlist' not in export_formats:
                export_formats = export_formats + ['netlist']

        jobs[job_id]['progress'] = 85
        jobs[job_id]['message'] = 'Generating exports...'

        # Export results
        export_files = await result_exporter.export(
            combined_result,
            output_dir,
            export_formats
        )
        
        combined_result['files'] = export_files
        combined_result['job_id'] = job_id
        combined_result['status'] = 'completed'

        overlay_file = collect_overlay_files(overlays, output_dir, job_id)
        if overlay_file:
            combined_result['files']['netlist_overlay'] = overlay_file

        # Collect annotated images
        if save_annotated:
            annotated_output_dir = output_dir / "annotated"
            annotated_output_dir.mkdir(exist_ok=True)

            annotated_paths = []
            for result in results:
                if 'annotated_path' in result and result['annotated_path']:
                    src_path = Path(result['annotated_path'])
                    if src_path.exists():
                        dst_path = annotated_output_dir / src_path.name
                        shutil.copy2(src_path, dst_path)
                        annotated_paths.append(dst_path)
            
            if annotated_paths:
                if len(annotated_paths) == 1:
                    combined_result['files']['annotated'] = str(annotated_paths[0])
                else:
                    zip_path = output_dir / f"annotated_{job_id}.zip"
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        for img_path in annotated_paths:
                            zipf.write(img_path, img_path.name)
                    combined_result['files']['annotated'] = str(zip_path)
        
        # ⭐ LOG TO DATABASE (if available) ⭐
        user_id = jobs[job_id].get('user_id')
        log_detection_to_db(
            user_id=user_id,
            job_id=job_id,
            filename=file_path.name,
            detections_count=combined_result['total_detections'],
            processing_time=processing_time,
            model_name=model_name,
            class_counts=combined_result['class_counts']
        )
        
        # Update job
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['message'] = 'Detection completed'
        jobs[job_id]['result'] = combined_result
        jobs[job_id]['updated_at'] = datetime.now().isoformat()
        
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['message'] = f'Error: {str(e)}'
        jobs[job_id]['updated_at'] = datetime.now().isoformat()
        print(f"❌ Job {job_id} failed: {str(e)}")
        raise


async def process_batch_job(
    job_id: str,
    file_paths: List[Path],
    confidence: float,
    dpi: int,
    save_annotated: bool,
    export_formats: List[str],
    model_id: Optional[str] = None,
    trace_circuits: bool = False,
    calibration: Optional[Calibration] = None
):
    """Process batch detection job"""
    
    try:
        if model_id and model_id != 'default':
            model_path = MODELS_DIR / f"{model_id}.pt"
            if not model_path.exists():
                raise ValueError(f"Model not found: {model_id}")
            model_name = model_id
        else:
            # Get default model from database
            default_path, default_name, default_display = get_default_model_path()
            
            if default_path and os.path.exists(default_path):
                model_path = Path(default_path)
                model_name = default_name
                print(f"Using default model from database: {default_display} ({default_name})")
            else:
                # Fallback to file system search
                model_path = MODELS_DIR / "best.pt"
                if not model_path.exists():
                    model_path = MODELS_DIR / "yolo11s.pt"
                if not model_path.exists():
                    model_path = MODELS_DIR / "yolo11n.pt"
                model_name = "default_fallback"
                print(f"Using fallback model: {model_path}")
        
        detection_engine = DetectionEngine(
            model_path=model_path,
            confidence_threshold=confidence
        )
        
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['message'] = f'Processing {len(file_paths)} files...'
        
        all_results = []
        batch_sources = []

        for idx, file_path in enumerate(file_paths):
            images = await file_processor.process_file(file_path, dpi)
            batch_sources.extend(page_sources(file_path, len(images)))

            for image_path in images:
                result = await detection_engine.detect(image_path, save_annotated)
                all_results.append(result)
            
            progress = int((idx + 1) / len(file_paths) * 80)
            jobs[job_id]['progress'] = progress
        
        # Ratings and equipment names printed next to the symbols
        mine_job_tokens(all_results, batch_sources, dpi)

        # Combine results
        combined_result = combine_results(all_results)

        tokens_summary = plan_tokens.summarize_tokens(
            [r.get('tokens', []) for r in all_results]
        )
        if tokens_summary:
            combined_result['tokens'] = tokens_summary
        if calibration:
            combined_result['calibration'] = calibration.to_dict()

        # Export
        output_dir = RESULTS_DIR / job_id
        output_dir.mkdir(exist_ok=True)

        # Trace electrical connections and build the netlist
        overlays = []
        if trace_circuits:
            jobs[job_id]['message'] = 'Tracing circuits...'

            overlays = trace_job_circuits(all_results, output_dir, batch_sources, dpi)
            combined_result['circuits'] = [
                r['circuits'] for r in all_results if 'circuits' in r
            ]
            combined_result['cross_sheet_circuits'] = merge_cross_sheet_circuits(
                combined_result['circuits']
            )
            combined_result['circuit_summary'] = summarize_circuits(combined_result['circuits'])
            combined_result['reconciliation'] = reconcile_takeoff(combined_result)
            if 'netlist' not in export_formats:
                export_formats = export_formats + ['netlist']

        export_files = await result_exporter.export(
            combined_result,
            output_dir,
            export_formats
        )
        
        combined_result['files'] = export_files
        combined_result['job_id'] = job_id
        combined_result['status'] = 'completed'

        overlay_file = collect_overlay_files(overlays, output_dir, job_id)
        if overlay_file:
            combined_result['files']['netlist_overlay'] = overlay_file

        # Collect annotated images
        if save_annotated:
            annotated_output_dir = output_dir / "annotated"
            annotated_output_dir.mkdir(exist_ok=True)

            annotated_paths = []
            for result in all_results:
                if 'annotated_path' in result and result['annotated_path']:
                    src_path = Path(result['annotated_path'])
                    if src_path.exists():
                        dst_path = annotated_output_dir / src_path.name
                        shutil.copy2(src_path, dst_path)
                        annotated_paths.append(dst_path)
            
            if annotated_paths:
                if len(annotated_paths) == 1:
                    combined_result['files']['annotated'] = str(annotated_paths[0])
                else:
                    zip_path = output_dir / f"annotated_{job_id}.zip"
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        for img_path in annotated_paths:
                            zipf.write(img_path, img_path.name)
                    combined_result['files']['annotated'] = str(zip_path)
        
        # Log to database
        user_id = jobs[job_id].get('user_id')
        log_detection_to_db(
            user_id=user_id,
            job_id=job_id,
            filename=f"batch_{len(file_paths)}_files",
            detections_count=combined_result['total_detections'],
            processing_time=combined_result.get('processing_time', 0),
            model_name=model_name,
            class_counts=combined_result['class_counts']
        )
        
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['result'] = combined_result
        
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['message'] = f'Error: {str(e)}'
        raise


def combine_results(results: List[Dict]) -> Dict:
    """Combine multiple detection results"""
    
    total_detections = sum(r['total_detections'] for r in results)
    
    class_counts = {}
    for result in results:
        for cls, count in result['class_counts'].items():
            class_counts[cls] = class_counts.get(cls, 0) + count
    
    all_confidences = []
    for result in results:
        all_confidences.extend(result.get('confidences', []))
    
    confidence_avg = sum(all_confidences) / len(all_confidences) if all_confidences else 0
    
    all_detections = []
    for result in results:
        # Which sheet a detection sits on - the per-sheet exports (DXF
        # overlay) and the netlist need it once results are combined.
        for det in result.get('detections', []):
            det['sheet'] = result.get('image_name', '')
        all_detections.extend(result.get('detections', []))

    return {
        "total_detections": total_detections,
        "class_counts": class_counts,
        "confidence_avg": round(confidence_avg, 3),
        "num_images": len(results),
        "detections": all_detections,
        "sheets": [
            {"name": r.get('image_name', ''), "image_path": r.get('image_path', '')}
            for r in results
        ]
    }


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    print("🚀 MEPdetect API starting...")
    print(f"📁 Upload directory: {UPLOAD_DIR}")
    print(f"📁 Results directory: {RESULTS_DIR}")
    print(f"📁 Models directory: {MODELS_DIR}")
    
    if DATABASE_AVAILABLE and DB_MODELS_AVAILABLE:
        print("✅ Database logging ENABLED")
    else:
        print("ℹ️  Database logging DISABLED (standalone mode)")
    
    model_files = sorted(MODELS_DIR.glob("*.pt"))
    if model_files:
        print(f"✅ Found {len(model_files)} model(s) in {MODELS_DIR}:")
        for model_file in model_files:
            print(f"   - {model_file.name}")
    else:
        print(f"⚠️  No *.pt files in {MODELS_DIR} — will use YOLO11 pretrained on first run")
        if MODELS_DIR.exists():
            entries = sorted(MODELS_DIR.iterdir())
            if entries:
                print(f"   Directory listing ({len(entries)} item(s)): {[p.name for p in entries[:20]]}")
            else:
                print("   Directory is empty (check MODELS_HOST_PATH / compose volume mount)")
        else:
            print("   Directory does not exist (volume mount missing?)")
    
    print("✅ API ready!")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("👋 MEPdetect API shutting down...")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )