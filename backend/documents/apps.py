from django.apps import AppConfig

class DocumentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'documents'

    def ready(self):
        # Pre-warm embedding model on Celery worker startup to eliminate first-use latency spike
        from celery.signals import worker_process_init
        
        @worker_process_init.connect
        def prewarm_models(sender=None, **kwargs):
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Worker process initialized. Pre-warming embedding model...")
            try:
                from .utils import get_embedding_model
                get_embedding_model()
            except Exception as e:
                logger.error(f"Failed to pre-warm embedding model: {str(e)}")
