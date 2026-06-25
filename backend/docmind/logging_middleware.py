import time
import uuid
import logging
import threading

logger = logging.getLogger('django.request')

# Thread-local storage for request-specific log context
_log_context = threading.local()

def get_log_context():
    if not hasattr(_log_context, 'data'):
        _log_context.data = {}
    return _log_context.data

class LoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Start timer & initialize context
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        ctx = get_log_context()
        ctx.clear()  # reset for current thread
        ctx['request_id'] = request_id
        ctx['path'] = request.path
        ctx['method'] = request.method
        
        request.request_id = request_id

        # 2. Call next middleware/view (User object is populated during this phase)
        response = self.get_response(request)

        # 3. Bind user id if authenticated
        if hasattr(request, 'user') and request.user.is_authenticated:
            ctx['user_id'] = request.user.id

        # 4. Finalize duration and log
        duration = time.time() - start_time
        ctx['processing_duration'] = duration
        
        # Determine log level
        log_level = logging.INFO
        if response.status_code >= 500:
            log_level = logging.ERROR
            
        # Log using structured logger. Custom JSONFormatter will serialize 'extra' fields.
        logger.log(
            log_level,
            f"{request.method} {request.path} - {response.status_code} - {duration:.4f}s",
            extra=ctx
        )
        
        # Clean up thread local context
        ctx.clear()
        
        return response

    def process_exception(self, request, exception):
        ctx = get_log_context()
        ctx['errors'] = str(exception)
        return None
