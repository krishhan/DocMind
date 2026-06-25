#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "==> Gathering static files..."
python manage.py collectstatic --noinput

echo "==> Running database migrations..."
python manage.py migrate

echo "==> Starting Celery worker in background..."
celery -A docmind worker --loglevel=info > /dev/stdout 2>&1 &

# Get workers parameter from GUNICORN_WORKERS env var, default to 3
WORKERS_COUNT=${GUNICORN_WORKERS:-3}

echo "==> Starting Gunicorn WSGI server on port ${PORT:-8000} with ${WORKERS_COUNT} workers..."
exec gunicorn docmind.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WORKERS_COUNT} \
    --timeout 120
