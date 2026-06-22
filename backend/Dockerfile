# Use official slim Python base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKDIR=/app

# Set work directory
WORKDIR ${WORKDIR}

# Install system dependencies (needed for compiling certain packages and PostgreSQL support)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt ${WORKDIR}/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . ${WORKDIR}/

# Expose Django port
EXPOSE 8000

# Make startup script executable
RUN chmod +x ${WORKDIR}/start.sh

# Launch Django application and background worker via startup script
CMD ["./start.sh"]
