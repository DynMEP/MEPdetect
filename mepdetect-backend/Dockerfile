FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (updated for Debian Trixie)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libgthread-2.0-0 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# OCR engine for reading circuit tags off sheets whose annotation is drawn as
# curves. Installed after the Python dependencies on purpose: adding it to the
# layer above would invalidate the pip layer and re-download torch (~2.5 GB) on
# every deploy that touches system packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY main.py .
COPY detection_engine.py .
COPY file_processor.py .
COPY result_exporter.py .
COPY circuit_tracer.py .
COPY pdf_geometry.py .
COPY segment_graph.py .
COPY calibration.py .
COPY plan_tokens.py .
COPY reconcile.py .

# ⭐ NEW: Copy database models for logging support
COPY db_models.py .
COPY auth.py .

# Diagnostics: tracing a sheet from the command line needs the same
# dependencies as the API, so the tool ships with it.
COPY tools/ ./tools/

# Create necessary directories
RUN mkdir -p /app/uploads /app/results /app/models

# Download YOLO11s model directly from GitHub
RUN wget -q https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt -O /app/models/yolo11s.pt && \
    echo "✅ Model downloaded to /app/models/"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]