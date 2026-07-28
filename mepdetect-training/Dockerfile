FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (fixed for Debian Trixie)
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

# Copy application code
COPY train_main.py .
COPY training_engine.py .
COPY dataset_manager.py .
COPY model_registry.py .

# Create necessary directories
RUN mkdir -p /app/datasets /app/models /app/training

# Download default YOLO11 models (fixed - no .pt extension)
RUN python -c "from ultralytics import YOLO; \
    YOLO('yolo11n'); \
    YOLO('yolo11s'); \
    YOLO('yolo11m')" || \
    echo "Models will download on first use"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

# Run application
CMD ["uvicorn", "train_main:app", "--host", "0.0.0.0", "--port", "8000"]