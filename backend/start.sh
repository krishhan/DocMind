#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "==> Gathering static files..."
python manage.py collectstatic --noinput

echo "==> Running database migrations..."
python manage.py migrate

if [ -n "$REDIS_URL" ]; then
  echo "==> Starting Celery worker in background..."
  celery -A docmind worker --loglevel=info > /dev/stdout 2>&1 &
else
  echo "==> REDIS_URL not set; running in synchronous eager mode..."
fi

# Get workers parameter from GUNICORN_WORKERS env var, default to 1 for 512MB RAM free tier
WORKERS_COUNT=${GUNICORN_WORKERS:-1}
THREADS_COUNT=${GUNICORN_THREADS:-2}

echo "==> Starting Gunicorn WSGI server on port ${PORT:-8000} with ${WORKERS_COUNT} worker(s) and ${THREADS_COUNT} thread(s)..."
exec gunicorn docmind.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WORKERS_COUNT} \
    --threads ${THREADS_COUNT} \
    --timeout 120
