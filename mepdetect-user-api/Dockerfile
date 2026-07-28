FROM python:3.11-slim

WORKDIR /app

COPY requirements-user-api.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

CMD ["uvicorn", "user_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
