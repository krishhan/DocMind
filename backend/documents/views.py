import os
import logging
from rest_framework import status, permissions, generics
from rest_framework.response import Response
from .models import Document
from .serializers import DocumentSerializer
from .utils import get_chroma_collection
from .tasks import process_document_task

logger = logging.getLogger(__name__)

def is_valid_pdf(file_obj):
    # PDF Signature Check
    header = file_obj.read(5)
    file_obj.seek(0)
    if header != b'%PDF-':
        return False, "Invalid file format. The file is not a valid PDF document (missing %PDF- header)."
        
    # MIME Type Check via python-magic
    try:
        import magic
        # Read the first 2048 bytes for magic analysis
        buffer = file_obj.read(2048)
        file_obj.seek(0)
        mime = magic.from_buffer(buffer, mime=True)
        if mime != 'application/pdf':
            return False, f"Invalid content type: {mime}. Only PDF files are supported."
    except Exception as e:
        logger.warning(f"python-magic validation bypassed: {str(e)}. Falling back to client-provided MIME.")
        if getattr(file_obj, 'content_type', '') != 'application/pdf':
            return False, "Invalid content type. Only PDF files are supported."
            
    return True, None

class DocumentListUploadView(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        
        # Automatically fail any documents stuck in processing for more than 5 minutes
        stuck_threshold = timezone.now() - timedelta(minutes=5)
        stuck_docs = Document.objects.filter(
            owner=self.request.user,
            status='processing',
            upload_date__lt=stuck_threshold
        )
        for doc in stuck_docs:
            doc.status = 'failed'
            doc.error_message = "Processing timed out. The server might have restarted or run out of memory. Please try again."
            doc.save()
            logger.warning(f"Marked stuck Document ID {doc.id} as failed.", extra={"document_id": doc.id})

        return Document.objects.filter(owner=self.request.user).select_related('owner').order_by('-upload_date')

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not file_obj.name.lower().endswith('.pdf'):
            return Response({"error": "Only PDF files are supported."}, status=status.HTTP_400_BAD_REQUEST)
        
        if file_obj.size > 10 * 1024 * 1024:
            return Response({"error": "File size exceeds the 10MB limit."}, status=status.HTTP_400_BAD_REQUEST)

        # Content/signature validation
        is_valid, err_msg = is_valid_pdf(file_obj)
        if not is_valid:
            return Response({"error": err_msg}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save()
        
        # Trigger background task asynchronously
        from django.conf import settings
        import threading
        if settings.CELERY_TASK_ALWAYS_EAGER:
            threading.Thread(
                target=process_document_task,
                args=(document.id,),
                daemon=True
            ).start()
        else:
            process_document_task.delay(document.id)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class DocumentDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        # Clean up ChromaDB vectors for this document
        try:
            collection = get_chroma_collection()
            # chroma where clause filters by document_id metadata field
            collection.delete(where={"document_id": instance.id})
            logger.info(f"Deleted vectors for Document ID {instance.id} from ChromaDB")
        except Exception as e:
            logger.error(f"Failed to delete ChromaDB vectors for document {instance.id}: {str(e)}")
        
        # Clean up local PDF file
        if instance.file:
            try:
                if os.path.exists(instance.file.path):
                    os.remove(instance.file.path)
                    logger.info(f"Deleted file {instance.file.path} from media storage")
            except Exception as e:
                logger.error(f"Failed to delete file {instance.file.name}: {str(e)}")
                
        instance.delete()
