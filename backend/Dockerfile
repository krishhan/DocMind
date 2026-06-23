# Use official slim Python base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKDIR=/app

# Set work directory
WORKDIR ${WORKDIR}

# Install system dependencies (needed for compiling certain packages, PostgreSQL support, and OpenCV/RapidOCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt ${WORKDIR}/
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download and cache sentence-transformers and OCR models to avoid runtime download/OOM issues
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"

# Copy project files
COPY . ${WORKDIR}/

# Expose Django port
EXPOSE 8000

# Make startup script executable
RUN chmod +x ${WORKDIR}/start.sh

# Launch Django application and background worker via startup script
CMD ["./start.sh"]
